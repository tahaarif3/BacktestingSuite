"""Tests for the replay session service (order rejections, scoring, lifecycle,
persistence). All network-free: a synthetic parquet stands in for market data.
"""

import math

import pandas as pd
import pytest

from desktop.backend import paths
from desktop.backend.services import data_service
from desktop.backend.services import replay_service as R
from desktop.backend.schemas import (
    CreateReplaySessionRequest,
    ReplaySessionConfig,
    ReplayOrderRequest,
    DataConfig,
)


def _make_parquet(path, n=220):
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    rows = []
    price = 100.0
    for i in range(n):
        price *= 1.0 + 0.004 * math.sin(i / 7.0) + 0.0005
        rows.append((price * 0.998, price * 1.012, price * 0.988, price, 1_000_000.0))
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    df.index.name = "timestamp"
    df.to_parquet(path)


@pytest.fixture
def env(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    sess_dir = tmp_path / "sessions"
    data_dir.mkdir()
    sess_dir.mkdir()
    _make_parquet(str(data_dir / "synth.parquet"))
    monkeypatch.setattr(data_service, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(paths, "SESSIONS_DIR", str(sess_dir))
    R._SESSIONS.clear()
    yield {"data_dir": data_dir, "sess_dir": sess_dir}
    R._SESSIONS.clear()


def _cfg(**kw):
    base = dict(
        strategy="sma",
        params={"fast_window": 5, "slow_window": 20},
        sizer="fixed_shares",
        sizer_value=100,
        capital=100000.0,
        warmup_bars=25,
        data=DataConfig(source="file", file="synth.parquet"),
    )
    base.update(kw)
    return ReplaySessionConfig(**base)


def _create(**kw):
    return R.create_session(CreateReplaySessionRequest(config=_cfg(**kw)))


# --- creation ---------------------------------------------------------------


def test_create_inlines_bars_and_events(env):
    resp = _create()
    assert resp["total_bars"] == 220
    assert resp["start_index"] == 25
    assert resp["bars"] is not None            # 220 <= DEFAULT_BAR_CHUNK
    assert resp["causality"]["causal"] is True
    assert len(resp["bars"]["c"]) == 220


def test_create_rejects_oversized(env, monkeypatch):
    monkeypatch.setattr(R, "MAX_SESSION_BARS", 10)
    with pytest.raises(R.SessionTooLarge):
        _create()


# --- order rejections (assert the order list never grows) -------------------


def _order_count(sid):
    return len(R._SESSIONS[sid].orders)


def test_reject_before_start(env):
    # The frontend enforces "trade at the current bar"; the backend's guards are
    # the start bar and the forward-only (high-water) rule. A bar before the
    # start index is rejected.
    resp = _create()
    sid = resp["session_id"]
    start = resp["start_index"]
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=start - 1, side="buy",
                                               qty_mode="shares", qty_value=10))
    assert _order_count(sid) == 0


def test_reject_past_bar_after_trading(env):
    resp = _create()
    sid = resp["session_id"]
    start = resp["start_index"]
    R.submit_order(sid, ReplayOrderRequest(bar_index=start + 10, side="buy",
                                           qty_mode="shares", qty_value=10))
    assert _order_count(sid) == 1
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=start + 5, side="buy",
                                               qty_mode="shares", qty_value=10))
    assert _order_count(sid) == 1


def test_reject_last_bar(env):
    resp = _create()
    sid = resp["session_id"]
    last = resp["total_bars"] - 1
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=last, side="buy",
                                               qty_mode="shares", qty_value=10))
    assert _order_count(sid) == 0


def test_reject_non_positive_qty(env):
    resp = _create()
    sid = resp["session_id"]
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=resp["start_index"], side="buy",
                                               qty_mode="shares", qty_value=0))
    assert _order_count(sid) == 0


def test_reject_short_when_disabled(env):
    resp = _create(short=False)
    sid = resp["session_id"]
    start = resp["start_index"]
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=start, side="sell",
                                               qty_mode="shares", qty_value=50))
    assert _order_count(sid) == 0


def test_short_allowed_when_enabled(env):
    resp = _create(short=True)
    sid = resp["session_id"]
    start = resp["start_index"]
    r = R.submit_order(sid, ReplayOrderRequest(bar_index=start, side="sell",
                                               qty_mode="shares", qty_value=50))
    assert r["accepted"] and r["state"]["account"]["position"] < 0


def test_cash_overdraft_rejected_then_allowed_under_unlimited(env):
    # A buy far exceeding cash: rejected under cash_only, accepted under unlimited.
    resp = _create(margin_policy="cash_only")
    sid = resp["session_id"]
    start = resp["start_index"]
    with pytest.raises(R.OrderRejected):
        R.submit_order(sid, ReplayOrderRequest(bar_index=start, side="buy",
                                               qty_mode="fraction", qty_value=5.0))
    assert _order_count(sid) == 0

    resp2 = _create(margin_policy="unlimited")
    sid2 = resp2["session_id"]
    r = R.submit_order(sid2, ReplayOrderRequest(bar_index=resp2["start_index"], side="buy",
                                                qty_mode="fraction", qty_value=5.0))
    assert r["accepted"]
    assert r["state"]["account"]["cash"] < 0


# --- scoring ----------------------------------------------------------------


def _follow_algo(sid):
    """Place a match-algo order at every bar so the user reproduces the algo."""
    s = R._SESSIONS[sid]
    for b in range(s.start_index, len(s.bars) - 1):
        R.submit_order(sid, ReplayOrderRequest(bar_index=b, side="buy", qty_mode="algo"))


def test_following_algo_perfectly_ties_algo(env):
    resp = _create()
    sid = resp["session_id"]
    _follow_algo(sid)
    sc = R.score(sid)
    for k in ("Total Return", "Sharpe Ratio", "Max Drawdown"):
        assert sc["user"]["summary"][k] == pytest.approx(sc["algo"]["summary"][k], abs=1e-6)


def test_doing_nothing_scores_flat(env):
    resp = _create()
    sid = resp["session_id"]
    R.seek(sid, resp["total_bars"] - 1)
    sc = R.score(sid)
    assert sc["user"]["summary"]["Total Return"] == pytest.approx(0.0, abs=1e-9)
    assert sc["user"]["summary"]["Total Trades"] == 0


def test_buy_hold_pays_costs(env):
    resp = _create(slippage_pct=0.001, commission_pct=0.001)
    sid = resp["session_id"]
    R.seek(sid, resp["total_bars"] - 1)
    sc = R.score(sid)
    # B&H equity ends below a costless benchmark because it paid entry costs.
    bh_final = sc["buy_hold"]["series"]["equity"][-1]
    bench_final = sc["buy_hold"]["series"]["benchmark"][-1]
    assert bh_final < bench_final


# --- undo / rewind / reset --------------------------------------------------


def test_undo_and_reset(env):
    resp = _create()
    sid = resp["session_id"]
    start = resp["start_index"]
    R.submit_order(sid, ReplayOrderRequest(bar_index=start, side="buy", qty_mode="shares", qty_value=10))
    R.submit_order(sid, ReplayOrderRequest(bar_index=start + 3, side="buy", qty_mode="shares", qty_value=10))
    assert _order_count(sid) == 2
    R.undo_last_order(sid)
    assert _order_count(sid) == 1
    R.reset(sid)
    assert _order_count(sid) == 0
    st = R.get_state(sid)
    assert st["cursor"] == start and st["high_water"] == start


def test_rewind_requires_confirmation(env):
    resp = _create()
    sid = resp["session_id"]
    start = resp["start_index"]
    R.submit_order(sid, ReplayOrderRequest(bar_index=start + 5, side="buy", qty_mode="shares", qty_value=10))
    with pytest.raises(R.OrderRejected):
        R.rewind(sid, start)  # would drop an order without confirm
    R.rewind(sid, start, confirm_discard_orders=True)
    assert _order_count(sid) == 0


# --- bars chunking ----------------------------------------------------------


def test_bars_chunk_bounds(env):
    resp = _create()
    sid = resp["session_id"]
    with pytest.raises(ValueError):
        R.get_bars(sid, 0, R.MAX_BAR_CHUNK + 1)
    with pytest.raises(IndexError):
        R.get_bars(sid, 10_000, 10)
    chunk = R.get_bars(sid, 0, 50)
    assert chunk["count"] == 50 and chunk["total"] == 220


# --- lifecycle & persistence ------------------------------------------------


def test_lru_eviction(env):
    ids = [_create()["session_id"] for _ in range(R.MAX_SESSIONS + 2)]
    assert len(R._SESSIONS) == R.MAX_SESSIONS
    # oldest evicted, newest kept
    assert ids[0] not in R._SESSIONS
    assert ids[-1] in R._SESSIONS


def test_persist_rehydrate_roundtrip(env):
    resp = _create()
    sid = resp["session_id"]
    start = resp["start_index"]
    R.submit_order(sid, ReplayOrderRequest(bar_index=start, side="buy", qty_mode="shares", qty_value=10))
    R.submit_order(sid, ReplayOrderRequest(bar_index=start + 4, side="close"))
    before = R.get_state(sid)

    R._SESSIONS.clear()
    recovered = R.rehydrate_all()
    assert sid in recovered
    after = R.get_state(sid)
    assert after["cursor"] == before["cursor"]
    assert len(after["orders"]) == len(before["orders"])
    assert after["account"]["equity"] == pytest.approx(before["account"]["equity"], abs=1e-6)


def test_stale_fingerprint_on_data_change(env):
    resp = _create()
    sid = resp["session_id"]
    # rewrite the underlying parquet with different data
    _make_parquet(str(env["data_dir"] / "synth.parquet"), n=180)
    R._SESSIONS.clear()
    R.rehydrate_all()
    assert R._SESSIONS[sid].stale is True
    with pytest.raises(R.SessionStale):
        R.get_state(sid)


def test_delete_session(env):
    resp = _create()
    sid = resp["session_id"]
    R.delete_session(sid)
    assert sid not in R._SESSIONS
    with pytest.raises(R.SessionNotFound):
        R.get_state(sid)

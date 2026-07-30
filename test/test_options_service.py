"""Options replay session + backtest service integration."""

import pytest

from desktop.backend.schemas import (
    BacktestConfig,
    CreateReplaySessionRequest,
    DataConfig,
    OptionPreviewRequest,
    OptionStructureConfig,
    ReplayOptionOrderRequest,
    ReplaySessionConfig,
    VolModelConfig,
)
from desktop.backend.services import backtest_service
from desktop.backend.services import replay_service as R


def _cfg(**over):
    base = dict(
        strategy="rs_breakout", params={},
        capital=100000, timing="next_close", warmup_bars=60, mode="options",
        options=OptionStructureConfig(structure_type="bear_call_spread", selection="delta",
                                      short_delta=0.30, width=5, dte_bars=20, contracts=1, grid_spacing=1),
        vol=VolModelConfig(iv_multiplier=1.2),
        data=DataConfig(source="file", file="spy_daily_yfinance.parquet"),
    )
    base.update(over)
    return ReplaySessionConfig(**base)


def test_options_backtest_run():
    cfg = BacktestConfig(strategy="rs_breakout", params={}, mode="options",
                         options=OptionStructureConfig(structure_type="bear_call_spread", dte_bars=20,
                                                       width=5, contracts=1, grid_spacing=1),
                         vol=VolModelConfig(iv_multiplier=1.2),
                         data=DataConfig(source="file", file="spy_daily_yfinance.parquet"))
    r = backtest_service.run_backtest(cfg)
    assert r["mode"] == "options"
    assert "option_trades" in r
    assert "summary" in r and "series" in r
    assert len(r["series"]["equity"]) > 0


def test_options_session_lifecycle():
    created = R.create_session(CreateReplaySessionRequest(config=_cfg()))
    sid = created["session_id"]
    try:
        assert created["mode"] == "options"
        assert "options_account" in created
        cur = created["start_index"]

        # preview a bear call spread
        pv = R.preview_option(sid, OptionPreviewRequest(bar_index=cur, structure=_cfg().options))
        assert pv["net_is_credit"] is True
        assert pv["max_loss"] is not None and pv["max_profit"] is not None
        assert len(pv["legs"]) == 2
        assert len(pv["payoff"]) > 10

        # open a structure
        res = R.submit_option_order(sid, ReplayOptionOrderRequest(bar_index=cur, action="open",
                                                                  structure=_cfg().options))
        acct = res["state"]["options_account"]
        assert len(acct["positions"]) == 1
        assert acct["net_delta"] < 0            # bear call spread is short delta
        pos_id = acct["positions"][0]["id"]

        # close it a few bars later
        R.seek(sid, cur + 5)
        res2 = R.submit_option_order(sid, ReplayOptionOrderRequest(
            bar_index=cur + 5, action="close", target_structure_id=pos_id))
        assert len(res2["state"]["options_account"]["positions"]) == 0

        # score is options-shaped
        sc = R.score(sid)
        assert sc["mode"] == "options"
        assert "option_trades" in sc["user"]
        assert "option_trades" in sc["algo"]
    finally:
        R.delete_session(sid)


def test_naked_short_rejected_without_regt():
    cfg = _cfg(options=OptionStructureConfig(structure_type="short_call", selection="delta",
                                             short_delta=0.30, dte_bars=20, contracts=1, grid_spacing=1),
               vol=VolModelConfig(margin_policy="defined_risk"))
    created = R.create_session(CreateReplaySessionRequest(config=cfg))
    sid = created["session_id"]
    try:
        cur = created["start_index"]
        with pytest.raises(R.OrderRejected):
            R.submit_option_order(sid, ReplayOptionOrderRequest(
                bar_index=cur, action="open", structure=cfg.options))
    finally:
        R.delete_session(sid)


def test_equity_order_rejected_in_options_session():
    from desktop.backend.schemas import ReplayOrderRequest
    created = R.create_session(CreateReplaySessionRequest(config=_cfg()))
    sid = created["session_id"]
    try:
        with pytest.raises(R.OrderRejected):
            R.submit_order(sid, ReplayOrderRequest(bar_index=created["start_index"], side="buy",
                                                   qty_mode="fraction", qty_value=0.5))
    finally:
        R.delete_session(sid)

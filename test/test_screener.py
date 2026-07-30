"""RS-Breakout diagnostics + the multi-symbol screener."""

import os

import pytest

from data.dataloader import DataLoader
from strat.rs_breakout import RSBreakoutStrategy
from desktop.backend.services import screener_service as S
from desktop.backend.paths import DATA_DIR


def test_diagnostics_signal_matches_generate_signals():
    path = os.path.join(DATA_DIR, "spy_daily_yfinance.parquet")
    bars = DataLoader().get_bars(path)[:600]
    strat = RSBreakoutStrategy()
    diag = strat.diagnostics(bars)
    assert diag["signal"] == strat.generate_signals(bars)  # single source of truth
    assert len(diag["regime_armed"]) == len(bars)
    assert set(diag["signal"]) <= {0.0, 1.0}


def _cached(sym):
    return os.path.exists(os.path.join(DATA_DIR, f"{sym}_1d.parquet"))


@pytest.mark.skipif(not _cached("NVDA"), reason="requires cached NVDA data")
def test_scan_ranks_cached_symbols():
    # refresh=False -> use cached parquet, no network.
    res = S.scan(["NVDA", "AAPL"], start="2019-01-01", end="2024-12-31",
                 interval="1d", params={}, window=60, refresh=False)
    assert res["scanned"] == 2
    syms = {r["symbol"] for r in res["results"]}
    assert syms == {"NVDA", "AAPL"}
    # sorted by score descending
    scores = [r["score"] for r in res["results"]]
    assert scores == sorted(scores, reverse=True)
    for r in res["results"]:
        assert "file" in r and r["file"].endswith(".parquet")
        assert isinstance(r["armed_now"], bool)
        assert r["has_reference"] is True


def test_scan_reports_errors_for_bad_ticker():
    res = S.scan(["NVDA", "ZZZZ_NOT_A_TICKER"], start="2019-01-01", end="2024-12-31",
                 interval="1d", params={}, window=60, refresh=False)
    # the bad symbol is skipped into errors, not crashing the scan
    ok = {r["symbol"] for r in res["results"]}
    bad = {e["symbol"] for e in res["errors"]}
    assert "ZZZZ_NOT_A_TICKER" in (ok | bad)

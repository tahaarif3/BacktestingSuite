"""Portfolio replay session service (uses cached data, no network)."""

import os

import pytest

from desktop.backend.services import portfolio_service as P
from desktop.backend.paths import DATA_DIR


def _cached(sym):
    return os.path.exists(os.path.join(DATA_DIR, f"{sym}_1d.parquet"))


pytestmark = pytest.mark.skipif(
    not (_cached("NVDA") and _cached("AAPL")),
    reason="requires cached NVDA/AAPL data",
)


def _make():
    return P.create_session({
        "tickers": ["NVDA", "AAPL"],
        "start": "2019-01-01", "end": "2024-12-31",
        "capital": 100000, "warmup_bars": 150, "refresh": False,
        "vol": {"iv_multiplier": 1.2},
    })


def test_create_and_radar():
    created = _make()
    sid = created["session_id"]
    try:
        assert created["symbols"] == ["NVDA", "AAPL"]
        assert created["total_bars"] > 200
        assert "signal_bars" in created
        radar = created["state"]["radar"]
        assert {r["symbol"] for r in radar} == {"NVDA", "AAPL"}
        for r in radar:
            assert isinstance(r["armed"], bool)
    finally:
        P.delete_session(sid)


def test_open_and_close_options_on_a_symbol():
    created = _make()
    sid = created["session_id"]
    start = created["start_index"]
    try:
        res = P.submit_order(sid, {
            "bar_index": start, "symbol": "NVDA", "action": "open",
            "structure": {"structure_type": "bull_put_spread", "selection": "delta",
                          "short_delta": 0.3, "width": 5, "dte_bars": 20, "contracts": 1,
                          "grid_spacing": 1},
        })
        acct = res["state"]["account"]
        assert len(acct["positions"]) == 1
        assert acct["positions"][0]["symbol"] == "NVDA"
        pos_id = acct["positions"][0]["id"]

        P.seek(sid, start + 5)
        res2 = P.submit_order(sid, {
            "bar_index": start + 5, "symbol": "NVDA", "action": "close",
            "target_structure_id": pos_id,
        })
        assert len(res2["state"]["account"]["positions"]) == 0

        sc = P.score(sid)
        assert sc["total_trades"] >= 1
        assert len(sc["equity"]) == sc["cursor"] + 1
    finally:
        P.delete_session(sid)


def test_shared_cash_across_symbols():
    created = _make()
    sid = created["session_id"]
    start = created["start_index"]
    try:
        cash0 = created["state"]["account"]["cash"]
        P.submit_order(sid, {"bar_index": start, "symbol": "NVDA", "action": "open",
                             "structure": {"structure_type": "bull_put_spread", "width": 5,
                                           "dte_bars": 20, "contracts": 1, "grid_spacing": 1}})
        st = P.submit_order(sid, {"bar_index": start + 1, "symbol": "AAPL", "action": "open",
                                  "structure": {"structure_type": "bear_call_spread", "width": 5,
                                                "dte_bars": 20, "contracts": 1, "grid_spacing": 1}})
        acct = st["state"]["account"]
        # both positions share ONE cash account
        assert len(acct["positions"]) == 2
        assert {p["symbol"] for p in acct["positions"]} == {"NVDA", "AAPL"}
        assert acct["cash"] != cash0
    finally:
        P.delete_session(sid)

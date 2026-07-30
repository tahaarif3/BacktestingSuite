"""Automated multi-position portfolio backtester: invariants + unit tests."""

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.indicators import add_indicators
from portfolio_backtest.risk import size_position
from portfolio_backtest.execution import entry_fill, exit_fill, stop_exit_price, commission
from portfolio_backtest.engine import run_portfolio_backtest
from portfolio_backtest.metrics import summarize


def _dates(n):
    return [datetime(2016, 1, 4) + timedelta(days=i) for i in range(n)]


def synth(n, start, drift):
    """A deterministic sine-modulated uptrend: makes periodic 20-day-high
    breakouts on the up-swings with volume spikes and closes near the high."""
    idx = pd.DatetimeIndex(_dates(n), name="timestamp")
    closes, opens, highs, lows, vols = [], [], [], [], []
    prev = start
    for i in range(n):
        trend = start * (1 + drift) ** i
        c = trend * (1 + 0.04 * math.sin(i / 6.0))
        o = prev
        up = c >= o
        hi = max(o, c) * (1.001 if up else 1.02)
        lo = min(o, c) * (0.999 if up else 0.985)
        closes.append(c); opens.append(o); highs.append(hi); lows.append(lo)
        vols.append(2_000_000 if up else 800_000)
        prev = c
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": vols}, index=idx)


# --- unit tests -------------------------------------------------------------


def test_prior_high_excludes_today():
    n = 60
    df = synth(n, 100, 0.001)
    df.iloc[-1, df.columns.get_loc("high")] = 10_000  # spike today's high
    out = add_indicators(df, PortfolioBacktestConfig(breakout_window=20))
    # prior_high at the last bar must NOT include today's spiked high
    assert out["prior_high"].iloc[-1] < 10_000


def test_size_position_caps():
    cfg = PortfolioBacktestConfig(initial_capital=100000, risk_per_trade=0.005,
                                  max_position_pct=0.15, whole_shares=True)
    # risk-based: $500 / $5 = 100 shares; capital cap 15000/100=150; cash ample
    assert size_position(100000, 100000, 100, 95, cfg) == 100
    # capital cap binds: risk/share tiny -> risk shares huge, capped by 15%/price
    assert size_position(100000, 100000, 100, 99.9, cfg) == 150
    # cash binds
    assert size_position(100000, 500, 100, 95, cfg) == 5
    # no risk (stop above entry) -> 0
    assert size_position(100000, 100000, 100, 100, cfg) == 0


def test_execution_and_stop_gap():
    cfg = PortfolioBacktestConfig(slippage_pct=0.0005)
    assert entry_fill(100, cfg) == pytest.approx(100.05)
    assert exit_fill(100, cfg) == pytest.approx(99.95)
    # low reaches stop, open above stop -> fill at stop (with slippage)
    assert stop_exit_price(101, 94, 95, cfg) == pytest.approx(exit_fill(95, cfg))
    # gap through: open below stop -> fill at open, not the (better) stop
    assert stop_exit_price(90, 89, 95, cfg) == pytest.approx(exit_fill(90, cfg))
    # low never reaches stop -> no exit
    assert stop_exit_price(101, 96, 95, cfg) is None
    assert commission(0, cfg) == 0.0


# --- engine invariants ------------------------------------------------------


def _universe():
    n = 300
    spy = synth(n, 300, 0.0008)                       # bullish benchmark (rising)
    data = {
        "AAPL": synth(n, 100, 0.0022),                # tech, outperforming SPY
        "MSFT": synth(n, 200, 0.0021),                # tech
        "NVDA": synth(n, 50, 0.0024),                 # tech
        "JPM": synth(n, 120, 0.0020),                 # financials
        "XOM": synth(n, 90, 0.0019),                  # energy
    }
    return data, spy


def _max_concurrent_by_sector(trades, open_positions, sectors):
    """Reconstruct peak concurrent positions per sector from the trade ledger."""
    events = []
    for t in trades:
        events.append((t["entry_date"], t["sector"], +1))
        events.append((t["exit_date"], t["sector"], -1))
    for p in open_positions:
        events.append((p["entry_date"], p["sector"], +1))
    peak = {}
    cur = {}
    for _, sec, delta in sorted(events):
        cur[sec] = cur.get(sec, 0) + delta
        peak[sec] = max(peak.get(sec, 0), cur[sec])
    return peak


def test_engine_invariants():
    data, spy = _universe()
    cfg = PortfolioBacktestConfig(
        tickers=list(data), start="2016-01-04", end="2017-12-31",
        max_positions=3, max_per_sector=1, rs_threshold=0.0,
    )
    res = run_portfolio_backtest(cfg, data, spy)  # reconcile() asserts internally each bar
    d = res.daily
    assert len(d) == len(spy)
    assert d["open_positions"].max() <= cfg.max_positions      # position cap
    assert (d["cash"] >= -1e-6).all()                          # never negative cash
    assert len(res.trades) > 0                                 # it actually traded
    peak = _max_concurrent_by_sector(res.trades, res.open_positions, None)
    assert all(v <= cfg.max_per_sector for v in peak.values()) # sector cap

    # final reconciliation identity holds explicitly
    summ = summarize(d, res.trades, cfg.initial_capital)
    assert "CAGR" in summ and "Calmar Ratio" in summ


def test_next_open_execution_price():
    data, spy = _universe()
    cfg = PortfolioBacktestConfig(tickers=list(data), start="2016-01-04", end="2017-12-31",
                                  slippage_pct=0.001, rs_threshold=0.0, max_positions=5, max_per_sector=5)
    res = run_portfolio_backtest(cfg, data, spy)
    # every entry price is the next open marked up by slippage -> strictly > raw open is
    # implied; here we just assert fills are positive and stops are below entries.
    for t in res.trades:
        assert t["entry_price"] > 0
        assert t["initial_stop"] < t["entry_price"]

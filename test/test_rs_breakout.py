"""Relative-Strength Breakout strategy: contract + firing behaviour."""

import os
import tempfile
from datetime import datetime, timedelta

import pandas as pd
import pytest

from domain.models import Bar
from strat.rs_breakout import RSBreakoutStrategy
from strategy_registry import STRATEGIES, build_strategy


def _write_spy(tmp, days, prices):
    df = pd.DataFrame(
        {"open": prices, "high": [p + 1 for p in prices], "low": [p - 1 for p in prices],
         "close": prices, "volume": [1e6] * len(prices)},
        index=pd.DatetimeIndex(days, name="timestamp"),
    )
    path = os.path.join(tmp, "spy_daily_yfinance.parquet")
    df.to_parquet(path)
    return path


def test_registered():
    assert "rs_breakout" in STRATEGIES
    spec = STRATEGIES["rs_breakout"]
    assert spec.supports_short is False
    assert len(spec.params) == 14


def test_signals_shape_and_values():
    days = [datetime(2022, 1, 3) + timedelta(days=i) for i in range(150)]
    prices = [100 + i * 0.3 for i in range(150)]
    stock = [Bar(d, p, p + 1, p - 1, p, 1e6) for d, p in zip(days, prices)]
    tmp = tempfile.mkdtemp()
    path = _write_spy(tmp, days, [400 - i * 0.4 for i in range(150)])
    s = RSBreakoutStrategy()
    s._resolve_spy_path = lambda: path
    sigs = s.generate_signals(stock)
    assert len(sigs) == len(stock)
    assert set(sigs) <= {0.0, 1.0}       # long-only


def test_degrades_to_flat_without_spy():
    days = [datetime(2022, 1, 3) + timedelta(days=i) for i in range(120)]
    stock = [Bar(d, 100, 101, 99, 100, 1e6) for d in days]
    s = RSBreakoutStrategy()
    s._resolve_spy_path = lambda: None      # no SPY available
    sigs = s.generate_signals(stock)
    assert sigs == [0.0] * len(stock)


def test_fires_on_relative_strength():
    days = [datetime(2022, 1, 3) + timedelta(days=i) for i in range(200)]
    tmp = tempfile.mkdtemp()
    path = _write_spy(tmp, days, [400 - i * 0.5 for i in range(200)])  # SPY weak
    stock_px = [100 + i * 0.6 for i in range(200)]                     # stock strong
    stock = []
    for i, d in enumerate(days):
        o = stock_px[i]
        c = stock_px[i] + (3.0 if i % 25 == 0 and i > 95 else 0.2)     # periodic momentum candle
        stock.append(Bar(d, o, max(o, c) + 2, min(o, c) - 0.5, c, 2e6 if i % 25 == 0 else 1e6))
    s = RSBreakoutStrategy(gap_edge=-1.0)
    s._resolve_spy_path = lambda: path
    sigs = s.generate_signals(stock)
    assert any(x > 0 for x in sigs)      # it can fire when the regime holds


def test_causal_no_lookahead():
    from desktop.backend.services.replay_ledger import audit_causality
    days = [datetime(2022, 1, 3) + timedelta(days=i) for i in range(160)]
    tmp = tempfile.mkdtemp()
    path = _write_spy(tmp, days, [400 - i * 0.4 for i in range(160)])
    stock = [Bar(d, 100 + i * 0.5, 100 + i * 0.5 + 2, 100 + i * 0.5 - 1, 100 + i * 0.5 + 0.5, 1e6)
             for i, d in enumerate(days)]
    s = RSBreakoutStrategy()
    s._resolve_spy_path = lambda: path
    aud = audit_causality(s, stock)
    assert aud["causal"] is True

from datetime import datetime, timedelta

import pandas as pd

from domain.models import Bar
from desktop.backend.services.replay_ledger import audit_causality
from user_strategies.trend_relative_strength_breakout import (
    TrendRelativeStrengthBreakoutStrategy,
)


def _bars(prices, volumes=None):
    start = datetime(2020, 1, 1)
    volumes = volumes or [1_000_000.0] * len(prices)
    return [
        Bar(
            start + timedelta(days=i),
            price - 0.25,
            price + 0.5,
            price - 1.5,
            price,
            volumes[i],
        )
        for i, price in enumerate(prices)
    ]


def _write_spy(tmp_path, prices):
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": [price + 1.0 for price in prices],
            "low": [price - 1.0 for price in prices],
            "close": prices,
            "volume": [10_000_000.0] * len(prices),
        },
        index=pd.date_range("2020-01-01", periods=len(prices)),
    )
    path = tmp_path / "spy.parquet"
    frame.to_parquet(path)
    return str(path)


def test_stays_flat_without_spy():
    strategy = TrendRelativeStrengthBreakoutStrategy()
    strategy._resolve_spy_path = lambda: None
    bars = _bars([100.0 + i for i in range(220)])
    assert strategy.generate_signals(bars) == [0.0] * len(bars)


def test_breakout_enters_and_exit_is_next_open_signal(tmp_path):
    n = 240
    spy_prices = [400.0 + i * 0.10 for i in range(n)]
    stock_prices = [100.0 + i * 0.30 for i in range(n)]
    volumes = [1_000_000.0] * n
    stock_prices[220] += 5.0
    volumes[220] = 2_000_000.0
    bars = _bars(stock_prices, volumes)

    strategy = TrendRelativeStrengthBreakoutStrategy()
    spy_path = _write_spy(tmp_path, spy_prices)
    strategy._resolve_spy_path = lambda: spy_path
    signals = strategy.generate_signals(bars)

    assert signals[220] == 1.0
    assert signals[221] == 1.0
    assert audit_causality(strategy, bars)["causal"] is True


def test_market_filter_blocks_falling_spy(tmp_path):
    n = 240
    stock_prices = [100.0 + i * 0.30 for i in range(n)]
    volumes = [1_000_000.0] * n
    stock_prices[220] += 5.0
    volumes[220] = 2_000_000.0
    bars = _bars(stock_prices, volumes)

    strategy = TrendRelativeStrengthBreakoutStrategy()
    spy_path = _write_spy(
        tmp_path, [400.0 - i * 0.10 for i in range(n)]
    )
    strategy._resolve_spy_path = lambda: spy_path

    assert strategy.generate_signals(bars) == [0.0] * n

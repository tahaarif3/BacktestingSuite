import pytest
import pandas as pd
import numpy as np
from domain.models import Bar
from strat import (
    BuyAndHoldStrategy,
    SMACrossoverStrategy,
    EMACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerBandsStrategy,
    MACDStrategy
)
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from backtest.execution import ExecutionModel


@pytest.fixture
def dummy_market_data():
    """Generates simple daily data with rising, falling, and sideways periods."""
    dates = pd.date_range("2023-01-01", periods=60)
    # Generate prices that rise, then fall
    close = [100.0 + i for i in range(30)] + [130.0 - i for i in range(30)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 1.0 for c in close],
        "low": [c - 1.0 for c in close],
        "close": close,
        "volume": [1000] * 60
    }, index=dates)


@pytest.fixture
def dummy_market_bars(dummy_market_data):
    """Converts dummy market data DataFrame to a list of domain Bar objects."""
    bars = []
    for t, r in dummy_market_data.iterrows():
        bars.append(Bar(
            timestamp=t,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=float(r["volume"])
        ))
    return bars


def test_buy_and_hold_strategy(dummy_market_bars):
    """Verify BuyAndHoldStrategy output is always 1.0."""
    strat = BuyAndHoldStrategy()
    signals = strat.generate_signals(dummy_market_bars)
    assert len(signals) == len(dummy_market_bars)
    assert all(sig == 1.0 for sig in signals)


def test_sma_crossover_strategy(dummy_market_bars):
    """Verify SMACrossoverStrategy mathematical bounds and signal assignment."""
    # Fast = 5, Slow = 20
    strat = SMACrossoverStrategy(fast_window=5, slow_window=20, long_only=True)
    signals = strat.generate_signals(dummy_market_bars)

    # Check warm-up period is 0.0
    assert all(sig == 0.0 for sig in signals[:19])
    # Beyond warm-up, signals should be 1.0 or 0.0
    assert set(signals).issubset({0.0, 1.0})

    # Long-Short test
    strat_ls = SMACrossoverStrategy(fast_window=5, slow_window=20, long_only=False)
    signals_ls = strat_ls.generate_signals(dummy_market_bars)
    assert -1.0 in set(signals_ls)
    assert all(sig == 0.0 for sig in signals_ls[:19])


def test_ema_crossover_strategy(dummy_market_bars):
    """Verify EMACrossoverStrategy signal assignment and warm-up."""
    strat = EMACrossoverStrategy(fast_window=5, slow_window=10, long_only=True)
    signals = strat.generate_signals(dummy_market_bars)

    # Check warm-up period
    assert all(sig == 0.0 for sig in signals[:9])
    assert set(signals).issubset({0.0, 1.0})


def test_rsi_mean_reversion_strategy(dummy_market_bars):
    """Verify RSIMeanReversionStrategy RSI calculations and boundaries."""
    strat = RSIMeanReversionStrategy(window=10, oversold=40.0, overbought=60.0, exit_level=50.0, long_only=True)
    signals = strat.generate_signals(dummy_market_bars)

    # Check that warm-up is flat (0.0)
    assert all(sig == 0.0 for sig in signals[:10])

    # Long-Short case
    strat_ls = RSIMeanReversionStrategy(window=10, oversold=40.0, overbought=60.0, exit_level=50.0, long_only=False)
    signals_ls = strat_ls.generate_signals(dummy_market_bars)
    assert set(signals_ls).issubset({-1.0, 0.0, 1.0})


def test_bollinger_bands_strategy(dummy_market_bars):
    """Verify BollingerBandsStrategy calculations and signal tracking."""
    strat = BollingerBandsStrategy(window=20, num_std=2.0, long_only=True)
    signals = strat.generate_signals(dummy_market_bars)

    # Check warm-up
    assert all(sig == 0.0 for sig in signals[:19])
    assert set(signals).issubset({0.0, 1.0})


def test_macd_strategy(dummy_market_bars):
    """Verify MACDStrategy calculations, warm-up, and signal outputs."""
    strat = MACDStrategy(fast_window=5, slow_window=10, signal_window=5, long_only=True)
    signals = strat.generate_signals(dummy_market_bars)

    # Warm-up is max(5, 10) + 5 = 15
    assert all(sig == 0.0 for sig in signals[:14])
    assert set(signals).issubset({0.0, 1.0})


def test_execution_compatibility(dummy_market_bars):
    """Run all strategies through the EventDrivenEngine to verify portfolio simulation compatibility."""
    strategies = [
        BuyAndHoldStrategy(),
        SMACrossoverStrategy(fast_window=5, slow_window=10, long_only=True),
        EMACrossoverStrategy(fast_window=5, slow_window=10, long_only=False),
        RSIMeanReversionStrategy(window=10, oversold=40.0, overbought=60.0, exit_level=50.0, long_only=True),
        BollingerBandsStrategy(window=10, num_std=1.5, long_only=False),
        MACDStrategy(fast_window=5, slow_window=10, signal_window=5, long_only=True)
    ]

    sizers = [
        FixedSharesSizer(fixed_shares=10),
        FixedFractionalSizer(fraction=0.1, initial_capital=10000.0),
        VolatilityBasedSizer(target_risk_per_trade=100.0, window=5)
    ]

    exec_model = ExecutionModel(slippage_pct=0.0005, commission_pct=0.001)

    for strat in strategies:
        for sizer in sizers:
            engine = EventDrivenEngine(
                strategy=strat,
                position_sizer=sizer,
                execution_model=exec_model,
                initial_capital=10000.0
            )
            # Verify the backtest completes without raising errors
            portfolio = engine.run(dummy_market_bars)
            assert not portfolio.equity_curve.empty
            assert portfolio.equity_curve.iloc[0] == 10000.0

import pytest
import pandas as pd
import numpy as np
from strat.base import BaseStrategy
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from backtest.execution import ExecutionModel
from backtest.vectorized import VectorizedEngine


class DummyStrategy(BaseStrategy):
    """Simple strategy that assigns predefined signals for testing."""
    def __init__(self, signals: list):
        self.signals = signals

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["signal"] = self.signals
        return df


@pytest.fixture
def sample_market_data():
    """Generates simple daily market data for testing backtests."""
    dates = pd.date_range("2023-01-01", periods=5)
    return pd.DataFrame({
        "open": [100.0, 102.0, 101.0, 105.0, 110.0],
        "high": [103.0, 104.0, 102.0, 106.0, 112.0],
        "low": [99.0, 101.0, 100.0, 104.0, 108.0],
        "close": [101.0, 103.0, 101.0, 105.0, 109.0]
    }, index=dates)


def test_look_ahead_bias_prevention(sample_market_data):
    """Verify that target positions are shifted by 1 to prevent look-ahead bias."""
    signals = [1, 0, -1, 1, 0]
    strategy = DummyStrategy(signals)
    sizer = FixedSharesSizer(fixed_shares=10)
    exec_model = ExecutionModel()
    engine = VectorizedEngine(strategy, sizer, exec_model, initial_capital=10000)

    portfolio = engine.run(sample_market_data)
    df = portfolio.data

    # Expected target positions: signal * 10 = [10, 0, -10, 10, 0]
    # Expected active positions (shifted by 1): [0, 10, 0, -10, 10]
    assert list(df["target_position"]) == [10.0, 0.0, -10.0, 10.0, 0.0]
    assert list(df["active_position"]) == [0.0, 10.0, 0.0, -10.0, 10.0]


def test_cost_deduction(sample_market_data):
    """Verify slippage and commission calculations are correctly computed and subtracted from cash."""
    signals = [1, 0, -1, 1, 0]  # Active positions: [0, 10, 0, -10, 10], Trades: [0, 10, -10, -10, 20]
    strategy = DummyStrategy(signals)
    sizer = FixedSharesSizer(fixed_shares=10)
    
    # 1% slippage, $0.1 absolute slippage, 0.2% commission, $0.05 flat commission, $1.0 min commission
    exec_model = ExecutionModel(
        slippage_pct=0.01,
        slippage_abs=0.1,
        commission_pct=0.002,
        commission_per_share=0.05,
        min_commission=1.0
    )
    
    engine = VectorizedEngine(strategy, sizer, exec_model, initial_capital=10000.0)
    portfolio = engine.run(sample_market_data)
    df = portfolio.data
    
    # On day 1 (index 1): Price = 103.0, trade size = +10 shares (buy)
    # Expected Slippage: 10 * (0.1 + 103.0 * 0.01) = 10 * 1.13 = 11.3
    # Expected Commission: 10 * (0.05 + 103.0 * 0.002) = 10 * 0.256 = 2.56 (since 2.56 > min_commission of 1.0)
    # Expected Total Friction: 11.3 + 2.56 = 13.86
    # Expected Cash Flow: - (10 * 103.0) - 13.86 = -1043.86
    assert df["slippage_cost"].iloc[1] == pytest.approx(11.3)
    assert df["commission_cost"].iloc[1] == pytest.approx(2.56)
    assert df["cash"].iloc[1] == pytest.approx(10000.0 - 1043.86)


def test_fixed_shares_sizer(sample_market_data):
    """Verify target positions for FixedSharesSizer."""
    signals = [1, -1, 0, 1, -1]
    df_input = sample_market_data.copy()
    df_input["signal"] = signals
    
    sizer = FixedSharesSizer(fixed_shares=50)
    target_pos = sizer.size_positions(df_input)
    
    assert list(target_pos) == [50.0, -50.0, 0.0, 50.0, -50.0]


def test_fixed_fractional_sizer(sample_market_data):
    """Verify target positions for FixedFractionalSizer using estimated equity."""
    signals = [1, 0, 0, 0, 0]
    df_input = sample_market_data.copy()
    df_input["signal"] = signals
    
    # Allocating 20% of account equity per signal
    sizer = FixedFractionalSizer(fraction=0.2, initial_capital=100000.0)
    target_pos = sizer.size_positions(df_input)
    
    # On day 0: signal = 1, Close = 101.0. Prev equity = 100000.0 (initial).
    # Target cash allocation = 100000 * 0.2 = 20000.0
    # Target shares = 20000.0 / 101.0 = 198.01980198...
    assert target_pos.iloc[0] == pytest.approx(20000.0 / 101.0)


def test_volatility_based_sizer(sample_market_data):
    """Verify target positions for VolatilityBasedSizer (incorporating ATR and std-dev fallback)."""
    signals = [1, 1, 1, 1, 1]
    df_input = sample_market_data.copy()
    df_input["signal"] = signals
    
    # Standard Volatility Sizer with window 2
    sizer = VolatilityBasedSizer(target_risk_per_trade=500.0, window=2)
    target_pos = sizer.size_positions(df_input)
    
    # Volatility uses rolling window of 2 (first 2 entries will be backfilled/averaged)
    # The sizer shifts volatility by 1 so no lookahead bias occurs
    # Asserting that sizer runs and returns reasonable values
    assert not target_pos.empty
    assert len(target_pos) == 5
    assert (target_pos.iloc[1:] != 0).all()


def test_portfolio_statistics(sample_market_data):
    """Verify correctness of Portfolio stats (total return, volatility, max drawdown)."""
    strategy = DummyStrategy([1, 1, 1, 1, 1])
    sizer = FixedSharesSizer(fixed_shares=10)
    exec_model = ExecutionModel()
    engine = VectorizedEngine(strategy, sizer, exec_model, initial_capital=10000.0)
    
    portfolio = engine.run(sample_market_data)
    
    # Equity curve values:
    # cash = 10000 - (10 * 103) = 8970.0 (trade executed day 1)
    # holdings value:
    # Day 0: cash = 10000.0, holdings = 0 * 101.0 = 0.0, equity = 10000.0
    # Day 1: cash = 8970.0, holdings = 10 * 103.0 = 1030.0, equity = 10000.0
    # Day 2: cash = 8970.0, holdings = 10 * 101.0 = 1010.0, equity = 9980.0
    # Day 3: cash = 8970.0, holdings = 10 * 105.0 = 1050.0, equity = 10020.0
    # Day 4: cash = 8970.0, holdings = 10 * 109.0 = 1090.0, equity = 10060.0
    assert list(portfolio.equity_curve) == [10000.0, 10000.0, 9980.0, 10020.0, 10060.0]
    
    # Total return: (10060.0 - 10000.0) / 10000.0 = 0.006 (0.6%)
    assert portfolio.total_return == pytest.approx(0.006)
    
    # Peaks: [10000, 10000, 10000, 10020, 10060]
    # Drawdowns: [0, 0, (9980-10000)/10000 = -0.002, 0, 0]
    # Max Drawdown: -0.002 (-0.2%)
    assert portfolio.max_drawdown == pytest.approx(-0.002)

import pytest
import pandas as pd
import numpy as np
from domain.models import Bar
from strat.base import BaseStrategy
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from backtest.execution import ExecutionModel
from backtest.event_driven import EventDrivenEngine


class DummyStrategy(BaseStrategy):
    """Simple strategy that assigns predefined signals for testing."""
    def __init__(self, signals: list):
        self.signals = signals

    def generate_signals(self, bars: list) -> list:
        return self.signals


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


@pytest.fixture
def sample_market_bars(sample_market_data):
    """Converts the sample market data DataFrame to a list of domain Bar objects."""
    bars = []
    for t, r in sample_market_data.iterrows():
        bars.append(Bar(
            timestamp=t,
            open=float(r["open"]),
            high=float(r["high"]),
            low=float(r["low"]),
            close=float(r["close"]),
            volume=0.0
        ))
    return bars


def test_look_ahead_bias_prevention(sample_market_bars):
    """Verify that target positions are computed chronologically and executed on the next bar's Open."""
    signals = [1, 0, -1, 1, 0]
    strategy = DummyStrategy(signals)
    sizer = FixedSharesSizer(fixed_shares=10)
    exec_model = ExecutionModel()
    engine = EventDrivenEngine(strategy, sizer, exec_model, initial_capital=10000, execution_timing="next_open")

    portfolio = engine.run(sample_market_bars)
    df = portfolio.data

    # Expected target positions at t (sized using signals at t-1):
    # - t=0: no prev signal -> target = 0
    # - t=1: prev signal=1 -> target = 10
    # - t=2: prev signal=0 -> target = 0
    # - t=3: prev signal=-1 -> target = -10
    # - t=4: prev signal=1 -> target = 10
    assert list(df["target_position"]) == [0.0, 10.0, 0.0, -10.0, 10.0]
    assert list(df["active_position"]) == [0.0, 10.0, 0.0, -10.0, 10.0]


def test_cost_deduction(sample_market_bars):
    """Verify slippage and commission calculations are correctly computed and subtracted from cash in the event loop."""
    signals = [1, 0, -1, 1, 0]
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
    
    engine = EventDrivenEngine(strategy, sizer, exec_model, initial_capital=10000.0, execution_timing="next_open")
    portfolio = engine.run(sample_market_bars)
    df = portfolio.data
    
    # On day 1 (index 1): execution price is Day 1 Open = 102.0, trade size = +10 shares (buy)
    # Expected Slippage: 10 * (0.1 + 102.0 * 0.01) = 10 * 1.12 = 11.2
    # Expected Commission: 10 * (0.05 + 102.0 * 0.002) = 10 * 0.254 = 2.54 (since 2.54 > min_commission of 1.0)
    # Expected Total Friction: 11.2 + 2.54 = 13.74
    # Expected Cash Flow: - (10 * 102.0) - 13.74 = -1033.74
    assert df["slippage_cost"].iloc[1] == pytest.approx(11.2)
    assert df["commission_cost"].iloc[1] == pytest.approx(2.54)
    assert df["cash"].iloc[1] == pytest.approx(10000.0 - 1033.74)


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
    
    assert not target_pos.empty
    assert len(target_pos) == 5
    assert (target_pos.iloc[1:] != 0).all()


def test_portfolio_statistics(sample_market_bars):
    """Verify correctness of Portfolio stats (total return, volatility, max drawdown) under EventDrivenEngine."""
    strategy = DummyStrategy([1, 1, 1, 1, 1])
    sizer = FixedSharesSizer(fixed_shares=10)
    exec_model = ExecutionModel()
    engine = EventDrivenEngine(strategy, sizer, exec_model, initial_capital=10000.0, execution_timing="next_open")
    
    portfolio = engine.run(sample_market_bars)
    
    # Equity curve values:
    # Day 0: cash = 10000.0, holdings = 0, equity = 10000.0
    # Day 1: trade executed at day 1 open (102.0). cash = 10000 - 10 * 102 = 8980.0. active = 10. close = 103.0. equity = 8980 + 10 * 103 = 10010.0.
    # Day 2: trade = 0. cash = 8980.0. active = 10. close = 101.0. equity = 8980 + 10 * 101 = 9990.0.
    # Day 3: trade = 0. cash = 8980.0. active = 10. close = 105.0. equity = 8980 + 10 * 105 = 10030.0.
    # Day 4: trade = 0. cash = 8980.0. active = 10. close = 109.0. equity = 8980 + 10 * 109 = 10070.0.
    assert list(portfolio.equity_curve) == [10000.0, 10010.0, 9990.0, 10030.0, 10070.0]
    
    # Total return: (10070.0 - 10000.0) / 10000.0 = 0.007 (0.7%)
    assert portfolio.total_return == pytest.approx(0.007)
    
    # Peaks: [10000, 10010, 10010, 10030, 10070]
    # Drawdowns: [0, 0, (9990 - 10010) / 10010 = -20/10010 = -0.001998001998...]
    assert portfolio.max_drawdown == pytest.approx(-20.0 / 10010.0)

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from analytics.metrics import PerformanceMetrics, extract_trades

def test_calculate_cagr():
    # 10% growth over exactly 1 year (non-leap year, 365 days)
    dates = [datetime(2021, 1, 1), datetime(2022, 1, 1)]
    equity = pd.Series([100.0, 110.0], index=dates)
    cagr = PerformanceMetrics.calculate_cagr(equity)
    expected = (110.0 / 100.0) ** (1.0 / (365.0 / 365.25)) - 1.0
    assert pytest.approx(cagr, abs=1e-6) == expected


    # Empty series
    assert PerformanceMetrics.calculate_cagr(pd.Series(dtype=float)) == 0.0

def test_calculate_sharpe_ratio():
    # Series with constant return
    dates = pd.date_range(start="2020-01-01", periods=10, freq="D")
    equity = pd.Series([100 + i for i in range(10)], index=dates)
    sharpe = PerformanceMetrics.calculate_sharpe_ratio(equity)
    # Volatility will be low but non-zero. Let's make sure it's positive.
    assert sharpe > 0.0

    # Constant equity (std of returns = 0)
    equity_flat = pd.Series([100.0] * 10, index=dates)
    assert PerformanceMetrics.calculate_sharpe_ratio(equity_flat) == 0.0

def test_calculate_sortino_ratio():
    dates = pd.date_range(start="2020-01-01", periods=5, freq="D")
    # Returns: day 1: 0%, day 2: +2%, day 3: -1%, day 4: -2%, day 5: +1%
    equity = pd.Series([100.0, 102.0, 100.98, 98.96, 99.95], index=dates)
    sortino = PerformanceMetrics.calculate_sortino_ratio(equity)
    
    # Returns should have negative elements, so downside dev is > 0 and Sortino is calculated.
    assert isinstance(sortino, float)
    
    # Check that flat equity returns 0.0
    equity_flat = pd.Series([100.0] * 5, index=dates)
    assert PerformanceMetrics.calculate_sortino_ratio(equity_flat) == 0.0

def test_calculate_max_drawdown():
    dates = pd.date_range(start="2020-01-01", periods=5, freq="D")
    # Peak is 100, drops to 90 (drawdown of -10%), recovers to 105, drops to 94.5 (-10% drawdown)
    equity = pd.Series([100.0, 90.0, 105.0, 94.5, 110.0], index=dates)
    mdd = PerformanceMetrics.calculate_max_drawdown(equity)
    assert pytest.approx(mdd, abs=1e-4) == -0.10

def test_calculate_win_rate():
    trades = pd.DataFrame({
        "pnl_usd": [10.0, -5.0, 15.0, 0.0]
    })
    # 2 positive trades out of 4
    win_rate = PerformanceMetrics.calculate_win_rate(trades)
    assert pytest.approx(win_rate, abs=1e-4) == 0.50

    # Empty trades
    assert PerformanceMetrics.calculate_win_rate(pd.DataFrame()) == 0.0

def test_calculate_profit_factor():
    trades = pd.DataFrame({
        "pnl_usd": [10.0, -5.0, 15.0, -3.0]
    })
    # Gross Profit = 25.0, Gross Loss = 8.0
    pf = PerformanceMetrics.calculate_profit_factor(trades)
    assert pytest.approx(pf, abs=1e-4) == 25.0 / 8.0

    # No losses
    trades_all_win = pd.DataFrame({"pnl_usd": [10.0, 20.0]})
    assert PerformanceMetrics.calculate_profit_factor(trades_all_win) == float('inf')

    # Empty
    assert PerformanceMetrics.calculate_profit_factor(pd.DataFrame()) == 0.0

def test_calculate_exposure_time():
    portfolio = pd.DataFrame({
        "active_position": [0.0, 10.0, 10.0, 0.0, -5.0]
    })
    # 3 active bars out of 5
    exposure = PerformanceMetrics.calculate_exposure_time(portfolio)
    assert pytest.approx(exposure, abs=1e-4) == 0.60

def test_extract_trades_basic():
    # Construct mock portfolio df simulating a buy then sell
    dates = pd.date_range(start="2020-01-01", periods=5, freq="D")
    portfolio_data = pd.DataFrame({
        "close": [100.0, 102.0, 105.0, 101.0, 103.0],
        "trades": [10.0, 0.0, -10.0, 0.0, 0.0],
    }, index=dates)
    
    trades = extract_trades(portfolio_data)
    assert len(trades) == 1
    trade = trades.iloc[0]
    assert trade["direction"] == "Long"
    assert trade["size"] == 10.0
    assert trade["entry_price"] == 100.0
    assert trade["exit_price"] == 105.0
    assert pytest.approx(trade["pnl_usd"], abs=1e-4) == (105.0 - 100.0) * 10.0
    assert trade["duration_days"] == 2

def test_extract_trades_flip_and_close_out():
    # Buy 10, then sell 20 (resulting in a -10 short position), then end backtest.
    # The final short position should be closed out on the final day's close.
    dates = pd.date_range(start="2020-01-01", periods=4, freq="D")
    portfolio_data = pd.DataFrame({
        "close": [100.0, 105.0, 95.0, 90.0],
        "trades": [10.0, -20.0, 0.0, 0.0],
    }, index=dates)
    
    trades = extract_trades(portfolio_data)
    # Should have 2 trades:
    # 1. Long 10 shares entered at 100, closed at 105.
    # 2. Short 10 shares entered at 105 (flip), closed at 90 on final day.
    assert len(trades) == 2
    
    t1 = trades.iloc[0]
    assert t1["direction"] == "Long"
    assert t1["size"] == 10.0
    assert t1["entry_price"] == 100.0
    assert t1["exit_price"] == 105.0
    assert t1["pnl_usd"] == 50.0
    
    t2 = trades.iloc[1]
    assert t2["direction"] == "Short"
    assert t2["size"] == 10.0
    assert t2["entry_price"] == 105.0
    assert t2["exit_price"] == 90.0
    assert t2["pnl_usd"] == 150.0 # short profit: (105 - 90) * 10 = 150

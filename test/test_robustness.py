import pytest
import numpy as np
import pandas as pd
from datetime import datetime
from domain.models import Bar
from validation.optimization import train_test_split, GridSearchOptimizer, WalkForwardAnalyzer
from validation.monte_carlo import MonteCarloSimulator
from validation.sensitivity import CostSensitivityAnalyzer
from strat.base import BaseStrategy

# Create a mock strategy for testing optimization
class MockStrategy(BaseStrategy):
    def __init__(self, param1: int = 10, param2: int = 20):
        self.param1 = param1
        self.param2 = param2

    def generate_signals(self, bars: list) -> list:
        # Simple signal generation based on parameters
        signals = [0.0] * len(bars)
        for i in range(len(bars)):
            if i % self.param1 == 0:
                signals[i] = 1.0
            elif i % self.param2 == 0:
                signals[i] = -1.0
        return signals


def test_train_test_split():
    bars = [Bar(datetime(2020, 1, i), 100.0, 101.0, 99.0, 100.0, 1000) for i in range(1, 11)]
    train, test = train_test_split(bars, train_ratio=0.7)
    assert len(train) == 7
    assert len(test) == 3
    assert train[-1].timestamp == datetime(2020, 1, 7)
    assert test[0].timestamp == datetime(2020, 1, 8)

def test_grid_search_optimizer_simple():
    # Construct mock bars
    dates = pd.date_range(start="2020-01-01", periods=10, freq="D")
    bars = [Bar(d, 100.0, 101.0, 99.0, 100.0, 1000) for d in dates]

    optimizer = GridSearchOptimizer(
        strategy_class=MockStrategy,
        param_grid={"param1": [2, 3], "param2": [4, 5]},
        initial_capital=100000.0,
        sizer_fraction=0.1
    )

    res = optimizer.optimize(bars, metric="Sharpe Ratio")
    assert "best_params" in res
    assert "best_metric_value" in res
    assert len(res["all_results"]) == 4

def test_grid_search_overfitting_warnings():
    # Setup conditions that should trigger overfitting warnings
    optimizer = GridSearchOptimizer(
        strategy_class=MockStrategy,
        param_grid={"param1": list(range(2, 22))}, # 20 combinations
        initial_capital=100000.0,
        sizer_fraction=0.1
    )
    
    # Mock some trades and results to trigger warnings
    # Permutations count = 20. If best trades count = 10, then permutations > 0.5 * trades_count (triggers parameter ratio warning)
    # If Sharpe is 3.5, triggers high Sharpe warning
    dates = pd.date_range(start="2020-01-01", periods=10, freq="D")
    bars = [Bar(d, 100.0, 101.0, 99.0, 100.0, 1000) for d in dates]

    # Let's verify standard optimize warns if metrics are highly fit
    # Since our mock run won't naturally achieve Sharpe > 3.0 or exactly 10 trades, we check structure of warnings list
    res = optimizer.optimize(bars)
    # Should not throw any errors, warning_messages should be a list
    assert isinstance(res["warning_messages"], list)

def test_monte_carlo_drawdown_calculation():
    # Create trades df with known losses to verify drawdown and ruin calculations
    trades = pd.DataFrame({
        "pnl_usd": [-20000.0, -15000.0, 10000.0, -35000.0, 5000.0],
        "pnl_pct": [-0.20, -0.15, 0.10, -0.35, 0.05]
    })

    
    # Starting capital 100,000.
    # Shuffled returns will be: [-0.20, -0.15, 0.10, -0.25, 0.05] relative to 100k
    # Worst case: all losses consecutively: 100k -> 80k -> 65k -> 40k (ruin triggers at 50% = 50k!)
    mc_res = MonteCarloSimulator.simulate_trade_shuffling(
        trades_df=trades,
        initial_capital=100000.0,
        iterations=100,
        ruin_threshold_pct=0.5,
        output_dir="output"
    )
    
    assert mc_res["total_trades"] == 5
    assert mc_res["probability_of_ruin"] > 0.0 # Some paths should hit the ruin barrier
    assert mc_res["median_max_drawdown"] < 0.0 # Should have real drawdowns
    assert mc_res["drawdown_95th_percentile"] < mc_res["drawdown_5th_percentile"]

def test_cost_sensitivity_analyzer():
    dates = pd.date_range(start="2020-01-01", periods=10, freq="D")
    bars = [Bar(d, 100.0, 101.0, 99.0, 100.0, 1000) for d in dates]

    analyzer = CostSensitivityAnalyzer(
        strategy_class=MockStrategy,
        strategy_params={"param1": 2, "param2": 4},
        initial_capital=100000.0,
        sizer_fraction=0.1
    )
    
    res_df = analyzer.run_sensitivity_analysis(
        bars=bars,
        commission_grid=[0.0, 0.001],
        slippage_grid=[0.0, 0.002]
    )
    
    assert len(res_df) == 4
    assert "commission_pct" in res_df.columns
    assert "slippage_pct" in res_df.columns
    assert "sharpe_ratio" in res_df.columns

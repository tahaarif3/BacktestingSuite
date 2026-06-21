import os
import sys
import pandas as pd
import numpy as np

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloader import DataLoader
from strat.sma_crossover import SMACrossoverStrategy
from presentation.presenter import PortfolioPresenter
from analytics.metrics import extract_trades
from validation.optimization import train_test_split, GridSearchOptimizer, WalkForwardAnalyzer
from validation.monte_carlo import MonteCarloSimulator
from validation.sensitivity import CostSensitivityAnalyzer


def main():
    print("=== SPY Backtesting Robustness & Validation (Phase 5) ===")

    # 1. Load data
    data_path = os.path.join("data", "spy_daily_yfinance.parquet")
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found. Please run scratch/sample_run.py first.")
        return
        
    loader = DataLoader()
    bars = loader.get_bars(data_path)
    print(f"Loaded {len(bars)} bars of SPY daily data.")

    # ----------------------------------------------------
    # Step 2: Train-Test Split & Out-of-Sample Grid Search Validation
    # ----------------------------------------------------
    print("\n--- 2. Train-Test Split (70/30) & Grid Search ---")
    train_bars, test_bars = train_test_split(bars, train_ratio=0.7)
    print(f"In-Sample (Training) Period: {len(train_bars)} bars")
    print(f"Out-of-Sample (Testing) Period: {len(test_bars)} bars")

    # Define Parameter Grid
    param_grid = {
        "fast_window": [5, 10, 15, 20],
        "slow_window": [30, 50, 70, 90]
    }

    # Run Grid Search Optimizer on In-Sample data
    optimizer = GridSearchOptimizer(
        strategy_class=SMACrossoverStrategy,
        param_grid=param_grid,
        initial_capital=100000.0,
        sizer_fraction=0.5
    )
    print("Running In-Sample Parameter Optimization...")
    opt_res = optimizer.optimize(train_bars, metric="Sharpe Ratio")
    
    best_params = opt_res["best_params"]
    best_is_sharpe = opt_res["best_metric_value"]
    print(f"Best In-Sample Parameters: {best_params}")
    print(f"Best In-Sample Sharpe Ratio: {best_is_sharpe:.4f}")
    
    if opt_res["overfitting_warning"]:
        print("\n[WARNING] In-Sample Overfitting Flags Triggered:")
        for msg in opt_res["warning_messages"]:
            print(f"  - {msg}")

    # Evaluate best parameters on Out-of-Sample (OOS) testing data
    print("\nEvaluating Best Parameters on Out-of-Sample (OOS) Testing...")
    optimizer_oos = GridSearchOptimizer(
        strategy_class=SMACrossoverStrategy,
        param_grid={k: [v] for k, v in best_params.items()},
        initial_capital=100000.0,
        sizer_fraction=0.5
    )
    oos_res = optimizer_oos.optimize(test_bars, metric="Sharpe Ratio")
    oos_sharpe = oos_res["best_metric_value"]
    oos_summary = oos_res["all_results"][0]["metrics"]
    
    print(f"OOS Sharpe Ratio: {oos_sharpe:.4f}")
    print(f"OOS CAGR: {oos_summary.get('CAGR', 0.0)*100:.2f}%")
    print(f"OOS Max Drawdown: {oos_summary.get('Max Drawdown', 0.0)*100:.2f}%")
    
    decay_ratio = oos_sharpe / best_is_sharpe if best_is_sharpe > 0 else 0.0
    print(f"Out-of-Sample Decay Ratio (OOS Sharpe / IS Sharpe): {decay_ratio:.2f}")
    if decay_ratio < 0.4:
        print("[WARNING] Severe Out-of-Sample performance decay detected.")

    # ----------------------------------------------------
    # Step 3: Walk-Forward Analysis (WFA)
    # ----------------------------------------------------
    print("\n--- 3. Walk-Forward Analysis (Rolling Window) ---")
    wfa = WalkForwardAnalyzer(
        strategy_class=SMACrossoverStrategy,
        param_grid=param_grid,
        train_span_bars=140,
        test_span_bars=40,
        initial_capital=100000.0,
        sizer_fraction=0.5
    )
    print("Running rolling Walk-Forward Analysis...")
    wfa_res = wfa.run_walk_forward(bars)

    print("\nWalk-Forward Windows Report:")
    print(f"{'Win':<4} | {'Train Range':<24} | {'Test Range':<24} | {'Best Params':<28} | {'IS Sharpe':<9} | {'OOS Sharpe':<10}")
    print("-" * 115)
    for win in wfa_res["windows_report"]:
        params_str = str(win["best_params"])
        print(
            f"{win['window']:<4} | "
            f"{win['train_dates']:<24} | "
            f"{win['test_dates']:<24} | "
            f"{params_str:<28} | "
            f"{win['train_sharpe']:<9.4f} | "
            f"{win['test_sharpe']:<10.4f}"
        )

    wfe = wfa_res["wfe"]
    print(f"\nWalk-Forward Efficiency (WFE): {wfe:.2f}")
    print(f"Average In-Sample Sharpe: {wfa_res['avg_is_sharpe']:.4f}")
    print(f"Walk-Forward Out-of-Sample Sharpe: {wfa_res['oos_summary'].get('Sharpe Ratio', 0.0):.4f}")
    
    if wfa_res["overfitting_warning"]:
        print(f"[WARNING] WFA Overfitting Check: {wfa_res['warning_message']}")
    else:
        print("[INFO] Walk-Forward Efficiency (WFE >= 0.40) is within acceptable range.")

    # ----------------------------------------------------
    # Step 4: Monte Carlo Simulations (Trade Sequence Shuffling)
    # ----------------------------------------------------
    print("\n--- 4. Monte Carlo Simulations on Trade Sequence ---")
    # Retrieve trades from the full OOS walk-forward run or In-Sample best run
    # Let's run a backtest with best parameters on the full dataset
    from backtest.event_driven import EventDrivenEngine
    from backtest.position_sizing import FixedFractionalSizer
    from backtest.execution import ExecutionModel
    
    full_strat = SMACrossoverStrategy(**best_params)
    full_sizer = FixedFractionalSizer(fraction=0.5, initial_capital=100000.0)
    full_exec = ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)
    full_engine = EventDrivenEngine(full_strat, full_sizer, full_exec, 100000.0)
    full_portfolio = full_engine.run(bars)
    full_trades = extract_trades(full_portfolio.data)
    
    print(f"Running Monte Carlo trade shuffling on {len(full_trades)} trades...")
    mc_res = MonteCarloSimulator.simulate_trade_shuffling(
        trades_df=full_trades,
        initial_capital=100000.0,
        iterations=1000,
        ruin_threshold_pct=0.5,
        output_dir="output"
    )
    
    print(f"Probability of Ruin (Equity < $50,000): {mc_res['probability_of_ruin']*100:.2f}%")
    print(f"Median Max Drawdown: {mc_res['median_max_drawdown']*100:.2f}%")
    print(f"95th Percentile Drawdown (VaR): {mc_res['drawdown_95th_percentile']*100:.2f}%")
    print(f"Median Final Equity: ${mc_res['median_final_equity']:,.2f}")
    print(f"5th Percentile Ending Equity: ${mc_res['final_equity_5th_percentile']:,.2f}")
    print(f"95th Percentile Ending Equity: ${mc_res['final_equity_95th_percentile']:,.2f}")
    print(f"Monte Carlo paths plot saved to: {mc_res['plot_path']}")

    # ----------------------------------------------------
    # Step 5: Transaction Cost Sensitivity Analysis
    # ----------------------------------------------------
    print("\n--- 5. Transaction Cost Sensitivity Analysis ---")
    cost_analyzer = CostSensitivityAnalyzer(
        strategy_class=SMACrossoverStrategy,
        strategy_params=best_params,
        initial_capital=100000.0,
        sizer_fraction=0.5
    )
    
    commission_grid = [0.0, 0.0002, 0.0005, 0.0010]  # 0, 2 bps, 5 bps, 10 bps
    slippage_grid = [0.0, 0.0001, 0.0003, 0.0005]    # 0, 1 bps, 3 bps, 5 bps
    
    print("Evaluating costs matrix...")
    sensitivity_df = cost_analyzer.run_sensitivity_analysis(
        bars=bars,
        commission_grid=commission_grid,
        slippage_grid=slippage_grid,
        output_dir="output"
    )

    print("\nSensitivity Analysis Table (Commissions vs. Slippage vs. Sharpe):")
    pivot_table = sensitivity_df.pivot(index="commission_pct", columns="slippage_pct", values="sharpe_ratio")
    # Format indices/columns as percentages for readability
    pivot_table.index = [f"{i * 100:.3f}%" for i in pivot_table.index]
    pivot_table.columns = [f"{c * 100:.3f}%" for c in pivot_table.columns]
    print(pivot_table)
    print("\nCost sensitivity heatmap saved to: output/cost_sensitivity.png")
    
    print("\n=== Phase 5 Robustness Checks Completed ===")


if __name__ == "__main__":
    main()

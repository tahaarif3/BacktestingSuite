import os
import sys
import argparse
import pandas as pd
from datetime import datetime

# Add directory to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data.dataloader import DataLoader
from domain.models import Bar
from backtest.execution import ExecutionModel
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from presentation.presenter import PortfolioPresenter
from analytics.metrics import PerformanceMetrics, extract_trades
from analytics.plots import generate_backtest_report_plots
from analytics.reports import generate_html_report

# Import strategies
from strat.buy_and_hold import BuyAndHoldStrategy
from strat.sma_crossover import SMACrossoverStrategy
from strat.ema_crossover import EMACrossoverStrategy
from strat.rsi_mean_reversion import RSIMeanReversionStrategy
from strat.bollinger_bands import BollingerBandsStrategy
from strat.macd import MACDStrategy
from strat.genetic_programming import GeneticProgrammingStrategy


def parse_args():
    parser = argparse.ArgumentParser(
        description="SPY Event-Driven Backtesting Suite Command-Line Interface"
    )
    
    # Strategy settings
    parser.add_argument(
        "--strategy",
        choices=["buy_and_hold", "sma", "ema", "rsi", "bb", "macd", "gp"],
        default="sma",
        help="Trading strategy to execute (default: sma)"
    )
    
    # General strategy settings
    parser.add_argument(
        "--short",
        action="store_true",
        help="Allow shorting (-1.0 signal instead of 0.0 flat)"
    )

    # Strategy-specific params
    parser.add_argument("--fast-window", type=int, default=10, help="Fast window for SMA/EMA crossover (default: 10)")
    parser.add_argument("--slow-window", type=int, default=50, help="Slow window for SMA/EMA crossover (default: 50)")
    parser.add_argument("--rsi-window", type=int, default=14, help="RSI window (default: 14)")
    parser.add_argument("--rsi-oversold", type=int, default=30, help="RSI oversold threshold (default: 30)")
    parser.add_argument("--rsi-overbought", type=int, default=70, help="RSI overbought threshold (default: 70)")
    parser.add_argument("--rsi-exit", type=int, default=50, help="RSI exit signal level (default: 50)")
    parser.add_argument("--bb-window", type=int, default=20, help="Bollinger Bands window (default: 20)")
    parser.add_argument("--bb-std", type=float, default=2.0, help="Bollinger Bands standard deviation multiplier (default: 2.0)")
    parser.add_argument("--macd-fast", type=int, default=12, help="MACD Fast EMA window (default: 12)")
    parser.add_argument("--macd-slow", type=int, default=26, help="MACD Slow EMA window (default: 26)")
    parser.add_argument("--macd-signal", type=int, default=9, help="MACD Signal window (default: 9)")
    parser.add_argument("--gp-json", type=str, default="champion_gp.json", help="Path to genetic programming strategy JSON file")


    # Sizing settings
    parser.add_argument(
        "--sizer",
        choices=["fixed_shares", "fixed_fractional", "volatility"],
        default="fixed_fractional",
        help="Position sizing logic (default: fixed_fractional)"
    )
    parser.add_argument(
        "--sizer-val",
        type=float,
        default=0.5,
        help="Sizer value (fraction for fractional [e.g. 0.5], shares count for fixed [e.g. 100], risk per trade for vol [e.g. 500])"
    )

    # Backtesting engine settings
    parser.add_argument("--capital", type=float, default=100000.0, help="Initial portfolio cash (default: 100000.0)")
    parser.add_argument("--slippage-pct", type=float, default=0.0002, help="Slippage percentage rate (default: 0.0002, 2 bps)")
    parser.add_argument("--commission-pct", type=float, default=0.0005, help="Commission percentage rate (default: 0.0005, 5 bps)")
    parser.add_argument("--commission-per-share", type=float, default=0.0, help="Commission per traded share in USD (default: 0.0)")
    parser.add_argument("--min-trade-shares", type=float, default=1e-8, help="Minimum trade size in shares (default: 1e-8)")
    parser.add_argument(
        "--timing",
        choices=["next_open", "next_close"],
        default="next_open",
        help="Order execution timing (default: next_open)"
    )

    # Output options
    parser.add_argument(
        "--report",
        action="store_true",
        help="Generate an automated self-contained HTML report at output/report.html"
    )
    parser.add_argument(
        "--robustness",
        action="store_true",
        help="Execute Walk-Forward Analysis, Monte Carlo Shuffling, and Cost Sensitivity checks"
    )
    parser.add_argument(
        "--data-path",
        type=str,
        default=os.path.join("data", "spy_daily_yfinance.parquet"),
        help="Path to historical price Parquet file"
    )

    return parser.parse_args()


def run_robustness_checks(bars, strategy_class, best_params, initial_capital, sizer_fraction, slippage_pct, commission_pct):
    """Orchestrates Phase 5 robustness and validation checks from the CLI."""
    print("\n====================================================")
    print("      RUNNING PHASE 5 ROBUSTNESS & VALIDATION")
    print("====================================================")
    
    from validation.optimization import train_test_split, GridSearchOptimizer, WalkForwardAnalyzer
    from validation.monte_carlo import MonteCarloSimulator
    from validation.sensitivity import CostSensitivityAnalyzer

    # 1. Train-Test Split (70/30)
    print("\n[1/3] Train-Test Split Validation...")
    train_bars, test_bars = train_test_split(bars, train_ratio=0.7)
    optimizer = GridSearchOptimizer(
        strategy_class=strategy_class,
        param_grid={k: [v] for k, v in best_params.items()},
        initial_capital=initial_capital,
        sizer_fraction=sizer_fraction,
        slippage_pct=slippage_pct,
        commission_pct=commission_pct
    )
    is_res = optimizer.optimize(train_bars)
    is_sharpe = is_res["best_metric_value"]
    
    oos_optimizer = GridSearchOptimizer(
        strategy_class=strategy_class,
        param_grid={k: [v] for k, v in best_params.items()},
        initial_capital=initial_capital,
        sizer_fraction=sizer_fraction,
        slippage_pct=slippage_pct,
        commission_pct=commission_pct
    )
    oos_res = oos_optimizer.optimize(test_bars)
    oos_sharpe = oos_res["best_metric_value"]
    decay = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
    
    print(f"  In-Sample (Training) Sharpe  : {is_sharpe:.4f}")
    print(f"  Out-of-Sample (Testing) Sharpe: {oos_sharpe:.4f}")
    print(f"  OOS Performance Decay Ratio   : {decay:.2f}")
    if decay < 0.4:
        print("  [WARNING] Severe Out-of-Sample performance decay detected.")

    # 2. Walk-Forward Analysis (WFA)
    print("\n[2/3] Rolling Walk-Forward Analysis...")
    # Define a default param grid for WFA based on strategy parameters
    param_grids_mapping = {
        BuyAndHoldStrategy: {},
        SMACrossoverStrategy: {"fast_window": [5, 10, 20], "slow_window": [30, 50, 70]},
        EMACrossoverStrategy: {"fast_window": [5, 10, 20], "slow_window": [30, 50, 70]},
        RSIMeanReversionStrategy: {"window": [10, 14, 20], "oversold": [25, 30, 35], "overbought": [65, 70, 75]},
        BollingerBandsStrategy: {"window": [15, 20, 25], "num_std": [1.5, 2.0, 2.5]},
        MACDStrategy: {"fast_period": [10, 12, 15], "slow_period": [22, 26, 30], "signal_period": [7, 9, 11]}
    }
    
    wfa_grid = param_grids_mapping.get(strategy_class, {})
    if wfa_grid:
        wfa = WalkForwardAnalyzer(
            strategy_class=strategy_class,
            param_grid=wfa_grid,
            train_span_bars=140,
            test_span_bars=40,
            initial_capital=initial_capital,
            sizer_fraction=sizer_fraction,
            slippage_pct=slippage_pct,
            commission_pct=commission_pct
        )
        wfa_res = wfa.run_walk_forward(bars)
        print(f"  Walk-Forward Efficiency (WFE) : {wfa_res['wfe']:.2f}")
        print(f"  Average In-Sample Sharpe      : {wfa_res['avg_is_sharpe']:.4f}")
        print(f"  Walk-Forward OOS Sharpe       : {wfa_res['oos_summary'].get('Sharpe Ratio', 0.0):.4f}")
        if wfa_res["overfitting_warning"]:
            print(f"  [WARNING] WFA Overfitting check: {wfa_res['warning_message']}")
    else:
        print("  Skipping Walk-Forward Analysis (no grid parameters defined for Buy & Hold).")

    # 3. Monte Carlo Simulations on Trade Sequence
    print("\n[3/3] Monte Carlo Simulations (Trade Sequence Shuffling)...")
    strat = strategy_class(**best_params)
    sizer = FixedFractionalSizer(fraction=sizer_fraction, initial_capital=initial_capital)
    exec_model = ExecutionModel(slippage_pct=slippage_pct, commission_pct=commission_pct)
    engine = EventDrivenEngine(strat, sizer, exec_model, initial_capital)
    portfolio = engine.run(bars)
    trades_df = extract_trades(portfolio.data)
    
    if len(trades_df) >= 3:
        mc_res = MonteCarloSimulator.simulate_trade_shuffling(
            trades_df=trades_df,
            initial_capital=initial_capital,
            iterations=1000,
            ruin_threshold_pct=0.5,
            output_dir="output"
        )
        print(f"  Probability of Ruin           : {mc_res['probability_of_ruin']*100:.2f}%")
        print(f"  Median Max Drawdown           : {mc_res['median_max_drawdown']*100:.2f}%")
        print(f"  95% Drawdown Value-at-Risk    : {mc_res['drawdown_95th_percentile']*100:.2f}%")
        print(f"  Median Final Equity           : ${mc_res['median_final_equity']:,.2f}")
        print(f"  Monte Carlo paths chart saved : output/monte_carlo_paths.png")
    else:
        print("  Skipping Monte Carlo (requires at least 3 executed trades).")

    # 4. Cost Sensitivity Analysis
    print("\n[4/4] Transaction Cost Sensitivity analysis...")
    cost_analyzer = CostSensitivityAnalyzer(
        strategy_class=strategy_class,
        strategy_params=best_params,
        initial_capital=initial_capital,
        sizer_fraction=sizer_fraction
    )
    comm_grid = [0.0, 0.0002, 0.0005, 0.0010]
    slip_grid = [0.0, 0.0001, 0.0003, 0.0005]
    sensitivity_df = cost_analyzer.run_sensitivity_analysis(
        bars=bars,
        commission_grid=comm_grid,
        slippage_grid=slip_grid,
        output_dir="output"
    )
    print("  Cost sensitivity heatmap saved: output/cost_sensitivity.png")


def main():
    args = parse_args()
    
    print("=== SPY Backtesting Dashboard & CLI ===")
    
    # 1. Load historical data
    if not os.path.exists(args.data_path):
        print(f"Error: Dataset {args.data_path} not found. Run scratch/sample_run.py first to fetch SPY daily data.")
        sys.exit(1)
        
    loader = DataLoader()
    bars = loader.get_bars(args.data_path)
    print(f"Loaded {len(bars)} daily bars from {args.data_path}")

    # 2. Map strategy selection to strategy class and parameters
    strategy_params = {}
    if args.strategy == "buy_and_hold":
        strategy_class = BuyAndHoldStrategy
    elif args.strategy == "sma":
        strategy_class = SMACrossoverStrategy
        strategy_params = {
            "fast_window": args.fast_window,
            "slow_window": args.slow_window,
            "long_only": not args.short
        }
    elif args.strategy == "ema":
        strategy_class = EMACrossoverStrategy
        strategy_params = {
            "fast_window": args.fast_window,
            "slow_window": args.slow_window,
            "long_only": not args.short
        }
    elif args.strategy == "rsi":
        strategy_class = RSIMeanReversionStrategy
        strategy_params = {
            "window": args.rsi_window,
            "oversold": args.rsi_oversold,
            "overbought": args.rsi_overbought,
            "exit_level": args.rsi_exit,
            "long_only": not args.short
        }
    elif args.strategy == "bb":
        strategy_class = BollingerBandsStrategy
        strategy_params = {
            "window": args.bb_window,
            "num_std": args.bb_std,
            "long_only": not args.short
        }
    elif args.strategy == "macd":
        strategy_class = MACDStrategy
        strategy_params = {
            "fast_period": args.macd_fast,
            "slow_period": args.macd_slow,
            "signal_period": args.macd_signal,
            "long_only": not args.short
        }
    elif args.strategy == "gp":
        strategy_class = GeneticProgrammingStrategy
        strategy_params = {
            "json_path": args.gp_json
        }


    # 3. Instantiate position sizer
    if args.sizer == "fixed_shares":
        sizer = FixedSharesSizer(fixed_shares=int(args.sizer_val))
    elif args.sizer == "fixed_fractional":
        sizer = FixedFractionalSizer(fraction=float(args.sizer_val), initial_capital=args.capital)
    elif args.sizer == "volatility":
        sizer = VolatilityBasedSizer(target_risk_per_trade=float(args.sizer_val), window=20)

    # 4. Instantiate execution cost model
    exec_model = ExecutionModel(
        slippage_pct=args.slippage_pct, 
        commission_pct=args.commission_pct,
        commission_per_share=args.commission_per_share
    )

    # 5. Initialize and run Event-Driven engine
    strategy = strategy_class(**strategy_params)
    engine = EventDrivenEngine(
        strategy=strategy,
        position_sizer=sizer,
        execution_model=exec_model,
        initial_capital=args.capital,
        execution_timing=args.timing,
        min_trade_shares=args.min_trade_shares
    )

    print(f"\nRunning backtest with strategy: '{args.strategy}'...")
    portfolio = engine.run(bars)
    
    # 6. Extract Trades & Compile Performance Analytics
    trades_df = extract_trades(portfolio.data, args.timing)

    summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)

    # 7. Print Terminal Performance Outputs
    print(PortfolioPresenter.format_summary(summary))
    print(PortfolioPresenter.format_trade_log(trades_df, limit=10))

    # 8. Report generation (HTML)
    if args.report:
        report_path = os.path.join("output", "report.html")
        print("\nGenerating HTML Report...")
        generate_html_report(
            portfolio_df=portfolio.data,
            trades_df=trades_df,
            strategy_name=args.strategy.upper().replace("_", " "),
            strategy_params=strategy_params,
            output_path=report_path
        )
        print(f"HTML dashboard report successfully saved to: {report_path}")

    # 9. Robustness testing
    if args.robustness:
        # For validation, we use sizer_val as sizer fraction if fixed_fractional, else default to 0.5
        sizer_fraction = args.sizer_val if args.sizer == "fixed_fractional" else 0.5
        run_robustness_checks(
            bars=bars,
            strategy_class=strategy_class,
            best_params=strategy_params,
            initial_capital=args.capital,
            sizer_fraction=sizer_fraction,
            slippage_pct=args.slippage_pct,
            commission_pct=args.commission_pct
        )


if __name__ == "__main__":
    main()

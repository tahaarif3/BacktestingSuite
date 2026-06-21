import os
import sys
import pandas as pd
import numpy as np

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloader import DataLoader
from strat.base import BaseStrategy
from domain.models import Bar
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from backtest.execution import ExecutionModel
from backtest.event_driven import EventDrivenEngine
from presentation.presenter import PortfolioPresenter


class SMACrossoverStrategy(BaseStrategy):
    """
    Simple Moving Average (SMA) Crossover Strategy.
    Generates a Buy signal (1.0) when short_window SMA is above long_window SMA,
    and a Flat/Sell signal (0.0) otherwise.
    Conforms to clean domain boundaries.
    """

    def __init__(self, short_window: int = 5, long_window: int = 20):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, bars: list) -> list:
        # Convert list of Bar objects to a pandas Series to compute moving averages easily
        closes = pd.Series([b.close for b in bars])
        
        # Calculate moving averages
        sma_short = closes.rolling(window=self.short_window).mean()
        sma_long = closes.rolling(window=self.long_window).mean()
        
        # Generate signal: 1.0 if short SMA > long SMA, else 0.0
        signals_arr = np.where(sma_short > sma_long, 1.0, 0.0)
        
        return [float(sig) for sig in signals_arr]


def main():
    print("=== SPY Event-Driven Backtesting Engine Verification ===")
    
    # 1. Load and clean historical SPY daily data using the repository pattern
    data_path = os.path.join("data", "spy_daily_yfinance.parquet")
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found. Please run scratch/sample_run.py first to fetch SPY data.")
        return
        
    loader = DataLoader()
    bars = loader.get_bars(data_path)
    print(f"Loaded {len(bars)} bars of SPY daily data.")

    # 2. Instantiate strategy
    strategy = SMACrossoverStrategy(short_window=10, long_window=50)

    # 3. Instantiate execution model with slippage and commission
    # slippage: 0.02% of price, commission: 0.05% of trade value (5 basis points)
    execution_model = ExecutionModel(
        slippage_pct=0.0002,
        commission_pct=0.0005
    )

    # 4. Instantiate Position Sizer (let's use Fixed Fractional: invest 50% of capital)
    sizer = FixedFractionalSizer(fraction=0.5, initial_capital=100000.0)

    # 5. Initialize and run the engine (using EventDrivenEngine executing at Next Open)
    engine = EventDrivenEngine(
        strategy=strategy,
        position_sizer=sizer,
        execution_model=execution_model,
        initial_capital=100000.0,
        execution_timing="next_open"
    )
    
    print("\nRunning backtest...")
    portfolio = engine.run(bars)
    
    # 6. Extract trades and display advanced performance metrics using the Presentation Layer
    from analytics.metrics import PerformanceMetrics, extract_trades
    from analytics.plots import generate_backtest_report_plots

    trades_df = extract_trades(portfolio.data)
    advanced_summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)
    
    print(PortfolioPresenter.format_summary(advanced_summary))
    print(PortfolioPresenter.format_trade_log(trades_df, limit=10))
            
    # Check end of the series
    res_df = portfolio.data
    print("\nFinal rows of simulation results:")
    columns_to_show = ["close", "signal", "target_position", "active_position", "trades", "commission_cost", "cash", "equity"]
    print(res_df[columns_to_show].tail(5))

    # Save Trade Log and generate plots
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    
    trade_log_path = os.path.join(output_dir, "trade_log.csv")
    trades_df.to_csv(trade_log_path, index=False)
    print(f"\nTrade log successfully exported to: {trade_log_path}")

    # Generate benchmark and plots
    initial_capital = portfolio.data["equity"].iloc[0]
    benchmark_curve = PerformanceMetrics.get_benchmark_equity(portfolio.data["close"], initial_capital)
    plot_paths = generate_backtest_report_plots(portfolio.data, benchmark_curve, output_dir)
    print("Diagnostic charts generated and saved:")
    for chart_name, path in plot_paths.items():
        print(f"  - {chart_name}: {path}")


if __name__ == "__main__":
    main()


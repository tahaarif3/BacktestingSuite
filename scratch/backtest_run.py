import os
import sys
import pandas as pd

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloader import DataLoader
from strat.base import BaseStrategy
from backtest.position_sizing import FixedSharesSizer, FixedFractionalSizer, VolatilityBasedSizer
from backtest.execution import ExecutionModel
from backtest.vectorized import VectorizedEngine


class SMACrossoverStrategy(BaseStrategy):
    """
    Simple Moving Average (SMA) Crossover Strategy.
    Generates a Buy signal (1) when short_window SMA is above long_window SMA,
    and a Flat/Sell signal (0) otherwise.
    """

    def __init__(self, short_window: int = 5, long_window: int = 20):
        self.short_window = short_window
        self.long_window = long_window

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        
        # Calculate moving averages
        df["sma_short"] = df["close"].rolling(window=self.short_window).mean()
        df["sma_long"] = df["close"].rolling(window=self.long_window).mean()
        
        # Generate raw signal: 1 (Buy) if short SMA > long SMA, else 0 (Flat)
        # Note: We fill NaN values (which occur during the warm-up period) with 0.
        df["signal"] = 0
        df.loc[df["sma_short"] > df["sma_long"], "signal"] = 1
        
        return df


def main():
    print("=== SPY Vectorized Backtesting Engine Verification ===")
    
    # 1. Load and clean historical SPY daily data
    data_path = os.path.join("data", "spy_daily_yfinance.parquet")
    if not os.path.exists(data_path):
        print(f"Error: {data_path} not found. Please run scratch/sample_run.py first to fetch SPY data.")
        return
        
    loader = DataLoader()
    raw_data = loader.load_data(data_path)
    cleaned_data = loader.clean_data(raw_data)
    print(f"Loaded {len(cleaned_data)} rows of SPY daily data.")

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

    # 5. Initialize and run the engine
    engine = VectorizedEngine(
        strategy=strategy,
        position_sizer=sizer,
        execution_model=execution_model,
        initial_capital=100000.0
    )
    
    print("\nRunning backtest...")
    portfolio = engine.run(cleaned_data)
    
    # 6. Display performance metrics
    summary = portfolio.get_summary()
    print("\n--- Performance Summary ---")
    for metric, value in summary.items():
        if "Return" in metric or "Volatility" in metric or "Drawdown" in metric:
            print(f"{metric}: {value * 100:.2f}%")
        elif "Equity" in metric:
            print(f"{metric}: ${value:,.2f}")
        else:
            print(f"{metric}: {value:.4f}")
            
    # Check end of the series
    res_df = portfolio.data
    print("\nFinal rows of simulation results:")
    columns_to_show = ["close", "signal", "target_position", "active_position", "trades", "commission_cost", "cash", "equity"]
    print(res_df[columns_to_show].tail(5))


if __name__ == "__main__":
    main()

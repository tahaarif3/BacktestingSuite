import os
import sys
import pandas as pd

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from domain.models import Bar
from data.dataloader import DataLoader
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedFractionalSizer
from backtest.execution import ExecutionModel
from strat import (
    BuyAndHoldStrategy,
    SMACrossoverStrategy,
    EMACrossoverStrategy,
    RSIMeanReversionStrategy,
    BollingerBandsStrategy,
    MACDStrategy
)


def load_spy_bars():
    """Loads cleaned SPY daily data and converts it to a List of domain Bar objects."""
    data_path = os.path.join("data", "spy_daily_yfinance.parquet")
    if not os.path.exists(data_path):
        raise FileNotFoundError(f"{data_path} not found. Please run scratch/sample_run.py first.")

    loader = DataLoader()
    raw_df = loader.load_data(data_path)
    cleaned_df = loader.clean_data(raw_df)
    
    bars = []
    for timestamp, row in cleaned_df.iterrows():
        bars.append(Bar(
            timestamp=timestamp,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"])
        ))
    return bars


def main():
    print("=== SPY Backtest Strategy Performance Comparison ===")
    
    try:
        bars = load_spy_bars()
        print(f"Successfully loaded {len(bars)} daily bars of SPY.")
    except Exception as e:
        print(f"Error loading bars: {e}")
        return

    # Define standard backtest parameters
    initial_capital = 100000.0
    sizer = FixedFractionalSizer(fraction=0.5, initial_capital=initial_capital)
    
    # 2 bps slippage, 5 bps commission
    execution_model = ExecutionModel(
        slippage_pct=0.0002,
        commission_pct=0.0005
    )

    # Initialize strategies to compare (long-only to compare against buy-and-hold baseline)
    strategies = {
        "Buy & Hold (Baseline)": BuyAndHoldStrategy(),
        "SMA Crossover (10/50)": SMACrossoverStrategy(fast_window=10, slow_window=50, long_only=True),
        "EMA Crossover (12/26)": EMACrossoverStrategy(fast_window=12, slow_window=26, long_only=True),
        "RSI Mean Reversion (14)": RSIMeanReversionStrategy(window=14, oversold=35.0, overbought=65.0, exit_level=50.0, long_only=True),
        "Bollinger Bands Breakout": BollingerBandsStrategy(window=20, num_std=1.5, long_only=True),
        "MACD Trend Following": MACDStrategy(fast_window=12, slow_window=26, signal_window=9, long_only=True)
    }

    results = []

    print("\nRunning backtests...")
    for name, strat in strategies.items():
        engine = EventDrivenEngine(
            strategy=strat,
            position_sizer=sizer,
            execution_model=execution_model,
            initial_capital=initial_capital,
            execution_timing="next_open"
        )
        try:
            portfolio = engine.run(bars)
            summary = portfolio.get_summary()
            
            results.append({
                "Strategy": name,
                "Total Return": f"{summary['Total Return'] * 100:.2f}%",
                "CAGR": f"{summary['Annualized Return'] * 100:.2f}%",
                "Volatility": f"{summary['Annualized Volatility'] * 100:.2f}%",
                "Sharpe Ratio": f"{summary['Sharpe Ratio']:.4f}",
                "Max Drawdown": f"{summary['Max Drawdown'] * 100:.2f}%",
                "Ending Equity": f"${summary['Final Equity']:,.2f}"
            })
        except Exception as e:
            print(f"Error executing strategy {name}: {e}")

    # Display comparison table
    df_results = pd.DataFrame(results)
    print("\n=== Performance Comparison Table ===")
    print(df_results.to_string(index=False))


if __name__ == "__main__":
    main()

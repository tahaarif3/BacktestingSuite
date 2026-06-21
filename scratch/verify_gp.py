import os
import sys
import numpy as np
import pandas as pd

# Add current directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.dataloader import DataLoader
from domain.models import Bar
from backtest.execution import ExecutionModel
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedFractionalSizer
from strat.genetic_programming import GeneticProgrammingStrategy
from analytics.metrics import PerformanceMetrics, extract_trades

def main():
    csv_path = "C:/Users/bigbo/Genetic_Trade/spy_ohlcv.csv"
    json_path = "champion_gp.json"

    print("====================================================")
    # 1. Load Data
    loader = DataLoader()
    bars = loader.get_bars(csv_path)
    n = len(bars)
    print(f"[Python] Loaded {n} bars from {csv_path}")

    # 2. Initialize GP Strategy & Precompute Signals
    strategy = GeneticProgrammingStrategy(json_path)
    print(f"[Python] Loaded GP Tree from {json_path}")
    
    # Generate signals for the entire dataset
    all_signals = strategy.generate_signals(bars)
    
    # 3. Partition Data & Signals (Warmup = 60)
    warmup = 60
    valid_len = n - warmup
    train_end = warmup + int(valid_len * 0.6)  # 60 + 59964 = 60024
    val_end = train_end + int(valid_len * 0.2)  # 60024 + 19988 = 80012

    train_bars = bars[warmup:train_end]
    train_sigs = all_signals[warmup:train_end]

    val_bars = bars[train_end:val_end]
    val_sigs = all_signals[train_end:val_end]

    test_bars = bars[val_end:n]
    test_sigs = all_signals[val_end:n]

    print(f"[Python] Split details: Train={len(train_bars)}, Val={len(val_bars)}, Test={len(test_bars)}")

    # 4. Setup Event-Driven Engine with same costs as Rust
    # Rust costs: slippage_rate = 0.0001 (1 bp), commission_per_share = 0.005 ($0.005)
    exec_model = ExecutionModel(
        slippage_pct=0.0001,
        commission_per_share=0.005
    )
    
    # Sizer: fixed fractional with 100% allocation
    sizer = FixedFractionalSizer(fraction=1.0, initial_capital=100000.0)

    # Helper function to run backtest and return report
    def run_partition(partition_name, p_bars, p_sigs):
        # Re-initialize engine for each partition to reset cash to $100k
        engine = EventDrivenEngine(
            strategy=strategy,
            position_sizer=sizer,
            execution_model=exec_model,
            initial_capital=100000.0,
            execution_timing="next_open",
            min_trade_shares=0.01
        )
        
        portfolio = engine.run(p_bars, signals=p_sigs)
        trades_df = extract_trades(portfolio.data, execution_timing="next_open")
        
        # Calculate performance metrics
        equity = pd.Series(portfolio.equity_curve)
        
        total_return = (equity.iloc[-1] / equity.iloc[0]) - 1.0
        
        # Calculate annualized return using the Rust formula (19656 bars per year)
        annualization_factor = 19656.0
        years = len(p_bars) / annualization_factor
        ann_return = (equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0 if years > 0 else 0.0
        
        # Sharpe ratio using Rust formula (high frequency 5m returns)
        pct_returns = equity.pct_change().fillna(0.0)
        mean_ret = pct_returns.mean()
        std_ret = pct_returns.std(ddof=0)
        ann_sharpe = (mean_ret / std_ret) * np.sqrt(annualization_factor) if std_ret > 1e-6 else 0.0
        
        # Sortino ratio using Rust formula
        neg_returns = pct_returns[pct_returns < 0.0]
        downside_std = np.sqrt(np.mean(neg_returns ** 2)) if not neg_returns.empty else 0.0
        ann_sortino = (mean_ret / downside_std) * np.sqrt(annualization_factor) if downside_std > 1e-6 else 0.0
        
        # Max drawdown
        peaks = equity.cummax()
        drawdowns = (equity - peaks) / peaks
        max_dd = drawdowns.min()
        
        # Trade count (exits)
        trade_count = len(trades_df)
        
        # Win rate
        # Rust: winning_trades / (trade_count / 2.0)
        # But in Python extract_trades, each round-trip trade is a single row in trades_df.
        # In Rust trade_count is incremented on every execution (entry and exit are 2 trades),
        # so report.trade_count / 2 is the number of completed trades.
        # Let's count trades with positive P&L.
        winning_trades = len(trades_df[trades_df["pnl_usd"] > 1e-8])
        win_rate = winning_trades / trade_count if trade_count > 0 else 0.0
        
        print(f"\n--- {partition_name} ---")
        print(f"  Total Return:        {total_return * 100.0:+.2f}%")
        print(f"  Annualized Return:   {ann_return * 100.0:+.2f}%")
        print(f"  Annualized Sharpe:   {ann_sharpe:.2f}")
        print(f"  Annualized Sortino:  {ann_sortino:.2f}")
        print(f"  Max Drawdown:        {max_dd * 100.0:.2f}%")
        print(f"  Trade Count (Exits): {trade_count}")
        print(f"  Win Rate:            {win_rate * 100.0:.2f}%")
        print(f"  Final Equity:        ${equity.iloc[-1]:,.2f}")

    run_partition("TRAIN (60% IN-SAMPLE)", train_bars, train_sigs)
    run_partition("VALIDATION (20% TUNING)", val_bars, val_sigs)
    run_partition("TEST (20% OUT-OF-SAMPLE)", test_bars, test_sigs)
    print("====================================================")

if __name__ == "__main__":
    main()

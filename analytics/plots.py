import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Dict

def generate_backtest_report_plots(
    portfolio_df: pd.DataFrame,
    benchmark_curve: pd.Series,
    output_dir: str,
    rolling_window: int = 20
) -> Dict[str, str]:
    """
    Generates three high-resolution diagnostic charts for the backtest performance:
    1. Equity Curve vs. Benchmark
    2. Drawdown Profile (filled area plot)
    3. Rolling Returns Comparison

    Saves them as PNG images in the specified output directory.
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    # Style parameters for modern aesthetic
    plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.edgecolor'] = '#cccccc'
    plt.rcParams['axes.linewidth'] = 0.8
    plt.rcParams['grid.color'] = '#eeeeee'
    plt.rcParams['grid.linestyle'] = '-'
    plt.rcParams['grid.linewidth'] = 0.5
    
    # Extract times
    times = portfolio_df.index
    
    # ----------------------------------------------------
    # Chart 1: Equity Curve vs. Benchmark
    # ----------------------------------------------------
    fig1, ax1 = plt.subplots(figsize=(11, 6), layout="constrained")
    ax1.plot(times, portfolio_df["equity"], label="Strategy", color="#0284c7", linewidth=2.0)
    ax1.plot(times, benchmark_curve, label="SPY Buy & Hold", color="#64748b", linewidth=1.5, linestyle="--")
    
    ax1.set_title("Equity Curve vs. SPY Benchmark", fontsize=14, fontweight="bold", pad=15, color="#1e293b")
    ax1.set_xlabel("Date", fontsize=11, color="#475569")
    ax1.set_ylabel("Equity Value ($)", fontsize=11, color="#475569")
    
    # Format Y axis with thousands separator
    ax1.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f"${x:,.0f}"))
    
    # Date formatting
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig1.autofmt_xdate()
    
    ax1.legend(loc="upper left", frameon=True, facecolor="#ffffff", edgecolor="#e2e8f0", fontsize=10)
    ax1.grid(True)
    
    equity_path = os.path.join(output_dir, "equity_comparison.png")
    fig1.savefig(equity_path, dpi=300)
    plt.close(fig1)

    # ----------------------------------------------------
    # Chart 2: Drawdown Profile
    # ----------------------------------------------------
    fig2, ax2 = plt.subplots(figsize=(11, 4), layout="constrained")
    
    # Compute Drawdown
    equity = portfolio_df["equity"]
    peaks = equity.cummax()
    drawdown = (equity - peaks) / peaks
    
    ax2.plot(times, drawdown * 100, color="#ef4444", linewidth=1.5, label="Drawdown")
    ax2.fill_between(times, drawdown * 100, 0, color="#fca5a5", alpha=0.4)
    
    ax2.set_title("Drawdown Profile (Peak-to-Trough)", fontsize=14, fontweight="bold", pad=15, color="#1e293b")
    ax2.set_xlabel("Date", fontsize=11, color="#475569")
    ax2.set_ylabel("Drawdown (%)", fontsize=11, color="#475569")
    
    # Format Y axis as percentage
    ax2.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x:.1f}%"))
    
    # Date formatting
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig2.autofmt_xdate()
    
    ax2.grid(True)
    
    drawdown_path = os.path.join(output_dir, "drawdown_chart.png")
    fig2.savefig(drawdown_path, dpi=300)
    plt.close(fig2)

    # ----------------------------------------------------
    # Chart 3: Rolling Returns
    # ----------------------------------------------------
    fig3, ax3 = plt.subplots(figsize=(11, 5), layout="constrained")
    
    # Calculate rolling returns (percentage change over rolling_window days)
    strat_rolling = portfolio_df["equity"].pct_change(rolling_window).fillna(0.0)
    bench_rolling = benchmark_curve.pct_change(rolling_window).fillna(0.0)
    
    ax3.plot(times, strat_rolling * 100, label=f"Strategy ({rolling_window}d)", color="#0284c7", linewidth=1.8)
    ax3.plot(times, bench_rolling * 100, label=f"SPY Buy & Hold ({rolling_window}d)", color="#64748b", linewidth=1.2, linestyle="--")
    
    ax3.set_title(f"Rolling {rolling_window}-Day Returns Comparison", fontsize=14, fontweight="bold", pad=15, color="#1e293b")
    ax3.set_xlabel("Date", fontsize=11, color="#475569")
    ax3.set_ylabel("Returns (%)", fontsize=11, color="#475569")
    
    # Format Y axis as percentage
    ax3.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f"{x:.1f}%"))
    
    # Date formatting
    ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig3.autofmt_xdate()
    
    ax3.legend(loc="upper left", frameon=True, facecolor="#ffffff", edgecolor="#e2e8f0", fontsize=10)
    ax3.grid(True)
    
    rolling_path = os.path.join(output_dir, "rolling_returns.png")
    fig3.savefig(rolling_path, dpi=300)
    plt.close(fig3)

    return {
        "equity_comparison": equity_path,
        "drawdown_chart": drawdown_path,
        "rolling_returns": rolling_path
    }

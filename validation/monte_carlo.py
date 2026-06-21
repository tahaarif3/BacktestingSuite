import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import Dict, Any

class MonteCarloSimulator:
    """
    Assesses strategy sequence risk by shuffling trade P&L percentage returns
    and projecting capital paths to determine drawdown distributions and ruin probability.
    """

    @staticmethod
    def simulate_trade_shuffling(
        trades_df: pd.DataFrame,
        initial_capital: float = 100000.0,
        iterations: int = 1000,
        ruin_threshold_pct: float = 0.5,
        output_dir: str = "output"
    ) -> Dict[str, Any]:
        """
        Runs Monte Carlo trade-shuffling simulation.
        Returns statistical metrics and saves a paths visualization plot.
        """
        if trades_df.empty or "pnl_pct" not in trades_df.columns:
            return {
                "probability_of_ruin": 0.0,
                "median_max_drawdown": 0.0,
                "drawdown_95th_percentile": 0.0,
                "drawdown_5th_percentile": 0.0,
                "median_final_equity": initial_capital,
                "final_equity_5th_percentile": initial_capital,
                "final_equity_95th_percentile": initial_capital,
                "total_trades": 0
            }

        # Extract P&L returns relative to initial capital to prevent size distortion from partial exits
        returns = (trades_df["pnl_usd"] / initial_capital).values
        n_trades = len(returns)

        
        # Array to store simulated paths: shape (iterations, n_trades + 1)
        paths = np.zeros((iterations, n_trades + 1))
        paths[:, 0] = initial_capital
        
        ruin_count = 0
        max_drawdowns = np.zeros(iterations)
        final_equities = np.zeros(iterations)

        ruin_barrier = initial_capital * ruin_threshold_pct

        for i in range(iterations):
            # Shuffle returns sequence
            shuffled_returns = np.random.choice(returns, size=n_trades, replace=False)
            
            # Project capital curve: Capital_k = Capital_{k-1} * (1 + return_k)
            # Using cumprod on (1 + returns)
            cap_curve = initial_capital * np.cumprod(1.0 + shuffled_returns)
            paths[i, 1:] = cap_curve
            
            # Check for ruin
            if np.any(cap_curve < ruin_barrier):
                ruin_count += 1
                
            # Calculate max drawdown for this path
            peaks = np.maximum.accumulate(paths[i])
            drawdowns = (paths[i] - peaks) / peaks
            max_drawdowns[i] = drawdowns.min()
            
            final_equities[i] = cap_curve[-1]

        # Calculate statistics
        prob_of_ruin = ruin_count / iterations
        
        # Max drawdown percentiles
        median_mdd = np.percentile(max_drawdowns, 50)
        mdd_95th = np.percentile(max_drawdowns, 5) # 5th percentile return index corresponds to 95% worst DD
        mdd_5th = np.percentile(max_drawdowns, 95)
        
        # Final equity percentiles
        median_fe = np.percentile(final_equities, 50)
        fe_5th = np.percentile(final_equities, 5)
        fe_95th = np.percentile(final_equities, 95)

        # Plot paths
        os.makedirs(output_dir, exist_ok=True)
        plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['axes.edgecolor'] = '#cccccc'
        plt.rcParams['axes.linewidth'] = 0.8
        plt.rcParams['grid.color'] = '#eeeeee'
        plt.rcParams['grid.linestyle'] = '-'
        plt.rcParams['grid.linewidth'] = 0.5

        fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
        
        # Plot a subset of paths (e.g., up to 100 paths for visual clarity)
        plot_limit = min(100, iterations)
        for i in range(plot_limit):
            ax.plot(range(n_trades + 1), paths[i], color="#cbd5e1", alpha=0.5, linewidth=0.8)
            
        # Plot median path
        # Find the path index closest to the median final equity
        median_idx = np.abs(final_equities - median_fe).argmin()
        ax.plot(range(n_trades + 1), paths[median_idx], color="#0284c7", linewidth=2.5, label=f"Median Path (Ending: ${median_fe:,.2f})")
        
        # Plot risk parameters
        ax.axhline(ruin_barrier, color="#ef4444", linestyle="--", linewidth=1.5, label=f"Ruin Barrier (${ruin_barrier:,.0f})")
        
        ax.set_title(f"Monte Carlo Simulations: Trade Shuffling ({iterations} Paths)", fontsize=14, fontweight="bold", pad=15, color="#1e293b")
        ax.set_xlabel("Trade Number", fontsize=11, color="#475569")
        ax.set_ylabel("Portfolio Value ($)", fontsize=11, color="#475569")
        
        ax.get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, loc: f"${x:,.0f}"))
        ax.legend(loc="upper left", frameon=True, facecolor="#ffffff", edgecolor="#e2e8f0", fontsize=10)
        ax.grid(True)
        
        plot_path = os.path.join(output_dir, "monte_carlo_paths.png")
        fig.savefig(plot_path, dpi=300)
        plt.close(fig)

        return {
            "probability_of_ruin": float(prob_of_ruin),
            "median_max_drawdown": float(median_mdd),
            "drawdown_95th_percentile": float(mdd_95th),
            "drawdown_5th_percentile": float(mdd_5th),
            "median_final_equity": float(median_fe),
            "final_equity_5th_percentile": float(fe_5th),
            "final_equity_95th_percentile": float(fe_95th),
            "total_trades": int(n_trades),
            "plot_path": plot_path
        }

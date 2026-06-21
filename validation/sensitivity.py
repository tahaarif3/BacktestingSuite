import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from typing import List, Dict, Any, Type
from domain.models import Bar
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedFractionalSizer
from backtest.execution import ExecutionModel
from analytics.metrics import PerformanceMetrics, extract_trades

class CostSensitivityAnalyzer:
    """
    Measures the robustness of a strategy under varying execution costs
    (commissions and slippage) to map its transaction friction tolerance.
    """

    def __init__(
        self,
        strategy_class: Type,
        strategy_params: Dict[str, Any],
        initial_capital: float = 100000.0,
        sizer_fraction: float = 0.5
    ):
        self.strategy_class = strategy_class
        self.strategy_params = strategy_params
        self.initial_capital = initial_capital
        self.sizer_fraction = sizer_fraction

    def run_sensitivity_analysis(
        self,
        bars: List[Bar],
        commission_grid: List[float],
        slippage_grid: List[float],
        output_dir: str = "output"
    ) -> pd.DataFrame:
        """
        Runs backtests across the cost grid.
        Returns a DataFrame of results and saves a diagnostic heatmap to disk.
        """
        results = []
        
        # Grid of results for plotting
        sharpe_matrix = np.zeros((len(commission_grid), len(slippage_grid)))

        for i, comm in enumerate(commission_grid):
            for j, slip in enumerate(slippage_grid):
                # Instantiate components
                strat = self.strategy_class(**self.strategy_params)
                sizer = FixedFractionalSizer(fraction=self.sizer_fraction, initial_capital=self.initial_capital)
                exec_model = ExecutionModel(slippage_pct=slip, commission_pct=comm)
                
                engine = EventDrivenEngine(
                    strategy=strat,
                    position_sizer=sizer,
                    execution_model=exec_model,
                    initial_capital=self.initial_capital
                )

                try:
                    portfolio = engine.run(bars)
                    trades_df = extract_trades(portfolio.data)
                    summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)
                    
                    total_return = summary.get("Total Return", 0.0)
                    sharpe = summary.get("Sharpe Ratio", 0.0)
                    max_dd = summary.get("Max Drawdown", 0.0)
                    
                    results.append({
                        "commission_pct": comm,
                        "slippage_pct": slip,
                        "total_return": total_return,
                        "sharpe_ratio": sharpe,
                        "max_drawdown": max_dd,
                        "total_trades": len(trades_df)
                    })
                    
                    sharpe_matrix[i, j] = sharpe
                except Exception as e:
                    print(f"Error evaluating commission={comm}, slippage={slip}: {e}")
                    results.append({
                        "commission_pct": comm,
                        "slippage_pct": slip,
                        "total_return": -1.0,
                        "sharpe_ratio": -10.0,
                        "max_drawdown": -1.0,
                        "total_trades": 0
                    })
                    sharpe_matrix[i, j] = -10.0

        results_df = pd.DataFrame(results)

        # Plot heatmap of Sharpe Ratios
        os.makedirs(output_dir, exist_ok=True)
        plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
        plt.rcParams['font.family'] = 'sans-serif'
        
        fig, ax = plt.subplots(figsize=(8, 6), layout="constrained")
        
        # Plot using imshow
        im = ax.imshow(sharpe_matrix, cmap="RdYlGn", aspect="auto", origin="lower")
        
        # Colorbar
        cbar = ax.figure.colorbar(im, ax=ax)
        cbar.ax.set_ylabel("Sharpe Ratio", rotation=-90, va="bottom", fontsize=11, color="#475569")
        
        # Labels and ticks
        ax.set_xticks(np.arange(len(slippage_grid)))
        ax.set_yticks(np.arange(len(commission_grid)))
        
        # Format labels as percentages
        ax.set_xticklabels([f"{s * 100:.3f}%" for s in slippage_grid])
        ax.set_yticklabels([f"{c * 100:.3f}%" for c in commission_grid])
        
        ax.set_xlabel("Slippage Rate (%)", fontsize=11, color="#475569", labelpad=10)
        ax.set_ylabel("Commission Rate (%)", fontsize=11, color="#475569", labelpad=10)
        
        ax.set_title("Cost Sensitivity: Sharpe Ratio Heatmap", fontsize=13, fontweight="bold", pad=15, color="#1e293b")
        
        # Annotate numbers in grid cells
        for i in range(len(commission_grid)):
            for j in range(len(slippage_grid)):
                val = sharpe_matrix[i, j]
                # Adjust text color based on cell color
                text_color = "black" if -1.0 < val < 2.0 else "white"
                ax.text(j, i, f"{val:.3f}", ha="center", va="center", color=text_color, fontweight="semibold")
        
        ax.grid(False) # Turn off grid lines inside heatmap cells
        
        plot_path = os.path.join(output_dir, "cost_sensitivity.png")
        fig.savefig(plot_path, dpi=300)
        plt.close(fig)

        return results_df

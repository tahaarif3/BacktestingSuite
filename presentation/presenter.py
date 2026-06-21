import pandas as pd
from typing import Dict, Any


class PortfolioPresenter:
    """
    Presenter layer to format and display backtest results.
    Decouples visual presentation code from core calculations.
    """

    @staticmethod
    def format_summary(summary: Dict[str, Any]) -> str:
        """
        Formats a portfolio performance summary dictionary into a readable string.
        """
        lines = ["\n--- Performance Summary ---"]
        for metric, value in summary.items():
            m_lower = metric.lower()
            if "return" in m_lower or "cagr" in m_lower or "volatility" in m_lower or "drawdown" in m_lower or "rate" in m_lower or "exposure" in m_lower:
                lines.append(f"{metric:<25}: {value * 100:.2f}%")
            elif "ratio" in m_lower or "factor" in m_lower:
                lines.append(f"{metric:<25}: {value:.4f}")
            elif "equity" in m_lower or "capital" in m_lower:
                lines.append(f"{metric:<25}: ${value:,.2f}")
            elif isinstance(value, int) or "trades" in m_lower:
                lines.append(f"{metric:<25}: {value}")
            elif isinstance(value, float):
                lines.append(f"{metric:<25}: {value:.4f}")
            else:
                lines.append(f"{metric:<25}: {value}")
        return "\n".join(lines)

    @staticmethod
    def format_trade_log(trades_df: pd.DataFrame, limit: int = 10) -> str:
        """
        Formats the recent trades into a clean terminal table.
        """
        if trades_df.empty:
            return "\n--- Trade Log ---\nNo trades executed."
        
        df_display = trades_df.tail(limit)
        
        lines = ["\n--- Trade Log (Last {} Trades) ---".format(limit)]
        header = f"{'Entry Time':<20} | {'Exit Time':<20} | {'Dir':<5} | {'Size':<6} | {'Entry Px':<10} | {'Exit Px':<10} | {'PnL ($)':<10} | {'PnL (%)':<8} | {'Dur (Days)':<10}"
        lines.append(header)
        lines.append("-" * len(header))
        
        for idx, row in df_display.iterrows():
            entry_str = row["entry_time"].strftime("%Y-%m-%d %H:%M") if hasattr(row["entry_time"], "strftime") else str(row["entry_time"])
            exit_str = row["exit_time"].strftime("%Y-%m-%d %H:%M") if hasattr(row["exit_time"], "strftime") else str(row["exit_time"])
            
            pnl_usd_val = row["pnl_usd"]
            pnl_pct_val = row["pnl_pct"] * 100
            
            line = (
                f"{entry_str:<20} | "
                f"{exit_str:<20} | "
                f"{row['direction']:<5} | "
                f"{row['size']:<6.1f} | "
                f"{row['entry_price']:<10.2f} | "
                f"{row['exit_price']:<10.2f} | "
                f"{pnl_usd_val:<10.2f} | "
                f"{pnl_pct_val:<8.2f}% | "
                f"{int(row['duration_days']):<10}"
            )
            lines.append(line)
        return "\n".join(lines)


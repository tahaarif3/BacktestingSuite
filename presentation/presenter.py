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
            if "Return" in metric or "Volatility" in metric or "Drawdown" in metric or "Ratio" in metric:
                # If it's Sharpe Ratio, we format it as a normal decimal, otherwise percentage
                if "Sharpe" in metric or "Ratio" in metric:
                    lines.append(f"{metric:<25}: {value:.4f}")
                else:
                    lines.append(f"{metric:<25}: {value * 100:.2f}%")
            elif "Equity" in metric or "Capital" in metric:
                lines.append(f"{metric:<25}: ${value:,.2f}")
            else:
                lines.append(f"{metric:<25}: {value:.4f}")
        return "\n".join(lines)

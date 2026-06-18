import pandas as pd
import numpy as np
from typing import Dict, Any


class Portfolio:
    """
    Encapsulates the results of a vectorized backtest simulation.
    Tracks cash, positions, and equity curve over time, and computes key summary statistics.
    """

    def __init__(self, data: pd.DataFrame, cash: pd.Series, positions: pd.Series, equity_curve: pd.Series):
        """
        Args:
            data: The full DataFrame containing the simulation results.
            cash: Series tracking cash balance over time.
            positions: Series tracking number of shares held over time.
            equity_curve: Series tracking total marked-to-market portfolio value.
        """
        self.data = data
        self.cash = cash
        self.positions = positions
        self.equity_curve = equity_curve

    @property
    def total_return(self) -> float:
        """Calculates total return over the entire simulation period."""
        if self.equity_curve.empty or self.equity_curve.iloc[0] == 0:
            return 0.0
        return (self.equity_curve.iloc[-1] / self.equity_curve.iloc[0]) - 1.0

    @property
    def annualized_return(self) -> float:
        """Calculates annualized return (CAGR) based on calendar days."""
        if self.equity_curve.empty or len(self.equity_curve) < 2:
            return 0.0
        days = (self.equity_curve.index[-1] - self.equity_curve.index[0]).days
        if days <= 0:
            return 0.0
        years = days / 365.25
        return (self.equity_curve.iloc[-1] / self.equity_curve.iloc[0]) ** (1.0 / years) - 1.0

    @property
    def daily_returns(self) -> pd.Series:
        """Returns the daily percentage change of the equity curve."""
        return self.equity_curve.pct_change().fillna(0.0)

    @property
    def annualized_volatility(self) -> float:
        """Calculates annualized volatility of daily returns (assuming 252 trading days)."""
        returns = self.daily_returns
        if len(returns) < 2:
            return 0.0
        return returns.std() * np.sqrt(252)

    @property
    def sharpe_ratio(self) -> float:
        """Calculates the Sharpe ratio assuming a 0% risk-free rate."""
        returns = self.daily_returns
        std = returns.std()
        if std == 0 or len(returns) < 2:
            return 0.0
        # Sharpe ratio = (mean / std) * sqrt(252)
        return (returns.mean() / std) * np.sqrt(252)

    @property
    def max_drawdown(self) -> float:
        """Calculates the maximum peak-to-trough drawdown (returns as negative decimal)."""
        if self.equity_curve.empty:
            return 0.0
        peaks = self.equity_curve.cummax()
        drawdowns = (self.equity_curve - peaks) / peaks
        return drawdowns.min()

    def get_summary(self) -> Dict[str, Any]:
        """
        Compiles performance metrics into a summary dictionary.
        
        Returns:
            Dict: Dictionary containing performance statistics.
        """
        return {
            "Total Return": self.total_return,
            "Annualized Return": self.annualized_return,
            "Annualized Volatility": self.annualized_volatility,
            "Sharpe Ratio": self.sharpe_ratio,
            "Max Drawdown": self.max_drawdown,
            "Initial Equity": self.equity_curve.iloc[0] if not self.equity_curve.empty else 0.0,
            "Final Equity": self.equity_curve.iloc[-1] if not self.equity_curve.empty else 0.0,
        }

import pandas as pd
import numpy as np
from typing import Dict, Any, List
from domain.models import Bar


class Portfolio:
    """
    Encapsulates the results of a backtest simulation.
    Tracks cash, positions, and equity curve over time, and computes key summary statistics.
    """

    def __init__(
        self,
        data: Any,
        cash: Any = None,
        positions: Any = None,
        equity_curve: Any = None,
        trades: Any = None,
        slippage_cost: Any = None,
        commission_cost: Any = None,
        target_positions: Any = None,
        signals: Any = None
    ):
        """
        Args:
            data: DataFrame (vectorized) or List[Bar] (event-driven).
            cash: pd.Series or List[float].
            positions: pd.Series or List[float].
            equity_curve: pd.Series or List[float].
        """
        if isinstance(data, pd.DataFrame):
            self.data = data
            self.cash = cash
            self.positions = positions
            self.equity_curve = equity_curve
        else:
            # We assume data is List[Bar] from clean event-driven engine
            bars: List[Bar] = data
            timestamps = [b.timestamp for b in bars]
            
            self.cash = pd.Series(cash, index=timestamps)
            self.positions = pd.Series(positions, index=timestamps)
            self.equity_curve = pd.Series(equity_curve, index=timestamps)
            
            # Construct DataFrame internally
            df = pd.DataFrame({
                "open": [b.open for b in bars],
                "high": [b.high for b in bars],
                "low": [b.low for b in bars],
                "close": [b.close for b in bars],
                "volume": [b.volume for b in bars],
                "signal": signals if signals is not None else [0.0] * len(bars),
                "target_position": target_positions,
                "active_position": positions,
                "trades": trades,
                "slippage_cost": slippage_cost,
                "commission_cost": commission_cost,
                "cash": cash,
                "equity": equity_curve
            }, index=timestamps)
            df.index.name = "timestamp"
            self.data = df


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
        # Pandas/NumPy Concept: Vectorized Arithmetic (pct_change) and Handling Missing Data (fillna)
        return self.equity_curve.pct_change().fillna(0.0)

    @property
    def annualized_volatility(self) -> float:
        """Calculates annualized volatility of daily returns (assuming 252 trading days)."""
        returns = self.daily_returns
        if len(returns) < 2:
            return 0.0
        # NumPy Concept: np.sqrt performs element-wise mathematical square root calculation
        return returns.std() * np.sqrt(252)

    @property
    def sharpe_ratio(self) -> float:
        """Calculates the Sharpe ratio assuming a 0% risk-free rate."""
        returns = self.daily_returns
        std = returns.std()
        if std == 0 or len(returns) < 2:
            return 0.0
        # Sharpe ratio = (mean / std) * sqrt(252)
        # NumPy Concept: np.sqrt performs element-wise mathematical square root calculation
        return (returns.mean() / std) * np.sqrt(252)

    @property
    def max_drawdown(self) -> float:
        """Calculates the maximum peak-to-trough drawdown (returns as negative decimal)."""
        if self.equity_curve.empty:
            return 0.0
        # Pandas/NumPy Concept: Cumulative and Rolling Calculations (cummax)
        peaks = self.equity_curve.cummax()
        # Pandas/NumPy Concept: Vectorized Arithmetic & Operations
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

from abc import ABC, abstractmethod
import pandas as pd
import numpy as np


class BasePositionSizer(ABC):
    """
    Abstract Base Class for translating strategy signals into target position sizes (shares).
    """

    @abstractmethod
    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculates the target position sizes (number of shares) for each timestamp.
        
        Args:
            data: DataFrame containing historical market data and a 'signal' column.
            
        Returns:
            pd.Series: Series representing the target shares for each timestamp.
        """
        pass


class FixedSharesSizer(BasePositionSizer):
    """
    Sizes positions based on a fixed number of shares per signal.
    """

    def __init__(self, fixed_shares: int = 100):
        self.fixed_shares = fixed_shares

    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        if "signal" not in data.columns:
            raise ValueError("Data must contain 'signal' column.")
        return data["signal"] * self.fixed_shares


class FixedFractionalSizer(BasePositionSizer):
    """
    Sizes positions based on a target percentage of the rolling account equity.
    Generates target share sizes using a vectorized estimation of rolling equity.
    """

    def __init__(self, fraction: float = 0.2, initial_capital: float = 100000.0):
        """
        Args:
            fraction: Fraction of equity to allocate to the position (e.g. 0.2 for 20%).
            initial_capital: Initial portfolio value used as the starting point for sizing.
        """
        self.fraction = fraction
        self.initial_capital = initial_capital

    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        if "signal" not in data.columns or "close" not in data.columns:
            raise ValueError("Data must contain 'signal' and 'close' columns.")

        signals = data["signal"]
        prices = data["close"]

        # Calculate daily asset returns
        price_returns = prices.pct_change().fillna(0)

        # Shift signals by 1 to reflect active positions for return calculation (prevent look-ahead bias)
        active_signals = signals.shift(1).fillna(0)

        # Compute strategy returns based on target allocation
        strat_returns = active_signals * self.fraction * price_returns

        # Compute cumulative growth and estimate rolling equity curve
        cum_growth = (1 + strat_returns).cumprod()
        estimated_equity = self.initial_capital * cum_growth

        # Shift equity by 1 to size today's positions using yesterday's ending equity
        prev_equity = estimated_equity.shift(1).fillna(self.initial_capital)

        # Allocate cash and translate to target share sizes
        target_cash_allocation = prev_equity * self.fraction
        target_shares = (signals * target_cash_allocation) / prices

        return target_shares.fillna(0).astype(float)


class VolatilityBasedSizer(BasePositionSizer):
    """
    Sizes positions inversely proportional to historical price volatility.
    Uses rolling True Range / Average True Range (ATR) if High/Low prices are present,
    otherwise falls back to rolling standard deviation of close price differences.
    """

    def __init__(self, target_risk_per_trade: float = 1000.0, window: int = 14):
        """
        Args:
            target_risk_per_trade: The absolute dollar risk allocated per trade.
            window: Rolling window length for volatility calculations.
        """
        self.target_risk_per_trade = target_risk_per_trade
        self.window = window

    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        if "signal" not in data.columns or "close" not in data.columns:
            raise ValueError("Data must contain 'signal' and 'close' columns.")

        signals = data["signal"]

        # Calculate volatility metric
        if "high" in data.columns and "low" in data.columns:
            # Average True Range (ATR)
            high = data["high"]
            low = data["low"]
            prev_close = data["close"].shift(1)

            tr = pd.concat([
                high - low,
                (high - prev_close).abs(),
                (low - prev_close).abs()
            ], axis=1).max(axis=1)

            volatility = tr.rolling(window=self.window).mean()
        else:
            # Fall back to rolling mean of absolute close price daily diffs
            volatility = data["close"].diff().abs().rolling(window=self.window).mean()

        # Handle NaNs and zero values to prevent division by zero errors
        volatility = volatility.ffill().bfill()
        # Replace remaining 0s or NaNs with a default multiplier
        volatility = volatility.replace(0, np.nan).fillna(1.0)

        # Shift volatility by 1 to size today's trade using yesterday's volatility (no look-ahead)
        volatility_active = volatility.shift(1).fillna(volatility.iloc[0] if not volatility.empty else 1.0)

        # Calculate target shares: signal * (Target Risk / Volatility)
        target_shares = signals * (self.target_risk_per_trade / volatility_active)

        return target_shares.fillna(0).astype(float)

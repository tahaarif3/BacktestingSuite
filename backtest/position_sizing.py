from abc import ABC, abstractmethod
import pandas as pd
import numpy as np
from domain.interfaces import IPositionSizer
from domain.models import Bar


class BasePositionSizer(IPositionSizer, ABC):
    """
    Abstract Base Class for translating strategy signals into target position sizes (shares).
    Conforms to domain IPositionSizer interface.
    """

    @abstractmethod
    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        """
        Calculates the target position sizes (number of shares) for each timestamp (Vectorized).
        
        Args:
            data: DataFrame containing historical market data and a 'signal' column.
            
        Returns:
            pd.Series: Series representing the target shares for each timestamp.
        """
        pass

    @abstractmethod
    def size_position(
        self, signal: float, price: float, current_equity: float, current_bar: Bar
    ) -> float:
        """
        Calculates the target position size (number of shares) dynamically for a single timestamp.
        Conforms to IPositionSizer.
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

    def size_position(
        self, signal: float, price: float, current_equity: float, current_bar: Bar
    ) -> float:
        return float(signal * self.fixed_shares)


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

        # Shift signals by 1 to reflect active positions for return calculation
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

    def size_position(
        self, signal: float, price: float, current_equity: float, current_bar: Bar
    ) -> float:
        if price <= 0:
            return 0.0
        target_cash_allocation = current_equity * self.fraction
        return float((signal * target_cash_allocation) / price)


class VolatilityBasedSizer(BasePositionSizer):
    """
    Sizes positions inversely proportional to historical price volatility.
    Calculates volatility internally using sequential bars.
    """

    def __init__(self, target_risk_per_trade: float = 1000.0, window: int = 14):
        """
        Args:
            target_risk_per_trade: The absolute dollar risk allocated per trade.
            window: Rolling window length for volatility calculations.
        """
        self.target_risk_per_trade = target_risk_per_trade
        self.window = window
        self._history = []

    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        if "signal" not in data.columns or "close" not in data.columns:
            raise ValueError("Data must contain 'signal' and 'close' columns.")

        signals = data["signal"]

        # Calculate volatility metric vectorially
        if "high" in data.columns and "low" in data.columns:
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
            volatility = data["close"].diff().abs().rolling(window=self.window).mean()

        volatility = volatility.ffill().bfill()
        volatility = volatility.replace(0, np.nan).fillna(1.0)
        volatility_active = volatility.shift(1).fillna(volatility.iloc[0] if not volatility.empty else 1.0)

        target_shares = signals * (self.target_risk_per_trade / volatility_active)
        return target_shares.fillna(0).astype(float)

    def size_position(
        self, signal: float, price: float, current_equity: float, current_bar: Bar
    ) -> float:
        # Cache the incoming bar to compute historical volatility
        self._history.append(current_bar)
        if len(self._history) > self.window + 1:
            self._history.pop(0)

        vol = self._calculate_volatility()
        return float(signal * (self.target_risk_per_trade / vol))

    def _calculate_volatility(self) -> float:
        if len(self._history) < 2:
            return 1.0  # Default fallback when history is insufficient

        # Calculate Average True Range (ATR) if High/Low are present, else absolute close diffs
        has_high_low = all(b.high is not None and b.low is not None for b in self._history)
        
        if has_high_low:
            tr_values = []
            for i in range(1, len(self._history)):
                curr = self._history[i]
                prev = self._history[i - 1]
                tr = max(
                    curr.high - curr.low,
                    abs(curr.high - prev.close),
                    abs(curr.low - prev.close)
                )
                tr_values.append(tr)
            if not tr_values:
                return 1.0
            avg_tr = sum(tr_values) / len(tr_values)
            return avg_tr if avg_tr > 1e-8 else 1.0
        else:
            diffs = []
            for i in range(1, len(self._history)):
                diffs.append(abs(self._history[i].close - self._history[i - 1].close))
            if not diffs:
                return 1.0
            avg_diff = sum(diffs) / len(diffs)
            return avg_diff if avg_diff > 1e-8 else 1.0


class ATRPercentRiskSizer(BasePositionSizer):
    """Risk a percentage of current equity using a fixed ATR stop distance.

    Shares are fixed when a new position opens and remain unchanged until the
    strategy exits.  With the defaults, position risk is:

        0.5% of equity / (2 * ATR(14))
    """

    def __init__(
        self,
        risk_fraction: float = 0.005,
        window: int = 14,
        stop_multiple: float = 2.0,
    ):
        self.risk_fraction = max(0.0, float(risk_fraction))
        self.window = max(2, int(window))
        self.stop_multiple = max(0.01, float(stop_multiple))
        self._history = []
        self._previous_signal = 0.0
        self._position_shares = 0.0

    @staticmethod
    def _true_range(data: pd.DataFrame) -> pd.Series:
        previous_close = data["close"].shift(1)
        return pd.concat(
            [
                data["high"] - data["low"],
                (data["high"] - previous_close).abs(),
                (data["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

    def size_positions(self, data: pd.DataFrame) -> pd.Series:
        required = {"signal", "high", "low", "close"}
        if not required.issubset(data.columns):
            raise ValueError(
                "Data must contain signal, high, low, and close columns."
            )

        atr = self._true_range(data).rolling(
            self.window, min_periods=self.window
        ).mean()
        entries = data["signal"].ne(0.0) & data["signal"].shift(
            1, fill_value=0.0
        ).eq(0.0)
        risk_dollars = getattr(self, "initial_capital", 100000.0)
        entry_shares = (
            risk_dollars
            * self.risk_fraction
            / (self.stop_multiple * atr.replace(0.0, np.nan))
        )
        targets = entry_shares.where(entries).ffill()
        targets = targets.where(data["signal"].ne(0.0), 0.0)
        return (targets * np.sign(data["signal"])).fillna(0.0).astype(float)

    def size_position(
        self,
        signal: float,
        price: float,
        current_equity: float,
        current_bar: Bar,
    ) -> float:
        # A sizer can be reused across runs; reset if timestamps go backwards.
        if (
            self._history
            and current_bar.timestamp <= self._history[-1].timestamp
        ):
            self._history = []
            self._previous_signal = 0.0
            self._position_shares = 0.0

        self._history.append(current_bar)
        if len(self._history) > self.window + 1:
            self._history.pop(0)

        direction = float(np.sign(signal))
        if direction == 0.0:
            self._previous_signal = 0.0
            self._position_shares = 0.0
            return 0.0

        if self._previous_signal == 0.0 or np.sign(
            self._previous_signal
        ) != direction:
            atr = self._calculate_atr()
            risk_dollars = max(0.0, current_equity) * self.risk_fraction
            self._position_shares = (
                direction
                * risk_dollars
                / (self.stop_multiple * atr)
            )

        self._previous_signal = direction
        return float(self._position_shares)

    def _calculate_atr(self) -> float:
        if len(self._history) < 2:
            return 1.0

        true_ranges = []
        for i in range(1, len(self._history)):
            current = self._history[i]
            previous = self._history[i - 1]
            true_ranges.append(
                max(
                    current.high - current.low,
                    abs(current.high - previous.close),
                    abs(current.low - previous.close),
                )
            )
        atr = float(np.mean(true_ranges[-self.window :]))
        return atr if np.isfinite(atr) and atr > 1e-8 else 1.0

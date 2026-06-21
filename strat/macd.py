from typing import List
import pandas as pd
import numpy as np
from domain.models import Bar
from strat.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """
    Moving Average Convergence Divergence (MACD) Trend Following Strategy.
    - Go Long (1.0) when MACD Line > Signal Line.
    - Go Short (-1.0) or Flat (0.0) when MACD Line <= Signal Line.
    """

    def __init__(
        self,
        fast_window: int = 12,
        slow_window: int = 26,
        signal_window: int = 9,
        long_only: bool = True
    ):
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.signal_window = signal_window
        self.long_only = long_only

        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be less than slow_window.")

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates trading signals for a sequence of bars using MACD crossovers.
        """
        if not bars:
            return []

        # Convert List[Bar] to DataFrame for calculations
        df = pd.DataFrame([{"close": bar.close} for bar in bars])

        # Calculate fast and slow EMAs
        fast_ema = df["close"].ewm(span=self.fast_window, adjust=False).mean()
        slow_ema = df["close"].ewm(span=self.slow_window, adjust=False).mean()

        # MACD Line
        df["macd_line"] = fast_ema - slow_ema

        # Signal Line (EMA of MACD Line)
        df["macd_signal"] = df["macd_line"].ewm(span=self.signal_window, adjust=False).mean()

        # Vectorized signal logic
        df["signal"] = np.where(
            df["macd_line"] > df["macd_signal"],
            1.0,
            -1.0 if not self.long_only else 0.0
        )

        # Set signal to 0.0 for the warm-up period to prevent false initial entries
        warmup = max(self.fast_window, self.slow_window) + self.signal_window
        df.iloc[:warmup - 1, df.columns.get_loc("signal")] = 0.0

        return df["signal"].tolist()

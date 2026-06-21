from typing import List
import pandas as pd
import numpy as np
from domain.models import Bar
from strat.base import BaseStrategy


class EMACrossoverStrategy(BaseStrategy):
    """
    Exponential Moving Average (EMA) Crossover Strategy.
    Generates a Buy signal (1.0) when the fast EMA is above the slow EMA,
    and a Short signal (-1.0) or Flat signal (0.0) when below.
    """

    def __init__(self, fast_window: int = 12, slow_window: int = 26, long_only: bool = True):
        self.fast_window = fast_window
        self.slow_window = slow_window
        self.long_only = long_only

        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be less than slow_window.")

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates trading signals for a sequence of bars using EMA crossover.
        """
        if not bars:
            return []

        # Convert List[Bar] to DataFrame for high-performance vectorized calculation
        df = pd.DataFrame([{"close": bar.close} for bar in bars])

        # Calculate Exponential Moving Averages
        df["ema_fast"] = df["close"].ewm(span=self.fast_window, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_window, adjust=False).mean()

        # Vectorized signal assignment using numpy where
        df["signal"] = np.where(
            df["ema_fast"] > df["ema_slow"],
            1.0,
            -1.0 if not self.long_only else 0.0
        )

        # Set signal to 0.0 for the warm-up period to avoid cold start issues
        df.iloc[:self.slow_window - 1, df.columns.get_loc("signal")] = 0.0

        return df["signal"].tolist()

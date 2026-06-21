from typing import List
import pandas as pd
import numpy as np
from domain.models import Bar
from strat.base import BaseStrategy


class BollingerBandsStrategy(BaseStrategy):
    """
    Bollinger Bands Breakout Strategy.
    - Go Long (1.0) when close price breaks above the Upper Bollinger Band.
    - Go Short (-1.0) or Flat (0.0) when close price breaks below the Lower Bollinger Band.
    - Hold the position between band boundaries (forward filled).
    """

    def __init__(self, window: int = 20, num_std: float = 2.0, long_only: bool = True):
        self.window = window
        self.num_std = num_std
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates trading signals for a sequence of bars using Bollinger Bands breakouts.
        """
        if not bars:
            return []

        # Convert List[Bar] to DataFrame for calculations
        df = pd.DataFrame([{"close": bar.close} for bar in bars])

        # Calculate Middle Band (SMA) and Standard Deviation
        df["bb_middle"] = df["close"].rolling(window=self.window).mean()
        df["bb_std"] = df["close"].rolling(window=self.window).std()

        # Calculate Upper and Lower Bollinger Bands
        df["bb_upper"] = df["bb_middle"] + (self.num_std * df["bb_std"])
        df["bb_lower"] = df["bb_middle"] - (self.num_std * df["bb_std"])

        # Determine signals chronologically using a state tracker
        signals = np.zeros(len(df))
        current_state = 0.0  # 0: flat, 1: long, -1: short

        close_prices = df["close"].values
        upper_bands = df["bb_upper"].values
        lower_bands = df["bb_lower"].values

        for t in range(len(df)):
            if t < self.window - 1:
                signals[t] = 0.0
                continue

            close = close_prices[t]
            upper = upper_bands[t]
            lower = lower_bands[t]

            # Signal triggers
            if close > upper:
                current_state = 1.0
            elif close < lower:
                current_state = -1.0 if not self.long_only else 0.0

            signals[t] = current_state

        return list(signals)

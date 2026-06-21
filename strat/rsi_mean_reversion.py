from typing import List
import pandas as pd
import numpy as np
from domain.models import Bar
from strat.base import BaseStrategy


class RSIMeanReversionStrategy(BaseStrategy):
    """
    RSI Mean Reversion Strategy (using Wilder's smoothing for RSI).
    - Buy (1.0) when RSI drops below oversold (30.0), exit (0.0) when RSI rises above exit_level (50.0).
    - Short (-1.0) when RSI rises above overbought (70.0), exit (0.0) when RSI drops below exit_level (50.0).
    """

    def __init__(
        self,
        window: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_level: float = 50.0,
        long_only: bool = True
    ):
        self.window = window
        self.oversold = oversold
        self.overbought = overbought
        self.exit_level = exit_level
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates trading signals for a sequence of bars using RSI mean reversion.
        """
        if not bars:
            return []

        # Convert List[Bar] to DataFrame for high-performance calculations
        df = pd.DataFrame([{"close": bar.close} for bar in bars])

        # Calculate Wilder's RSI
        delta = df["close"].diff()
        up = delta.clip(lower=0)
        down = -delta.clip(upper=0)

        # Wilder's smoothing uses alpha = 1 / window
        roll_up = up.ewm(alpha=1.0 / self.window, adjust=False).mean()
        roll_down = down.ewm(alpha=1.0 / self.window, adjust=False).mean()

        rs = roll_up / roll_down.replace(0, np.nan)
        df["rsi"] = 100.0 - (100.0 / (1.0 + rs))
        df["rsi"] = df["rsi"].fillna(50.0)

        # Chronological state-machine loop to determine signals
        signals = np.zeros(len(df))
        current_state = 0.0  # 0: flat, 1: long, -1: short
        
        rsi_values = df["rsi"].values
        for t in range(len(df)):
            if t < self.window:
                signals[t] = 0.0
                continue

            rsi = rsi_values[t]

            if current_state == 0.0:
                if rsi < self.oversold:
                    current_state = 1.0
                elif not self.long_only and rsi > self.overbought:
                    current_state = -1.0
            elif current_state == 1.0:
                if rsi >= self.exit_level:
                    # Check if we should reverse immediately to short
                    if not self.long_only and rsi > self.overbought:
                        current_state = -1.0
                    else:
                        current_state = 0.0
            elif current_state == -1.0:
                if rsi <= self.exit_level:
                    # Check if we should reverse immediately to long
                    if rsi < self.oversold:
                        current_state = 1.0
                    else:
                        current_state = 0.0

            signals[t] = current_state

        return list(signals)

from typing import List

import numpy as np
import pandas as pd

from domain.models import Bar
from strat.base import BaseStrategy


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI mean-reversion.

    Enters long when RSI drops below ``oversold`` and exits when it reverts up
    through ``exit_level``. When ``long_only`` is False it also shorts above
    ``overbought`` and covers back at ``exit_level``. The first ``window`` bars
    are flat (RSI undefined during warm-up).
    """

    def __init__(
        self,
        window: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        exit_level: float = 50.0,
        long_only: bool = True,
    ):
        self.window = int(window)
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.exit_level = float(exit_level)
        self.long_only = long_only

    def _rsi(self, closes: pd.Series) -> pd.Series:
        delta = closes.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.rolling(window=self.window).mean()
        avg_loss = loss.rolling(window=self.window).mean()
        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
        # If there are no losses in the window, RSI saturates at 100.
        rsi = rsi.where(avg_loss > 0, 100.0)
        # Re-mask the warm-up region where the averages are undefined.
        rsi[avg_gain.isna() | avg_loss.isna()] = np.nan
        return rsi

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        closes = self._closes(bars)
        rsi = self._rsi(closes)

        signals: List[float] = []
        position = 0.0
        for value in rsi:
            if np.isnan(value):
                signals.append(0.0)
                continue

            if position == 0.0:
                if value < self.oversold:
                    position = 1.0
                elif (not self.long_only) and value > self.overbought:
                    position = -1.0
            elif position == 1.0:
                if value >= self.exit_level:
                    position = 0.0
            elif position == -1.0:
                if value <= self.exit_level:
                    position = 0.0

            signals.append(position)

        return signals

from typing import List

import numpy as np

from domain.models import Bar
from strat.base import BaseStrategy


class BollingerBandsStrategy(BaseStrategy):
    """Bollinger Bands breakout.

    Goes long (1.0) on a close above the upper band and, when ``long_only`` is
    False, short (-1.0) on a close below the lower band; a long-only run exits to
    flat (0.0) on a lower-band breach. The position is held between bands. The
    first ``window - 1`` bars are flat (bands undefined during warm-up).
    """

    def __init__(self, window: int = 20, num_std: float = 2.0, long_only: bool = True):
        self.window = int(window)
        self.num_std = float(num_std)
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        closes = self._closes(bars)
        mid = closes.rolling(window=self.window).mean()
        std = closes.rolling(window=self.window).std()
        upper = mid + self.num_std * std
        lower = mid - self.num_std * std

        signals: List[float] = []
        position = 0.0
        for i in range(len(closes)):
            if np.isnan(upper.iloc[i]) or np.isnan(lower.iloc[i]):
                signals.append(0.0)
                continue

            price = closes.iloc[i]
            if price > upper.iloc[i]:
                position = 1.0
            elif price < lower.iloc[i]:
                position = -1.0 if not self.long_only else 0.0
            # otherwise hold the existing position

            signals.append(position)

        return signals

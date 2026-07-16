from typing import List

import numpy as np

from domain.models import Bar
from strat.base import BaseStrategy


class EMACrossoverStrategy(BaseStrategy):
    """Exponential Moving Average crossover.

    Long (1.0) when the fast EMA is above the slow EMA; otherwise flat (0.0) or
    short (-1.0) when ``long_only`` is False. The first ``slow_window - 1`` bars
    are held flat as a warm-up so the slow EMA can stabilise.
    """

    def __init__(self, fast_window: int = 10, slow_window: int = 50, long_only: bool = True):
        self.fast_window = int(fast_window)
        self.slow_window = int(slow_window)
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        closes = self._closes(bars)
        fast = closes.ewm(span=self.fast_window, adjust=False).mean()
        slow = closes.ewm(span=self.slow_window, adjust=False).mean()

        signals = np.where(fast > slow, 1.0, self._flat_value())
        warm = max(self.slow_window - 1, 0)
        signals[:warm] = 0.0
        return [float(s) for s in signals]

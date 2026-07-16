from typing import List, Optional

import numpy as np

from domain.models import Bar
from strat.base import BaseStrategy


class MACDStrategy(BaseStrategy):
    """MACD trend following.

    Long (1.0) when the MACD histogram (MACD line minus signal line) is positive;
    otherwise flat (0.0) or short (-1.0) when ``long_only`` is False.

    Accepts both the ``*_window`` names used by the test-suite and the ``*_period``
    names used by cli.py, so a single class satisfies both callers.
    """

    def __init__(
        self,
        fast_window: int = 12,
        slow_window: int = 26,
        signal_window: int = 9,
        long_only: bool = True,
        fast_period: Optional[int] = None,
        slow_period: Optional[int] = None,
        signal_period: Optional[int] = None,
    ):
        self.fast_window = int(fast_period if fast_period is not None else fast_window)
        self.slow_window = int(slow_period if slow_period is not None else slow_window)
        self.signal_window = int(signal_period if signal_period is not None else signal_window)
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        closes = self._closes(bars)
        ema_fast = closes.ewm(span=self.fast_window, adjust=False).mean()
        ema_slow = closes.ewm(span=self.slow_window, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.signal_window, adjust=False).mean()
        histogram = macd_line - signal_line

        signals = np.where(histogram > 0, 1.0, self._flat_value())
        warm = max(self.slow_window + self.signal_window, 0)
        signals[:warm] = 0.0
        return [float(s) for s in signals]

from typing import List

from domain.models import Bar
from strat.base import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """Always fully invested: emits a long signal (1.0) on every bar."""

    def __init__(self):
        self.long_only = True

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        return [1.0] * len(bars)

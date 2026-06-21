from typing import List
from domain.models import Bar
from strat.base import BaseStrategy


class BuyAndHoldStrategy(BaseStrategy):
    """
    Baseline strategy that buys on day 1 and holds forever.
    """

    def __init__(self, long_only: bool = True):
        # long_only is included to maintain signature uniformity across strategies
        self.long_only = long_only

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates Buy signals (1.0) for every bar.
        """
        return [1.0] * len(bars)

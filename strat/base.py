from abc import ABC, abstractmethod
from typing import List
from domain.interfaces import IStrategy
from domain.models import Bar


class BaseStrategy(IStrategy, ABC):
    """
    Abstract Base Class for defining trading strategies.
    """

    @abstractmethod
    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Takes a list of clean domain Bar objects and returns a list of float signals.
        
        Args:
            bars: List of Bar domain entities.
            
        Returns:
            List[float]: A list of signals aligned with the bars (1.0 for Buy, -1.0 for Sell, 0.0 for Flat).
        """
        pass


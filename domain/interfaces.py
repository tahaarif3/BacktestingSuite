from abc import ABC, abstractmethod
from typing import List
from domain.models import Bar


class IStrategy(ABC):
    @abstractmethod
    def generate_signals(self, bars: List[Bar]) -> List[float]:
        """
        Generates trading signals for a sequence of bars.
        Returns a list of float signals, aligned with the input bars.
        """
        pass


class IPositionSizer(ABC):
    @abstractmethod
    def size_position(self, signal: float, price: float, current_equity: float, current_bar: Bar) -> float:
        """
        Calculates the target position (in shares) dynamically for a single bar.
        """
        pass


class IExecutionModel(ABC):
    @abstractmethod
    def calculate_slippage(self, price: float, shares: float) -> float:
        """Calculates slippage cost for a trade of a given size at a given price."""
        pass

    @abstractmethod
    def calculate_commission(self, price: float, shares: float) -> float:
        """Calculates commission cost for a trade of a given size at a given price."""
        pass


class IMarketDataRepository(ABC):
    @abstractmethod
    def get_bars(self) -> List[Bar]:
        """
        Retrieves a sequence of clean domain Bar objects.
        """
        pass


"""Reconstructed strategy package.

The original private strategies were gitignored and absent from the clone; these
are faithful reconstructions of the six standard strategies plus a GP loader.
Drop private implementations back into this folder to override them.
"""

from strat.base import BaseStrategy
from strat.buy_and_hold import BuyAndHoldStrategy
from strat.sma_crossover import SMACrossoverStrategy
from strat.ema_crossover import EMACrossoverStrategy
from strat.rsi_mean_reversion import RSIMeanReversionStrategy
from strat.bollinger_bands import BollingerBandsStrategy
from strat.macd import MACDStrategy
from strat.genetic_programming import GeneticProgrammingStrategy

__all__ = [
    "BaseStrategy",
    "BuyAndHoldStrategy",
    "SMACrossoverStrategy",
    "EMACrossoverStrategy",
    "RSIMeanReversionStrategy",
    "BollingerBandsStrategy",
    "MACDStrategy",
    "GeneticProgrammingStrategy",
]

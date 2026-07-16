"""Base class for reconstructed strategies.

NOTE: The original `strat/` package is gitignored ("Secret and private trading
strategies") and was not present in the clone. These implementations of the six
standard, publicly-documented strategies were reconstructed to match the exact
contract exercised by test/test_strategies.py and cli.py (parameter names,
warm-up lengths, and signal semantics). Drop your private versions back into this
folder to override them; the registry picks up whatever classes are exported here.
"""

from typing import List

import numpy as np
import pandas as pd

from domain.interfaces import IStrategy
from domain.models import Bar


class BaseStrategy(IStrategy):
    """Common helpers for signal-generating strategies.

    Signal convention (aligned 1:1 with the input bars):
      * ``1.0``  -> long
      * ``0.0``  -> flat (also used for the warm-up period)
      * ``-1.0`` -> short (only emitted when ``long_only`` is False)
    """

    long_only: bool = True

    @staticmethod
    def _closes(bars: List[Bar]) -> pd.Series:
        return pd.Series([b.close for b in bars], dtype=float)

    def _flat_value(self) -> float:
        """Value used when the strategy is not long: flat (long-only) or short."""
        return 0.0 if self.long_only else -1.0

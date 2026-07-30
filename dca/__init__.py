"""Dollar-cost-averaging / bankroll-management backtester for a single index
(SPY by default).

Tests different contribution schedules and buy/sell rules against a plain
$100/month baseline, lump-sum, and buy-and-hold — to answer "does timing my
contributions around a moving average actually beat just buying every month?".
"""

from dca.engine import DcaConfig, run_dca, DcaResult

__all__ = ["DcaConfig", "run_dca", "DcaResult"]

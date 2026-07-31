"""Market-timing (buy AND sell) backtester for a single index.

Unlike the DCA engine (contributions, buy-only), this simulates a lump-sum
portfolio whose *exposure* to the index is driven by a rule — a moving-average
regime, momentum, seasonality, volatility target, or leverage — rebalanced with
realistic trading cost, idle-cash yield, and margin interest. Used to compare
timing strategies against buy-and-hold.
"""

from timing.engine import TimingConfig, run_timing, TimingResult

__all__ = ["TimingConfig", "run_timing", "TimingResult"]

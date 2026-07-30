"""Automated multi-position portfolio backtester.

An event-driven engine that scans a universe each day, ranks competing
breakout signals, opens several simultaneous positions under risk / capital /
sector limits, models next-open execution with slippage + stop-gaps, and tracks
portfolio equity with a daily accounting-reconciliation assertion — all without
look-ahead bias.

Implements the market-filter + relative-strength + breakout rules as a
standalone portfolio strategy (distinct from the single-instrument RS-Breakout
`IStrategy`, though the rules line up).

Honest data limits (free data): the universe is a fixed watchlist (survivorship
biased — removed/delisted names are absent), sectors come from a static map, and
there are no real option chains (the options mapping prices synthetically).
"""

from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.engine import run_portfolio_backtest, PortfolioBacktestResult

__all__ = ["PortfolioBacktestConfig", "run_portfolio_backtest", "PortfolioBacktestResult"]

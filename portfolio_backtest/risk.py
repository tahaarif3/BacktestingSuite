"""Position sizing: risk-per-trade, capped by max position value and cash."""

from __future__ import annotations

import math

from portfolio_backtest.config import PortfolioBacktestConfig


def size_position(
    equity: float, cash: float, entry_price: float, stop_price: float, cfg: PortfolioBacktestConfig
) -> int:
    """Shares to trade = min(risk-based, capital-cap, affordable). 0 if the
    stop isn't below entry (no definable risk) or nothing is affordable."""
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0 or entry_price <= 0:
        return 0
    dollar_risk = equity * cfg.risk_per_trade
    risk_shares = dollar_risk / risk_per_share
    cap_shares = (equity * cfg.max_position_pct) / entry_price
    cash_shares = cash / entry_price
    shares = min(risk_shares, cap_shares, cash_shares)
    if cfg.whole_shares:
        shares = math.floor(shares)
    return int(max(shares, 0)) if cfg.whole_shares else max(shares, 0.0)

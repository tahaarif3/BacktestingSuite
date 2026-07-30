"""Realistic-ish fills: slippage on both sides, commissions, and stop-gaps."""

from __future__ import annotations

from typing import Optional

from portfolio_backtest.config import PortfolioBacktestConfig


def entry_fill(next_open: float, cfg: PortfolioBacktestConfig) -> float:
    return next_open * (1.0 + cfg.slippage_pct)


def exit_fill(price: float, cfg: PortfolioBacktestConfig) -> float:
    return price * (1.0 - cfg.slippage_pct)


def commission(shares: float, cfg: PortfolioBacktestConfig) -> float:
    if shares <= 0:
        return 0.0
    base = cfg.commission_per_share * shares + cfg.commission_per_order
    if cfg.min_commission > 0:
        base = max(base, cfg.min_commission)
    return float(base)


def stop_exit_price(day_open: float, day_low: float, stop: float, cfg: PortfolioBacktestConfig) -> Optional[float]:
    """If the day's low reached the stop, return the fill price (with slippage).
    Models an overnight gap through the stop: if the open is already below the
    stop, you fill at the open, not the (better) stop level."""
    if day_low <= stop:
        raw = stop if day_open >= stop else day_open
        return exit_fill(raw, cfg)
    return None

"""Multi-position portfolio accounting with a daily reconciliation identity.

Reconciliation (asserted every bar):
    equity == initial_capital + realized_gross + unrealized_gross - cum_costs
where realized/unrealized are gross of costs and every commission/slippage
dollar lands in ``cum_costs`` (slippage is embedded in fill prices, so it shows
up through realized/unrealized rather than cum_costs — see note in `close`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

RECON_EPS = 1e-3


@dataclass
class Position:
    ticker: str
    sector: str
    entry_date: datetime
    entry_price: float          # fill price (incl. slippage)
    shares: float
    initial_stop: float
    current_stop: float
    score: float
    entry_commission: float
    mfe: float = 0.0            # max favorable excursion ($, peak unrealized)
    mae: float = 0.0            # max adverse excursion ($, worst unrealized)

    def unrealized(self, price: float) -> float:
        return self.shares * (price - self.entry_price)

    def update_excursion(self, high: float, low: float) -> None:
        self.mfe = max(self.mfe, self.shares * (high - self.entry_price))
        self.mae = min(self.mae, self.shares * (low - self.entry_price))


@dataclass
class ClosedTrade:
    ticker: str
    sector: str
    signal_date: Optional[datetime]
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    shares: float
    initial_stop: float
    exit_reason: str
    gross_pnl: float
    commission: float
    slippage: float
    net_pnl: float
    return_pct: float
    r_multiple: float
    holding_days: int
    mfe: float
    mae: float


class Portfolio:
    def __init__(self, initial_capital: float):
        self.initial_capital = float(initial_capital)
        self.cash = float(initial_capital)
        self.positions: Dict[str, Position] = {}
        self.closed: List[ClosedTrade] = []
        self.realized_gross = 0.0
        self.cum_costs = 0.0        # commissions only (slippage is in fill prices)
        self.sector_counts: Dict[str, int] = {}

    # --- queries ---
    def holdings_value(self, prices: Dict[str, float]) -> float:
        return sum(p.shares * prices[p.ticker] for p in self.positions.values() if p.ticker in prices)

    def equity(self, prices: Dict[str, float]) -> float:
        return self.cash + self.holdings_value(prices)

    def unrealized_gross(self, prices: Dict[str, float]) -> float:
        return sum(p.unrealized(prices[p.ticker]) for p in self.positions.values() if p.ticker in prices)

    def sector_count(self, sector: str) -> int:
        return self.sector_counts.get(sector, 0)

    # --- mutations ---
    def open(self, pos: Position) -> None:
        notional = pos.shares * pos.entry_price
        self.cash -= notional + pos.entry_commission
        self.cum_costs += pos.entry_commission
        self.positions[pos.ticker] = pos
        self.sector_counts[pos.sector] = self.sector_counts.get(pos.sector, 0) + 1

    def close(self, ticker: str, exit_date: datetime, exit_price: float, commission: float,
              reason: str, signal_date: Optional[datetime], slippage_dollars: float) -> ClosedTrade:
        pos = self.positions.pop(ticker)
        self.sector_counts[pos.sector] -= 1
        proceeds = pos.shares * exit_price
        self.cash += proceeds - commission
        gross = pos.shares * (exit_price - pos.entry_price)
        self.realized_gross += gross
        self.cum_costs += commission
        net = gross - pos.entry_commission - commission
        risk_per_share = pos.entry_price - pos.initial_stop
        r = (exit_price - pos.entry_price) / risk_per_share if risk_per_share > 0 else 0.0
        cost_basis = pos.shares * pos.entry_price
        trade = ClosedTrade(
            ticker=ticker, sector=pos.sector, signal_date=signal_date, entry_date=pos.entry_date,
            entry_price=pos.entry_price, exit_date=exit_date, exit_price=exit_price, shares=pos.shares,
            initial_stop=pos.initial_stop, exit_reason=reason, gross_pnl=gross,
            commission=pos.entry_commission + commission, slippage=slippage_dollars, net_pnl=net,
            return_pct=(net / cost_basis) if cost_basis > 0 else 0.0, r_multiple=r,
            holding_days=(exit_date - pos.entry_date).days, mfe=pos.mfe, mae=pos.mae,
        )
        self.closed.append(trade)
        return trade

    def reconcile(self, prices: Dict[str, float]) -> None:
        eq = self.equity(prices)
        identity = self.initial_capital + self.realized_gross + self.unrealized_gross(prices) - self.cum_costs
        if abs(eq - identity) > max(RECON_EPS, abs(eq) * 1e-9):
            raise AssertionError(
                f"Portfolio accounting broke: equity {eq:.4f} != identity {identity:.4f} "
                f"(diff {eq - identity:.6f})"
            )

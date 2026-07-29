"""Options marking, P&L, and a Portfolio-compatible result wrapper.

``mark_structure`` reprices every leg with Black-Scholes at the current bar
(decremented time-to-expiry, current IV) and aggregates greeks. ``OptionsPortfolio``
exposes the same ``.data`` DataFrame (with ``equity`` / ``active_position`` /
``close``) and ``.equity_curve`` Series contract that ``analytics.PerformanceMetrics``
already consumes — so Sharpe/Sortino/drawdown/CAGR all work unchanged.

``reconstruct_option_trades`` turns closed structure round-trips into a trade
frame whose ``pnl_usd`` column drives win-rate / profit-factor, replacing the
share-based ``extract_trades`` (which cannot represent a multi-leg spread).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

from domain.models import Bar
from options.instruments import OptionStructure
from options.pricing import CONTRACT_MULTIPLIER, TRADING_DAYS, bs_greeks, bs_price


def leg_time_to_expiry(expiry_index: int, bar_index: int) -> float:
    """Trading-day years remaining for a leg at ``bar_index`` (>=0)."""
    return max(expiry_index - bar_index, 0) / TRADING_DAYS


def mark_structure(
    structure: OptionStructure,
    spot: float,
    bar_index: int,
    r: float,
    sigma: float,
) -> Dict[str, Any]:
    """Mark a whole structure at ``bar_index``.

    Returns per-structure dollar ``value`` (signed mark-to-market of holdings),
    aggregate position ``greeks`` (already ×multiplier×contracts), and per-leg
    marks for the UI.
    """
    value = 0.0
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    leg_marks: List[Dict[str, Any]] = []
    for leg in structure.legs:
        T = leg_time_to_expiry(leg.expiry_index, bar_index)
        price = bs_price(spot, leg.strike, T, r, sigma, leg.kind)
        g = bs_greeks(spot, leg.strike, T, r, sigma, leg.kind)
        contrib = leg.quantity * price * CONTRACT_MULTIPLIER
        value += contrib
        for k in net:
            net[k] += leg.quantity * g[k] * CONTRACT_MULTIPLIER
        leg_marks.append({
            "kind": leg.kind,
            "strike": leg.strike,
            "quantity": leg.quantity,
            "dte_bars": max(leg.expiry_index - bar_index, 0),
            "mark": price,
            "value": contrib,
            "delta": g["delta"],
            "gamma": g["gamma"],
            "theta": g["theta"],
            "vega": g["vega"],
        })
    return {"value": value, "greeks": net, "legs": leg_marks}


@dataclass
class ClosedOptionTrade:
    structure_id: str
    structure_type: str
    contracts: int
    open_index: int
    close_index: int
    open_timestamp: datetime
    close_timestamp: datetime
    entry_cash: float        # net cash at open (credit +, debit -), before costs
    exit_cash: float         # cash from closing (mark value returned)
    costs: float             # total slippage+commission over open+close
    pnl_usd: float           # realized P&L incl. costs
    max_risk: float          # |max loss| at open (for pnl% denominator)
    reason: str              # "close" | "expiry"


def reconstruct_option_trades(closed: Sequence[ClosedOptionTrade]) -> pd.DataFrame:
    """Round-trip trade frame. Column names align with what the frontend
    ``OptionTradeTable`` and ``PerformanceMetrics`` expect (``pnl_usd``)."""
    if not closed:
        return pd.DataFrame(
            columns=[
                "entry_time", "exit_time", "structure", "contracts",
                "entry_cash", "exit_cash", "pnl_usd", "pnl_pct", "max_risk", "reason",
            ]
        )
    rows = []
    for t in closed:
        denom = t.max_risk if t.max_risk > 1e-9 else abs(t.entry_cash) if abs(t.entry_cash) > 1e-9 else 1.0
        rows.append({
            "entry_time": t.open_timestamp,
            "exit_time": t.close_timestamp,
            "structure": t.structure_type,
            "contracts": t.contracts,
            "entry_cash": t.entry_cash,
            "exit_cash": t.exit_cash,
            "pnl_usd": t.pnl_usd,
            "pnl_pct": t.pnl_usd / denom,
            "max_risk": t.max_risk,
            "reason": t.reason,
        })
    return pd.DataFrame(rows)


class OptionsPortfolio:
    """Portfolio-shaped result for the options path.

    Builds a DataFrame with the columns ``analytics`` reads (``equity``,
    ``active_position``, ``open``/``close`` for the benchmark) and an
    ``equity_curve`` Series, so ``PerformanceMetrics.get_advanced_summary`` and
    ``get_benchmark_equity`` work with no shim.
    """

    def __init__(
        self,
        bars: Sequence[Bar],
        cash: Sequence[float],
        equity_curve: Sequence[float],
        open_structure_counts: Sequence[float],
        net_delta: Optional[Sequence[float]] = None,
    ):
        n = len(bars)
        timestamps = [b.timestamp for b in bars]
        self.equity_curve = pd.Series(list(equity_curve), index=timestamps)
        self.cash = pd.Series(list(cash), index=timestamps)
        df = pd.DataFrame({
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "active_position": list(open_structure_counts),
            "net_delta": list(net_delta) if net_delta is not None else [0.0] * n,
            "cash": list(cash),
            "equity": list(equity_curve),
        }, index=timestamps)
        df.index.name = "timestamp"
        self.data = df

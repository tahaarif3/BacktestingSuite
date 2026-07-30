"""Pure multi-symbol options portfolio ledger.

A shared cash account across a watchlist of symbols, all on ONE date axis (the
replay clock). At each bar it settles expiries, fills orders decided on the
previous bar, and marks every open structure across every symbol — reusing the
symbol-agnostic options primitives (``build_structure`` / ``mark_structure``).

Same discipline as the single-symbol ledgers: decision on bar ``d`` fills at
``d+1``, recompute-from-order-list (pure, orders never mutated), so undo/rewind
is just "recompute with fewer orders". Equity is marked on each symbol's close;
options are European, cash-settled at intrinsic on expiry (no early assignment).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from backtest.execution import ExecutionModel
from options.instruments import OptionStructure
from options.pricing import CONTRACT_MULTIPLIER
from options.portfolio import mark_structure
from options.structures import StructureSpec, build_structure


@dataclass(frozen=True)
class PortfolioOptionOrder:
    """An options order tagged with the symbol it applies to."""

    id: str
    symbol: str
    bar_index: int
    action: str                       # "open" | "close"
    structure_type: str = "bull_put_spread"
    selection: str = "delta"
    short_delta: float = 0.30
    pct_otm: float = 0.05
    width: float = 5.0
    strikes: Optional[List[float]] = None
    dte_bars: int = 30
    contracts: int = 1
    grid_spacing: float = 5.0
    target_structure_id: Optional[str] = None
    note: str = ""
    placed_at: str = ""

    def to_spec(self) -> StructureSpec:
        return StructureSpec(
            structure_type=self.structure_type, selection=self.selection,
            short_delta=self.short_delta, pct_otm=self.pct_otm, width=self.width,
            strikes=list(self.strikes) if self.strikes else None,
            dte_bars=self.dte_bars, contracts=self.contracts, grid_spacing=self.grid_spacing,
        )


@dataclass(frozen=True)
class PortfolioFill:
    order_id: str
    symbol: str
    structure_id: str
    decision_index: int
    fill_index: int
    timestamp: Optional[datetime]
    action: str                # "open" | "close" | "expiry"
    structure_type: str
    spot: float
    net_cash: float
    costs: float
    cash_after: float
    realized_pnl: float


@dataclass
class PortfolioClosedTrade:
    symbol: str
    structure_id: str
    structure_type: str
    contracts: int
    open_index: int
    close_index: int
    open_timestamp: Optional[datetime]
    close_timestamp: Optional[datetime]
    entry_cash: float
    exit_cash: float
    costs: float
    pnl_usd: float
    max_risk: float
    reason: str


@dataclass
class _OpenState:
    structure: OptionStructure
    symbol: str
    entry_cash: float
    open_costs: float
    max_risk: float
    open_index: int
    open_timestamp: Optional[datetime]


@dataclass
class PortfolioLedgerResult:
    dates: List[datetime]
    equity_curve: List[float]
    cash_curve: List[float]
    fills: List[PortfolioFill]
    closed_trades: List[PortfolioClosedTrade]
    open_by_symbol: Dict[str, List[OptionStructure]]
    final_cash: float
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float
    max_risk: float
    min_cash: float
    warnings: List[str] = field(default_factory=list)


def _leg_costs_from_marks(exec_model: ExecutionModel, marked_legs) -> float:
    total = 0.0
    for lm in marked_legs:
        shares = lm["quantity"] * CONTRACT_MULTIPLIER
        total += exec_model.calculate_slippage(lm["mark"], shares)
        total += exec_model.calculate_commission(lm["mark"], shares)
    return total


def build_portfolio_options_ledger(
    *,
    dates: Sequence[datetime],
    closes: Dict[str, List[Optional[float]]],
    opens: Dict[str, List[Optional[float]]],
    iv: Dict[str, List[float]],
    orders: Sequence[PortfolioOptionOrder],
    upto_index: int,
    capital: float,
    exec_model: ExecutionModel,
    timing: str = "next_open",
    risk_free_rate: float = 0.04,
    margin_policy: str = "defined_risk",
    annualization: float = 252.0,
) -> PortfolioLedgerResult:
    n_axis = len(dates)
    if n_axis == 0:
        raise ValueError("Empty date axis.")
    n = min(max(upto_index + 1, 0), n_axis)
    if n <= 0:
        raise ValueError("upto_index must be >= 0.")
    r = risk_free_rate
    symbols = list(closes.keys())

    orders_by_decision: Dict[int, List[PortfolioOptionOrder]] = defaultdict(list)
    for o in orders:
        orders_by_decision[o.bar_index].append(o)

    cash = capital
    open_states: Dict[str, Dict[str, _OpenState]] = {s: {} for s in symbols}
    closed: List[PortfolioClosedTrade] = []
    fills: List[PortfolioFill] = []
    warnings: List[str] = []

    equity_curve = [capital] * n
    cash_curve = [capital] * n
    realized_total = 0.0
    min_cash = capital

    def spot_for_fill(sym: str, t: int) -> Optional[float]:
        arr = opens[sym] if timing == "next_open" else closes[sym]
        return arr[t] if t < len(arr) else None

    for t in range(n):
        ts = dates[t]

        # 1) settle expiries at this bar (per symbol, at its close).
        for sym in symbols:
            spot_c = closes[sym][t]
            if spot_c is None:
                continue
            for sid in [s for s, st in open_states[sym].items() if st.structure.expiry_index <= t]:
                st = open_states[sym].pop(sid)
                marked = mark_structure(st.structure, spot_c, t, r, iv[sym][t], annualization)
                exit_value = marked["value"]
                cash += exit_value
                realized = st.entry_cash + exit_value - st.open_costs
                realized_total += realized
                closed.append(PortfolioClosedTrade(
                    symbol=sym, structure_id=sid, structure_type=st.structure.structure_type,
                    contracts=st.structure.contracts, open_index=st.open_index, close_index=t,
                    open_timestamp=st.open_timestamp, close_timestamp=ts, entry_cash=st.entry_cash,
                    exit_cash=exit_value, costs=st.open_costs, pnl_usd=realized,
                    max_risk=st.max_risk, reason="expiry",
                ))
                fills.append(PortfolioFill(
                    order_id="", symbol=sym, structure_id=sid, decision_index=t, fill_index=t,
                    timestamp=ts, action="expiry", structure_type=st.structure.structure_type,
                    spot=spot_c, net_cash=exit_value, costs=0.0, cash_after=cash, realized_pnl=realized,
                ))

        # 2) fills for orders decided on bar t-1.
        if t >= 1:
            for order in orders_by_decision.get(t - 1, []):
                sym = order.symbol
                if sym not in open_states:
                    warnings.append(f"order for unknown symbol {sym}")
                    continue
                spot = spot_for_fill(sym, t)
                if spot is None:
                    warnings.append(f"{sym}: no price at fill bar {t}; order skipped")
                    continue
                if order.action == "open":
                    structure = build_structure(order.to_spec(), S=spot, sigma=iv[sym][t],
                                                r=r, open_index=t, structure_id=order.id,
                                                annualization=annualization)
                    entry_cash = structure.net_cash_at_open
                    marked = mark_structure(structure, spot, t, r, iv[sym][t], annualization)
                    costs = _leg_costs_from_marks(exec_model, marked["legs"])
                    cash += entry_cash - costs
                    ml = structure.max_loss
                    max_risk = abs(ml) if ml != float("-inf") else float("inf")
                    open_states[sym][order.id] = _OpenState(
                        structure=structure, symbol=sym, entry_cash=entry_cash,
                        open_costs=costs, max_risk=max_risk, open_index=t, open_timestamp=ts,
                    )
                    fills.append(PortfolioFill(
                        order_id=order.id, symbol=sym, structure_id=order.id, decision_index=t - 1,
                        fill_index=t, timestamp=ts, action="open",
                        structure_type=structure.structure_type, spot=spot, net_cash=entry_cash,
                        costs=costs, cash_after=cash, realized_pnl=0.0,
                    ))
                else:  # close
                    sid = order.target_structure_id
                    st = open_states[sym].pop(sid, None)
                    if st is None:
                        warnings.append(f"{sym}: close for unknown/closed structure {sid}")
                        continue
                    marked = mark_structure(st.structure, spot, t, r, iv[sym][t], annualization)
                    exit_value = marked["value"]
                    costs = _leg_costs_from_marks(exec_model, marked["legs"])
                    cash += exit_value - costs
                    realized = st.entry_cash + exit_value - st.open_costs - costs
                    realized_total += realized
                    closed.append(PortfolioClosedTrade(
                        symbol=sym, structure_id=sid, structure_type=st.structure.structure_type,
                        contracts=st.structure.contracts, open_index=st.open_index, close_index=t,
                        open_timestamp=st.open_timestamp, close_timestamp=ts, entry_cash=st.entry_cash,
                        exit_cash=exit_value, costs=st.open_costs + costs, pnl_usd=realized,
                        max_risk=st.max_risk, reason="close",
                    ))
                    fills.append(PortfolioFill(
                        order_id=order.id, symbol=sym, structure_id=sid, decision_index=t - 1,
                        fill_index=t, timestamp=ts, action="close",
                        structure_type=st.structure.structure_type, spot=spot, net_cash=exit_value,
                        costs=costs, cash_after=cash, realized_pnl=realized,
                    ))

        # 3) mark every open structure across all symbols at this bar's close.
        holdings = 0.0
        for sym in symbols:
            spot_c = closes[sym][t]
            if spot_c is None:
                continue
            for st in open_states[sym].values():
                holdings += mark_structure(st.structure, spot_c, t, r, iv[sym][t], annualization)["value"]
        equity = cash + holdings
        cash_curve[t] = cash
        equity_curve[t] = equity
        min_cash = min(min_cash, cash)

    # unrealized (if flattened now at the last bar's close) + total open risk.
    unrealized = 0.0
    total_max_risk = 0.0
    open_by_symbol: Dict[str, List[OptionStructure]] = {}
    for sym in symbols:
        spot_c = closes[sym][n - 1]
        alive = list(open_states[sym].values())
        if alive:
            open_by_symbol[sym] = [st.structure for st in alive]
        for st in alive:
            if spot_c is not None:
                marked = mark_structure(st.structure, spot_c, n - 1, r, iv[sym][n - 1], annualization)
                unrealized += st.entry_cash + marked["value"] - st.open_costs
            if st.max_risk != float("inf"):
                total_max_risk += st.max_risk

    return PortfolioLedgerResult(
        dates=list(dates[:n]),
        equity_curve=equity_curve,
        cash_curve=cash_curve,
        fills=fills,
        closed_trades=closed,
        open_by_symbol=open_by_symbol,
        final_cash=cash,
        final_equity=equity_curve[-1] if n else capital,
        realized_pnl=realized_total,
        unrealized_pnl=unrealized,
        max_risk=total_max_risk,
        min_cash=min_cash,
        warnings=warnings,
    )

"""Pure options ledger — the options-mode mirror of ``replay_ledger.build_ledger``.

Recomputes the full account (cash, open structures, equity curve, realized P&L)
from a list of :class:`OptionOrder`s, up to a given bar. Same discipline as the
equity ledger: decision on bar ``d`` fills at ``d+1``, same ``ExecutionModel``,
same ``timing`` semantics, pure (never mutates ``orders``), so undo/rewind is
just "recompute with fewer orders".

Auto-settles each structure at intrinsic on its expiry bar (European, cash-settled,
no early assignment — v1).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from domain.models import Bar
from backtest.execution import ExecutionModel
from options.instruments import OptionStructure
from options.pricing import CONTRACT_MULTIPLIER
from options.portfolio import ClosedOptionTrade, OptionsPortfolio, mark_structure
from options.structures import StructureSpec, build_structure
from options.volatility import iv_for_bar, realized_vol_series

TRADE_EPS = 1e-8


@dataclass(frozen=True)
class OptionOrder:
    """A user (or algo) options order. ``bar_index`` is the bar the user was
    looking at; the order fills at ``bar_index + 1``."""

    id: str
    bar_index: int
    action: str                       # "open" | "close"
    structure_type: str = "bear_call_spread"
    selection: str = "delta"          # "delta" | "pct_otm" | "absolute"
    short_delta: float = 0.30
    pct_otm: float = 0.05
    width: float = 5.0
    strikes: Optional[List[float]] = None
    dte_bars: int = 30
    contracts: int = 1
    grid_spacing: float = 5.0
    target_structure_id: Optional[str] = None   # for "close"
    note: str = ""
    placed_at: str = ""

    def to_spec(self) -> StructureSpec:
        return StructureSpec(
            structure_type=self.structure_type,
            selection=self.selection,
            short_delta=self.short_delta,
            pct_otm=self.pct_otm,
            width=self.width,
            strikes=list(self.strikes) if self.strikes else None,
            dte_bars=self.dte_bars,
            contracts=self.contracts,
            grid_spacing=self.grid_spacing,
        )


@dataclass(frozen=True)
class OptionFill:
    order_id: str
    structure_id: str
    decision_index: int
    fill_index: int
    timestamp: datetime
    action: str                # "open" | "close" | "expiry"
    structure_type: str
    spot: float
    net_cash: float            # signed cash effect (before costs) of this fill
    costs: float
    cash_after: float
    equity_after: float
    realized_pnl: float        # for close/expiry; 0 on open


@dataclass
class OptionsLedgerResult:
    portfolio: OptionsPortfolio
    fills: List[OptionFill]
    closed_trades: List[ClosedOptionTrade]
    open_structures: List[OptionStructure]
    final_cash: float
    final_equity: float
    realized_pnl: float
    unrealized_pnl: float
    max_risk: float
    min_cash: float
    warnings: List[str] = field(default_factory=list)


@dataclass
class _OpenState:
    structure: OptionStructure
    entry_cash: float          # net cash received(+)/paid(-) at open, before costs
    open_costs: float
    max_risk: float
    open_index: int
    open_timestamp: datetime


def _leg_costs(exec_model: ExecutionModel, structure: OptionStructure, price_lookup) -> float:
    """Slippage+commission across legs, using each leg's mark as the price and
    qty×multiplier as the share count (keeps parity with the equity cost model)."""
    total = 0.0
    for leg in structure.legs:
        px = price_lookup(leg)
        shares = leg.quantity * CONTRACT_MULTIPLIER
        total += exec_model.calculate_slippage(px, shares)
        total += exec_model.calculate_commission(px, shares)
    return total


def build_iv_series(
    bars: Sequence[Bar],
    *,
    iv_window: int = 20,
    iv_multiplier: float = 1.0,
    iv_override: Optional[float] = None,
    iv_floor: float = 0.05,
    iv_cap: float = 3.0,
    annualization: float = 252.0,
) -> List[float]:
    closes = [b.close for b in bars]
    rv = realized_vol_series(closes, window=iv_window, annualization=annualization)
    return [
        iv_for_bar(v, iv_multiplier=iv_multiplier, iv_override=iv_override,
                   iv_floor=iv_floor, iv_cap=iv_cap)
        for v in rv
    ]


def build_options_ledger(
    bars: Sequence[Bar],
    orders: Sequence[OptionOrder],
    *,
    upto_index: int,
    capital: float,
    exec_model: ExecutionModel,
    timing: str = "next_open",
    risk_free_rate: float = 0.04,
    iv_window: int = 20,
    iv_multiplier: float = 1.0,
    iv_override: Optional[float] = None,
    iv_floor: float = 0.05,
    iv_cap: float = 3.0,
    margin_policy: str = "defined_risk",
) -> OptionsLedgerResult:
    if not bars:
        raise ValueError("Cannot build an options ledger on empty data.")
    n = min(max(upto_index + 1, 0), len(bars))
    if n <= 0:
        raise ValueError("upto_index must be >= 0.")

    iv = build_iv_series(
        bars, iv_window=iv_window, iv_multiplier=iv_multiplier,
        iv_override=iv_override, iv_floor=iv_floor, iv_cap=iv_cap,
    )
    r = risk_free_rate

    orders_by_decision: Dict[int, List[OptionOrder]] = defaultdict(list)
    for o in orders:
        orders_by_decision[o.bar_index].append(o)

    cash = capital
    open_states: Dict[str, _OpenState] = {}
    closed: List[ClosedOptionTrade] = []
    fills: List[OptionFill] = []
    warnings: List[str] = []

    cash_list = [capital] * n
    equity_list = [capital] * n
    count_list = [0.0] * n
    delta_list = [0.0] * n
    realized_total = 0.0
    min_cash = capital

    def spot_at(t: int) -> float:
        bar = bars[t]
        return bar.open if timing == "next_open" else bar.close

    for t in range(n):
        current_bar = bars[t]

        # 1) settle any expiries occurring at this bar (use bar close as spot).
        for sid in [s for s, st in open_states.items() if st.structure.expiry_index <= t]:
            st = open_states.pop(sid)
            marked = mark_structure(st.structure, current_bar.close, t, r, iv[t])
            exit_value = marked["value"]           # cash returned by flattening
            cash += exit_value                     # no cost on cash-settled expiry
            realized = st.entry_cash + exit_value - st.open_costs
            realized_total += realized
            closed.append(ClosedOptionTrade(
                structure_id=sid, structure_type=st.structure.structure_type,
                contracts=st.structure.contracts, open_index=st.open_index,
                close_index=t, open_timestamp=st.open_timestamp,
                close_timestamp=current_bar.timestamp, entry_cash=st.entry_cash,
                exit_cash=exit_value, costs=st.open_costs, pnl_usd=realized,
                max_risk=st.max_risk, reason="expiry",
            ))
            fills.append(OptionFill(
                order_id="", structure_id=sid, decision_index=t, fill_index=t,
                timestamp=current_bar.timestamp, action="expiry",
                structure_type=st.structure.structure_type, spot=current_bar.close,
                net_cash=exit_value, costs=0.0, cash_after=cash,
                equity_after=0.0, realized_pnl=realized,
            ))

        # 2) process orders decided on bar t-1 (fill at t).
        if t >= 1:
            decision_index = t - 1
            spot = spot_at(t)
            for order in orders_by_decision.get(decision_index, []):
                if order.action == "open":
                    sid = order.id
                    structure = build_structure(
                        order.to_spec(), S=spot, sigma=iv[t], r=r,
                        open_index=t, structure_id=sid,
                    )
                    entry_cash = structure.net_cash_at_open
                    costs = _leg_costs(exec_model, structure, lambda leg: leg.entry_price)
                    cash += entry_cash - costs
                    ml = structure.max_loss
                    max_risk = abs(ml) if ml != float("-inf") else float("inf")
                    open_states[sid] = _OpenState(
                        structure=structure, entry_cash=entry_cash, open_costs=costs,
                        max_risk=max_risk, open_index=t, open_timestamp=current_bar.timestamp,
                    )
                    fills.append(OptionFill(
                        order_id=order.id, structure_id=sid, decision_index=decision_index,
                        fill_index=t, timestamp=current_bar.timestamp, action="open",
                        structure_type=structure.structure_type, spot=spot,
                        net_cash=entry_cash, costs=costs, cash_after=cash,
                        equity_after=0.0, realized_pnl=0.0,
                    ))
                elif order.action == "close":
                    sid = order.target_structure_id
                    st = open_states.pop(sid, None)
                    if st is None:
                        warnings.append(f"close order for unknown/closed structure {sid}")
                        continue
                    marked = mark_structure(st.structure, spot, t, r, iv[t])
                    exit_value = marked["value"]
                    # close costs from each leg's current mark
                    costs = 0.0
                    for lm in marked["legs"]:
                        shares = lm["quantity"] * CONTRACT_MULTIPLIER
                        costs += exec_model.calculate_slippage(lm["mark"], shares)
                        costs += exec_model.calculate_commission(lm["mark"], shares)
                    cash += exit_value - costs
                    realized = st.entry_cash + exit_value - st.open_costs - costs
                    realized_total += realized
                    closed.append(ClosedOptionTrade(
                        structure_id=sid, structure_type=st.structure.structure_type,
                        contracts=st.structure.contracts, open_index=st.open_index,
                        close_index=t, open_timestamp=st.open_timestamp,
                        close_timestamp=current_bar.timestamp, entry_cash=st.entry_cash,
                        exit_cash=exit_value, costs=st.open_costs + costs, pnl_usd=realized,
                        max_risk=st.max_risk, reason="close",
                    ))
                    fills.append(OptionFill(
                        order_id=order.id, structure_id=sid, decision_index=decision_index,
                        fill_index=t, timestamp=current_bar.timestamp, action="close",
                        structure_type=st.structure.structure_type, spot=spot,
                        net_cash=exit_value, costs=costs, cash_after=cash,
                        equity_after=0.0, realized_pnl=realized,
                    ))

        # 3) mark all open structures at this bar's close.
        holdings = 0.0
        net_delta = 0.0
        for st in open_states.values():
            marked = mark_structure(st.structure, current_bar.close, t, r, iv[t])
            holdings += marked["value"]
            net_delta += marked["greeks"]["delta"]
        equity = cash + holdings

        cash_list[t] = cash
        equity_list[t] = equity
        count_list[t] = float(len(open_states))
        delta_list[t] = net_delta
        min_cash = min(min_cash, cash)

    # unrealized = if we closed everything now at the last bar's close.
    last_close = bars[n - 1].close
    unrealized = 0.0
    total_max_risk = 0.0
    for st in open_states.values():
        marked = mark_structure(st.structure, last_close, n - 1, r, iv[n - 1])
        unrealized += st.entry_cash + marked["value"] - st.open_costs
        total_max_risk += st.max_risk if st.max_risk != float("inf") else 0.0

    portfolio = OptionsPortfolio(
        bars=list(bars[:n]), cash=cash_list, equity_curve=equity_list,
        open_structure_counts=count_list, net_delta=delta_list,
    )

    return OptionsLedgerResult(
        portfolio=portfolio,
        fills=fills,
        closed_trades=closed,
        open_structures=[st.structure for st in open_states.values()],
        final_cash=cash,
        final_equity=equity_list[-1] if n else capital,
        realized_pnl=realized_total,
        unrealized_pnl=unrealized,
        max_risk=total_max_risk,
        min_cash=min_cash,
        warnings=warnings,
    )

"""Pure, stateless core for the replay / manual-trading feature.

This module holds the ledger math and signal analysis. It has **no** FastAPI,
no session state, and no I/O, so every function here is independently unit
testable. ``replay_service`` is the stateful layer built on top.

The ledger loop in :func:`build_ledger` is a deliberate line-for-line mirror of
``backtest.event_driven.EventDrivenEngine.run`` (see event_driven.py:81-148),
with exactly one substitution: the target position at each bar comes from the
user's order placed on the *previous* bar instead of from the strategy's
position sizer. Keeping the arithmetic identical is what makes the user's,
the algorithm's, and buy-&-hold's numbers directly comparable, and lets the
result be a real ``backtest.portfolio.Portfolio`` that the existing analytics
consume with no shim.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np

from domain.interfaces import IPositionSizer, IStrategy
from domain.models import Bar
from backtest.execution import ExecutionModel
from backtest.portfolio import Portfolio
from backtest.position_sizing import VolatilityBasedSizer

# Tolerances. TRADE_EPS matches EventDrivenEngine's hardcoded 1e-8 cost gate.
SIGNAL_EPS = 1e-9
TRADE_EPS = 1e-8
CASH_EPS = 1e-6


# --- Data structures --------------------------------------------------------


@dataclass(frozen=True)
class ReplayOrder:
    """A single user order. ``bar_index`` is the bar the user was LOOKING at
    (its close is the newest price they know); the order fills at
    ``bar_index + 1``, mirroring the engine's "act on t-1, fill at t"."""

    id: str
    bar_index: int
    side: str                 # "buy" | "sell" | "close"
    qty_mode: str = "shares"  # "shares" | "fraction" | "algo" | "algo_scaled"
    qty_value: float = 0.0    # shares, or fraction of equity; ignored for close/algo
    note: str = ""
    placed_at: str = ""       # wall-clock ISO, journal only; never affects math


@dataclass(frozen=True)
class Fill:
    order_id: str
    decision_index: int
    fill_index: int
    timestamp: datetime
    requested_target: float
    trade_shares: float       # 0.0 if below min_trade_shares (a no-op)
    exec_price: float
    slippage: float
    commission: float
    position_after: float
    cash_after: float
    equity_after: float

    @property
    def no_op(self) -> bool:
        return abs(self.trade_shares) < TRADE_EPS


@dataclass(frozen=True)
class SignalEvent:
    index: int                 # bar whose CLOSE produced the change (decision bar)
    fill_index: int            # index + 1 — the bar it would execute on
    timestamp: datetime
    from_signal: float
    to_signal: float
    kind: str                  # enter/exit/flip long/short | scale
    close: float
    algo_target_shares: float  # the algo's target at fill_index, for "match algo"


@dataclass
class LedgerResult:
    portfolio: Portfolio
    fills: List[Fill]
    final_cash: float
    final_position: float
    final_equity: float
    min_cash: float
    max_gross_exposure: float
    warnings: List[str] = field(default_factory=list)


# --- Signal helpers ---------------------------------------------------------


def _num(x: Any) -> float:
    """NaN/None -> 0.0, else float."""
    if x is None:
        return 0.0
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(xf) or math.isinf(xf):
        return 0.0
    return xf


def classify_signal_change(prev: float, curr: float) -> str:
    ps = 0 if abs(prev) <= SIGNAL_EPS else (1 if prev > 0 else -1)
    cs = 0 if abs(curr) <= SIGNAL_EPS else (1 if curr > 0 else -1)
    if ps == 0 and cs > 0:
        return "enter_long"
    if ps == 0 and cs < 0:
        return "enter_short"
    if ps > 0 and cs == 0:
        return "exit_long"
    if ps < 0 and cs == 0:
        return "exit_short"
    if ps > 0 and cs < 0:
        return "flip_short"
    if ps < 0 and cs > 0:
        return "flip_long"
    return "scale"


def derive_signal_events(
    bars: Sequence[Bar],
    signals: Sequence[float],
    algo_target_positions: Optional[Sequence[float]] = None,
    *,
    start_index: int = 0,
) -> List[SignalEvent]:
    """The bar indices where the signal CHANGES — the moments the UI pauses on.

    An event at bar ``i`` is first actionable at ``i + 1`` (the engine acts on
    ``signals[t-1]``). Changes on the final bar are dropped (nothing to fill
    against). NaN is treated as flat (0.0)."""
    events: List[SignalEvent] = []
    n = min(len(signals), len(bars))
    for i in range(max(1, start_index), n):
        prev = _num(signals[i - 1])
        curr = _num(signals[i])
        if abs(curr - prev) <= SIGNAL_EPS:
            continue
        fill_index = i + 1
        if fill_index >= len(bars):
            continue
        algo_target = 0.0
        if algo_target_positions is not None and fill_index < len(algo_target_positions):
            algo_target = _num(algo_target_positions[fill_index])
        events.append(
            SignalEvent(
                index=i,
                fill_index=fill_index,
                timestamp=bars[i].timestamp,
                from_signal=prev,
                to_signal=curr,
                kind=classify_signal_change(prev, curr),
                close=bars[i].close,
                algo_target_shares=algo_target,
            )
        )
    return events


def audit_causality(
    strategy: IStrategy,
    bars: Sequence[Bar],
    *,
    probes: int = 12,
    tol: float = 1e-9,
) -> Dict[str, Any]:
    """Detect lookahead: does ``generate_signals(bars[:k])`` agree with the full
    run on the first ``k`` bars? A strategy that peeks at future bars will
    diverge. Cheap (~a dozen extra generate_signals calls)."""
    n = len(bars)
    if n < 2:
        return {"causal": True, "first_divergence_index": None, "probes_checked": []}

    full = [_num(s) for s in strategy.generate_signals(bars)]
    ks = sorted({int(k) for k in np.geomspace(2, n, num=probes)})
    ks = [k for k in ks if 2 <= k <= n]

    first_div: Optional[int] = None
    checked: List[int] = []
    for k in ks:
        sig = [_num(s) for s in strategy.generate_signals(bars[:k])]
        checked.append(k)
        upto = min(k, len(sig), len(full))
        for j in range(upto):
            if abs(sig[j] - full[j]) > tol:
                first_div = j if first_div is None else min(first_div, j)
                break
        if first_div is not None:
            break
    return {
        "causal": first_div is None,
        "first_divergence_index": first_div,
        "probes_checked": checked,
    }


# --- Sizing ----------------------------------------------------------------


def algo_target_for_user(
    bars: Sequence[Bar],
    signals: Sequence[float],
    *,
    sizer: IPositionSizer,
    fill_index: int,
    user_prev_equity: float,
) -> float:
    """The algo's target share count if it were sized against the USER's equity.

    ``sizer`` MUST be a fresh instance — ``VolatilityBasedSizer.size_position``
    mutates ``self._history`` (position_sizing.py:159), so a shared instance
    would give different answers on repeated calls. For the volatility sizer we
    reconstruct exactly the rolling window the engine would have at this bar."""
    t = fill_index
    if t < 1 or t > len(bars):
        return 0.0
    if isinstance(sizer, VolatilityBasedSizer):
        # At engine bar t, size_position(current_bar=bars[t-1]) appends bars[t-1]
        # to a history capped at window+1. Prime with bars[t-1-window : t-1] so
        # the append reproduces bars[t-1-window : t].
        lo = max(0, (t - 1) - sizer.window)
        sizer._history = list(bars[lo:t - 1])
    prev_bar = bars[t - 1]
    return float(
        sizer.size_position(
            signal=_num(signals[t - 1]),
            price=prev_bar.close,
            current_equity=user_prev_equity,
            current_bar=prev_bar,
        )
    )


def resolve_target(
    order: ReplayOrder,
    *,
    position: float,
    bars: Sequence[Bar],
    signals: Sequence[float],
    prev_bar: Bar,
    prev_equity: float,
    fill_index: int,
    algo_target_positions: Optional[Sequence[float]],
    sizer_factory: Optional[Callable[[], IPositionSizer]],
    whole_shares: bool,
) -> float:
    """Translate one order into the resulting **target** position (shares)."""
    side = order.side
    if side == "close":
        return 0.0

    sign = 1.0 if side == "buy" else -1.0
    mode = order.qty_mode

    if mode == "algo":
        if algo_target_positions is None or fill_index >= len(algo_target_positions):
            raise ValueError("No algo target available for this bar.")
        target = _num(algo_target_positions[fill_index])
    elif mode == "algo_scaled":
        if sizer_factory is None:
            raise ValueError("algo_scaled requires a sizer factory.")
        target = algo_target_for_user(
            bars, signals,
            sizer=sizer_factory(),
            fill_index=fill_index,
            user_prev_equity=prev_equity,
        )
    elif mode == "fraction":
        px = prev_bar.close
        shares = 0.0 if px <= 0 else (order.qty_value * prev_equity) / px
        target = position + sign * shares
    elif mode == "shares":
        target = position + sign * order.qty_value
    else:
        raise ValueError(f"Unknown qty_mode: {mode}")

    if whole_shares:
        target = float(math.trunc(target))
    return float(target)


# --- The ledger ------------------------------------------------------------


def build_ledger(
    bars: Sequence[Bar],
    signals: Sequence[float],
    orders: Sequence[ReplayOrder],
    *,
    upto_index: int,
    capital: float,
    exec_model: ExecutionModel,
    timing: str,
    min_trade_shares: float,
    algo_target_positions: Optional[Sequence[float]] = None,
    sizer_factory: Optional[Callable[[], IPositionSizer]] = None,
    whole_shares: bool = False,
) -> LedgerResult:
    """Recompute the entire account state from the order list, up to and
    including bar ``upto_index``. Pure: same inputs always yield the same
    result, and the input ``orders`` is never mutated.

    Mirrors ``EventDrivenEngine.run``: the only difference is that between
    orders the position is HELD (target == current position) rather than
    resized every bar."""
    if not bars:
        raise ValueError("Cannot build a ledger on empty data.")
    n = min(max(upto_index + 1, 0), len(bars))
    if n <= 0:
        raise ValueError("upto_index must be >= 0.")

    orders_by_decision: Dict[int, List[ReplayOrder]] = defaultdict(list)
    for o in orders:
        orders_by_decision[o.bar_index].append(o)

    target_positions = [0.0] * n
    active_positions = [0.0] * n
    trades_list = [0.0] * n
    slippage_costs = [0.0] * n
    commission_costs = [0.0] * n
    cash_list = [capital] * n
    holdings_list = [0.0] * n
    equity_list = [capital] * n

    cash = capital
    position = 0.0
    fills: List[Fill] = []
    min_cash = capital
    max_gross = 0.0

    for t in range(n):
        if t == 0:
            cash_list[0] = cash
            active_positions[0] = position
            holdings_list[0] = 0.0
            equity_list[0] = cash
            continue

        prev_bar = bars[t - 1]
        prev_equity = equity_list[t - 1]
        decision_index = t - 1
        current_bar = bars[t]
        exec_price = current_bar.open if timing == "next_open" else current_bar.close

        day_orders = orders_by_decision.get(decision_index, [])
        bar_trade_total = 0.0
        bar_slip_total = 0.0
        bar_comm_total = 0.0

        # No order at this bar -> hold: target == position, no trade.
        for order in day_orders:
            target_shares = resolve_target(
                order,
                position=position,
                bars=bars,
                signals=signals,
                prev_bar=prev_bar,
                prev_equity=prev_equity,
                fill_index=t,
                algo_target_positions=algo_target_positions,
                sizer_factory=sizer_factory,
                whole_shares=whole_shares,
            )
            trade_shares = target_shares - position
            if abs(trade_shares) < min_trade_shares:
                trade_shares = 0.0
                target_shares = position

            if abs(trade_shares) > TRADE_EPS:
                slippage = exec_model.calculate_slippage(exec_price, trade_shares)
                commission = exec_model.calculate_commission(exec_price, trade_shares)
            else:
                slippage = 0.0
                commission = 0.0

            cash = cash - (trade_shares * exec_price) - (slippage + commission)
            position = target_shares
            bar_trade_total += trade_shares
            bar_slip_total += slippage
            bar_comm_total += commission

            fills.append(
                Fill(
                    order_id=order.id,
                    decision_index=decision_index,
                    fill_index=t,
                    timestamp=current_bar.timestamp,
                    requested_target=target_shares,
                    trade_shares=trade_shares,
                    exec_price=exec_price,
                    slippage=slippage,
                    commission=commission,
                    position_after=position,
                    cash_after=cash,
                    equity_after=cash + position * current_bar.close,
                )
            )

        holdings = position * current_bar.close
        equity = cash + holdings

        target_positions[t] = position
        active_positions[t] = position
        trades_list[t] = bar_trade_total
        slippage_costs[t] = bar_slip_total
        commission_costs[t] = bar_comm_total
        cash_list[t] = cash
        holdings_list[t] = holdings
        equity_list[t] = equity

        min_cash = min(min_cash, cash)
        max_gross = max(max_gross, abs(holdings))

    portfolio = Portfolio(
        data=list(bars[:n]),
        cash=cash_list,
        positions=active_positions,
        equity_curve=equity_list,
        trades=trades_list,
        slippage_cost=slippage_costs,
        commission_cost=commission_costs,
        target_positions=target_positions,
        signals=[_num(s) for s in signals[:n]],
    )

    return LedgerResult(
        portfolio=portfolio,
        fills=fills,
        final_cash=cash,
        final_position=position,
        final_equity=equity_list[-1] if n else capital,
        min_cash=min_cash,
        max_gross_exposure=max_gross,
    )


# --- Wire-format timestamps -------------------------------------------------


def is_intraday(index) -> bool:
    """True when there is more than one bar on some calendar date — the same
    heuristic Portfolio.daily_returns and calculate_sharpe_ratio already use."""
    try:
        dates = np.array([ts.date() for ts in index])
    except AttributeError:
        return False
    return len(np.unique(dates)) < len(dates)


def iso_index(index, *, intraday: Optional[bool] = None) -> List:
    """Epoch seconds for intraday (so 5m bars don't collapse to identical
    date strings), 'YYYY-MM-DD' for daily."""
    if intraday is None:
        intraday = is_intraday(index)
    if intraday:
        return [int(ts.timestamp()) for ts in index]
    return [ts.strftime("%Y-%m-%d") for ts in index]

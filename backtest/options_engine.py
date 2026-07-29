"""Options-mode backtest engine.

A **separate** class from ``EventDrivenEngine`` (the share path is untouched).
It reuses the existing scalar-signal machinery: any ``IStrategy`` emits signals,
and each signal state-change is mapped to opening/closing a configured option
*structure template* (e.g. "bear call spread, 30 DTE, short delta 0.30, width
$5"). This is what lets any existing strategy be traded as options for free.

Mapping:
    enter (flat -> non-flat)   -> open the template structure
    exit  (non-flat -> flat)   -> close the open structure
    flip                       -> close, then open a fresh structure
Auto-expiry is handled by the ledger, independent of signals.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from domain.interfaces import IStrategy
from domain.models import Bar
from backtest.execution import ExecutionModel
from options.ledger import OptionOrder, OptionsLedgerResult, build_options_ledger
from options.structures import StructureSpec

# Reuse the signal-event derivation from the replay ledger (single source of truth).
from desktop.backend.services.replay_ledger import derive_signal_events


class OptionsEventDrivenEngine:
    def __init__(
        self,
        strategy: IStrategy,
        structure: StructureSpec,
        execution_model: ExecutionModel,
        initial_capital: float = 100000.0,
        execution_timing: str = "next_open",
        risk_free_rate: float = 0.04,
        iv_window: int = 20,
        iv_multiplier: float = 1.0,
        iv_override: Optional[float] = None,
        iv_floor: float = 0.05,
        iv_cap: float = 3.0,
        margin_policy: str = "defined_risk",
    ):
        if execution_timing not in ("next_open", "next_close"):
            raise ValueError("execution_timing must be 'next_open' or 'next_close'.")
        self.strategy = strategy
        self.structure = structure
        self.execution_model = execution_model
        self.initial_capital = initial_capital
        self.execution_timing = execution_timing
        self.risk_free_rate = risk_free_rate
        self.iv_window = iv_window
        self.iv_multiplier = iv_multiplier
        self.iv_override = iv_override
        self.iv_floor = iv_floor
        self.iv_cap = iv_cap
        self.margin_policy = margin_policy

    def signals_to_orders(self, bars: Sequence[Bar], signals: Sequence[float]) -> List[OptionOrder]:
        """Turn signal state-changes into a deterministic option order list."""
        events = derive_signal_events(bars, signals)
        orders: List[OptionOrder] = []
        open_id: Optional[str] = None
        seq = 0

        def close_current(bar_index: int):
            nonlocal open_id
            if open_id is not None:
                orders.append(OptionOrder(
                    id=f"close_{bar_index}_{open_id}", bar_index=bar_index,
                    action="close", target_structure_id=open_id,
                ))
                open_id = None

        def open_new(bar_index: int):
            nonlocal open_id, seq
            seq += 1
            sid = f"opt_{bar_index}_{seq}"
            s = self.structure
            orders.append(OptionOrder(
                id=sid, bar_index=bar_index, action="open",
                structure_type=s.structure_type, selection=s.selection,
                short_delta=s.short_delta, pct_otm=s.pct_otm, width=s.width,
                strikes=list(s.strikes) if s.strikes else None,
                dte_bars=s.dte_bars, contracts=s.contracts, grid_spacing=s.grid_spacing,
            ))
            open_id = sid

        for ev in events:
            kind = ev.kind
            if kind in ("enter_long", "enter_short"):
                if open_id is None:
                    open_new(ev.index)
            elif kind in ("exit_long", "exit_short"):
                close_current(ev.index)
            elif kind in ("flip_long", "flip_short"):
                close_current(ev.index)
                open_new(ev.index)
        return orders

    def run(self, data: Sequence[Bar], signals: Optional[Sequence[float]] = None) -> OptionsLedgerResult:
        if not data:
            raise ValueError("Cannot run backtest on empty data.")
        if signals is None:
            signals = self.strategy.generate_signals(data)
        if len(signals) != len(data):
            raise ValueError("Strategy signals length does not match data length.")

        orders = self.signals_to_orders(data, signals)
        return build_options_ledger(
            data, orders,
            upto_index=len(data) - 1,
            capital=self.initial_capital,
            exec_model=self.execution_model,
            timing=self.execution_timing,
            risk_free_rate=self.risk_free_rate,
            iv_window=self.iv_window,
            iv_multiplier=self.iv_multiplier,
            iv_override=self.iv_override,
            iv_floor=self.iv_floor,
            iv_cap=self.iv_cap,
            margin_policy=self.margin_policy,
        )

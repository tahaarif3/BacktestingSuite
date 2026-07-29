"""Options structures + ledger: economics, determinism, reconciliation."""

from datetime import datetime, timedelta

import pytest

from domain.models import Bar
from backtest.execution import ExecutionModel
from options.structures import StructureSpec, build_structure
from options.ledger import OptionOrder, build_options_ledger


def _flat_bars(n, price=100.0):
    return [Bar(datetime(2023, 1, 1) + timedelta(days=i), price, price + 1, price - 1, price, 1e6)
            for i in range(n)]


def _ramp_bars(n, start=100.0, step=0.0):
    bars = []
    for i in range(n):
        p = start + i * step
        bars.append(Bar(datetime(2023, 1, 1) + timedelta(days=i), p, p + 1, p - 1, p, 1e6))
    return bars


def test_bear_call_spread_boundaries():
    spec = StructureSpec("bear_call_spread", selection="delta", short_delta=0.30,
                         width=5, dte_bars=30, contracts=1, grid_spacing=1)
    st = build_structure(spec, 100, 0.25, 0.04, open_index=0, structure_id="s")
    credit = -st.net_premium_per_share * 100  # cash received
    assert credit > 0                                   # it's a credit spread
    assert st.max_profit == pytest.approx(credit, abs=1e-6)
    assert st.max_loss == pytest.approx(-(5 * 100 - credit), abs=1e-6)
    assert st.is_defined_risk
    assert len(st.breakevens) == 1


def test_naked_short_is_undefined_risk():
    spec = StructureSpec("short_call", selection="delta", short_delta=0.30,
                         dte_bars=30, contracts=1, grid_spacing=1)
    st = build_structure(spec, 100, 0.25, 0.04, open_index=0, structure_id="s")
    assert st.max_loss == float("-inf")
    assert not st.is_defined_risk


def test_ledger_deterministic_and_non_mutating():
    bars = _flat_bars(40)
    orders = [OptionOrder(id="s1", bar_index=0, action="open", structure_type="bear_call_spread",
                          dte_bars=20, width=5, contracts=1, grid_spacing=1)]
    em = ExecutionModel()
    snapshot = [OptionOrder(**{**o.__dict__}) for o in orders]
    r1 = build_options_ledger(bars, orders, upto_index=39, capital=100000, exec_model=em,
                              timing="next_close", iv_override=0.25)
    r2 = build_options_ledger(bars, orders, upto_index=39, capital=100000, exec_model=em,
                              timing="next_close", iv_override=0.25)
    assert r1.portfolio.equity_curve.tolist() == r2.portfolio.equity_curve.tolist()
    assert r1.final_equity == r2.final_equity
    # orders untouched
    assert [o.__dict__ for o in orders] == [o.__dict__ for o in snapshot]


def test_credit_increases_cash_and_expiry_keeps_credit():
    # Flat market: short strikes never breached -> keep the full credit.
    bars = _flat_bars(30)
    orders = [OptionOrder(id="s1", bar_index=0, action="open", structure_type="bear_call_spread",
                          dte_bars=15, width=5, contracts=1, grid_spacing=1)]
    r = build_options_ledger(bars, orders, upto_index=29, capital=100000,
                             exec_model=ExecutionModel(), timing="next_close", iv_override=0.25)
    assert r.final_cash > 100000              # credit received
    assert r.realized_pnl > 0                 # kept the credit at expiry
    assert len(r.open_structures) == 0        # settled
    assert r.final_equity == pytest.approx(100000 + r.realized_pnl, abs=1e-6)


def test_max_loss_on_rally_through_strikes():
    # Strong rally so the spread ends max-loss.
    bars = _ramp_bars(30, start=100.0, step=2.0)  # ends at ~158
    spec_ref = build_structure(
        StructureSpec("bear_call_spread", short_delta=0.30, width=5, dte_bars=15,
                      contracts=1, grid_spacing=1),
        bars[1].close, 0.25, 0.04, open_index=1, structure_id="ref")
    orders = [OptionOrder(id="s1", bar_index=0, action="open", structure_type="bear_call_spread",
                          short_delta=0.30, dte_bars=15, width=5, contracts=1, grid_spacing=1)]
    r = build_options_ledger(bars, orders, upto_index=29, capital=100000,
                             exec_model=ExecutionModel(), timing="next_close", iv_override=0.25)
    # realized should be close to the structure's max loss (negative)
    assert r.realized_pnl == pytest.approx(spec_ref.max_loss, abs=1.0)
    assert r.realized_pnl < 0


def test_equity_reconciles_open_position():
    bars = _flat_bars(10)
    orders = [OptionOrder(id="s1", bar_index=0, action="open", structure_type="bull_put_spread",
                          dte_bars=30, width=5, contracts=1, grid_spacing=1)]  # expiry beyond window
    r = build_options_ledger(bars, orders, upto_index=9, capital=100000,
                             exec_model=ExecutionModel(), timing="next_close", iv_override=0.25)
    assert len(r.open_structures) == 1        # still open (expiry beyond window)
    # capital + realized + unrealized == final equity
    assert 100000 + r.realized_pnl + r.unrealized_pnl == pytest.approx(r.final_equity, abs=1e-6)

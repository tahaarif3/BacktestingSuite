"""Tests for the pure replay ledger core (desktop/backend/services/replay_ledger.py).

The load-bearing guarantee: replaying the algorithm's own decisions through
build_ledger must reproduce EventDrivenEngine byte-for-byte, so that the User /
Algo / Buy-&-Hold comparison the feature exists for is honest.
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from domain.interfaces import IStrategy
from domain.models import Bar
from backtest.execution import ExecutionModel
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import (
    FixedSharesSizer,
    FixedFractionalSizer,
    VolatilityBasedSizer,
)

from desktop.backend.services.replay_ledger import (
    ReplayOrder,
    build_ledger,
    resolve_target,
    derive_signal_events,
    audit_causality,
    algo_target_for_user,
    classify_signal_change,
    iso_index,
    is_intraday,
)


# --- fixtures ---------------------------------------------------------------


def wavy_bars(n=300, intraday=False):
    """Deterministic wavy uptrend so crossovers/flips occur."""
    bars = []
    t0 = datetime(2020, 1, 1, 9, 30)
    price = 100.0
    for i in range(n):
        price *= 1.0 + 0.004 * math.sin(i / 7.0) + 0.0005
        step = timedelta(minutes=5) if intraday else timedelta(days=1)
        o = price * 0.998
        h = price * 1.012
        low = price * 0.988
        bars.append(Bar(t0 + step * i, o, h, low, price, 1_000_000.0))
    return bars


class ToySMA(IStrategy):
    """Causal SMA-crossover-ish strategy for parity tests."""

    def __init__(self, fast=5, slow=20, long_only=True):
        self.fast = fast
        self.slow = slow
        self.long_only = long_only

    def generate_signals(self, bars):
        closes = np.array([b.close for b in bars], dtype=float)
        n = len(closes)
        sig = np.zeros(n)
        for i in range(n):
            if i < self.slow - 1:
                continue
            fast = closes[i - self.fast + 1 : i + 1].mean()
            slow = closes[i - self.slow + 1 : i + 1].mean()
            sig[i] = 1.0 if fast > slow else (0.0 if self.long_only else -1.0)
        return [float(s) for s in sig]


class PeekingStrategy(IStrategy):
    """Deliberately cheats: uses tomorrow's close. audit_causality must catch it."""

    def generate_signals(self, bars):
        closes = [b.close for b in bars]
        out = []
        for i in range(len(closes)):
            if i + 1 < len(closes) and closes[i + 1] > closes[i]:
                out.append(1.0)
            else:
                out.append(0.0)
        return out


def orders_from_engine_trades(portfolio_df, mode="algo"):
    """Build one ReplayOrder per bar where the engine actually traded."""
    orders = []
    trades = portfolio_df["trades"].tolist()
    targets = portfolio_df["target_position"].tolist()
    for t in range(len(trades)):
        if abs(trades[t]) <= 1e-8:
            continue
        # engine trade at bar t was decided at bar t-1
        decision = t - 1
        if mode == "algo":
            orders.append(ReplayOrder(id=f"o{t}", bar_index=decision, side="buy", qty_mode="algo"))
        elif mode == "shares":
            side = "buy" if trades[t] > 0 else "sell"
            orders.append(
                ReplayOrder(id=f"o{t}", bar_index=decision, side=side,
                            qty_mode="shares", qty_value=abs(trades[t]))
            )
    return orders


def run_engine_ref(bars, signals, sizer, timing, capital=100000.0,
                   slip=0.0002, comm=0.0005):
    exec_model = ExecutionModel(slippage_pct=slip, commission_pct=comm)
    engine = EventDrivenEngine(
        strategy=None if signals is not None else ToySMA(),
        position_sizer=sizer,
        execution_model=exec_model,
        initial_capital=capital,
        execution_timing=timing,
    )
    return engine.run(bars, signals=signals), exec_model


# --- engine parity (the load-bearing tests) ---------------------------------


@pytest.mark.parametrize("timing", ["next_open", "next_close"])
def test_algo_mode_reproduces_engine_exactly(timing):
    bars = wavy_bars(300)
    signals = ToySMA().generate_signals(bars)

    for sizer in (
        FixedSharesSizer(fixed_shares=100),
        FixedFractionalSizer(fraction=0.5, initial_capital=100000.0),
        VolatilityBasedSizer(target_risk_per_trade=500.0, window=20),
    ):
        eng_portfolio, exec_model = run_engine_ref(bars, signals, sizer, timing)
        edf = eng_portfolio.data
        algo_targets = edf["target_position"].tolist()

        orders = orders_from_engine_trades(edf, mode="algo")
        res = build_ledger(
            bars, signals, orders,
            upto_index=len(bars) - 1,
            capital=100000.0,
            exec_model=exec_model,
            timing=timing,
            min_trade_shares=1e-8,
            algo_target_positions=algo_targets,
        )
        rdf = res.portfolio.data
        for col in ["cash", "active_position", "equity", "trades",
                    "slippage_cost", "commission_cost"]:
            np.testing.assert_allclose(
                rdf[col].to_numpy(), edf[col].to_numpy(), atol=1e-9,
                err_msg=f"{col} mismatch for {type(sizer).__name__} / {timing}",
            )


@pytest.mark.parametrize("timing", ["next_open", "next_close"])
def test_shares_mode_reproduces_engine(timing):
    bars = wavy_bars(250)
    signals = ToySMA().generate_signals(bars)
    sizer = FixedSharesSizer(fixed_shares=100)
    eng_portfolio, exec_model = run_engine_ref(bars, signals, sizer, timing)
    edf = eng_portfolio.data

    orders = orders_from_engine_trades(edf, mode="shares")
    res = build_ledger(
        bars, signals, orders,
        upto_index=len(bars) - 1, capital=100000.0,
        exec_model=exec_model, timing=timing, min_trade_shares=1e-8,
    )
    rdf = res.portfolio.data
    np.testing.assert_allclose(rdf["equity"].to_numpy(), edf["equity"].to_numpy(), atol=1e-9)
    np.testing.assert_allclose(rdf["cash"].to_numpy(), edf["cash"].to_numpy(), atol=1e-9)


def test_min_trade_shares_gate_matches_engine():
    bars = wavy_bars(50)
    signals = [0.0] * 50
    exec_model = ExecutionModel(slippage_pct=0.01, commission_pct=0.01)
    # Order for a tiny share count under a large min gate -> no-op.
    orders = [ReplayOrder(id="o1", bar_index=5, side="buy", qty_mode="shares", qty_value=0.5)]
    res = build_ledger(
        bars, signals, orders, upto_index=49, capital=100000.0,
        exec_model=exec_model, timing="next_open", min_trade_shares=1.0,
    )
    assert res.final_position == 0.0
    assert res.fills[0].trade_shares == 0.0
    assert res.fills[0].no_op is True
    assert res.fills[0].slippage == 0.0 and res.fills[0].commission == 0.0
    assert res.final_cash == pytest.approx(100000.0)


def test_execution_costs_use_the_same_model():
    bars = wavy_bars(30)
    exec_model = ExecutionModel(
        slippage_pct=0.001, slippage_abs=0.1,
        commission_pct=0.002, commission_per_share=0.05, min_commission=1.0,
    )
    orders = [ReplayOrder(id="o1", bar_index=5, side="buy", qty_mode="shares", qty_value=100.0)]
    res = build_ledger(
        bars, [0.0] * 30, orders, upto_index=29, capital=1_000_000.0,
        exec_model=exec_model, timing="next_open", min_trade_shares=1e-8,
    )
    fill = res.fills[0]
    assert fill.slippage == pytest.approx(
        exec_model.calculate_slippage(fill.exec_price, fill.trade_shares)
    )
    assert fill.commission == pytest.approx(
        exec_model.calculate_commission(fill.exec_price, fill.trade_shares)
    )


# --- determinism ------------------------------------------------------------


def _sample_orders():
    return [
        ReplayOrder(id="a", bar_index=10, side="buy", qty_mode="fraction", qty_value=0.5),
        ReplayOrder(id="b", bar_index=40, side="sell", qty_mode="fraction", qty_value=0.25),
        ReplayOrder(id="c", bar_index=80, side="close"),
    ]


def test_build_is_pure():
    bars = wavy_bars(120)
    exec_model = ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)
    orders = _sample_orders()
    kwargs = dict(upto_index=119, capital=100000.0, exec_model=exec_model,
                  timing="next_open", min_trade_shares=1e-8)
    r1 = build_ledger(bars, [0.0] * 120, orders, **kwargs)
    r2 = build_ledger(bars, [0.0] * 120, orders, **kwargs)
    np.testing.assert_array_equal(r1.portfolio.data["equity"].to_numpy(),
                                  r2.portfolio.data["equity"].to_numpy())
    # inputs not mutated
    assert [o.id for o in orders] == ["a", "b", "c"]


def test_undo_equals_never_placed():
    bars = wavy_bars(120)
    exec_model = ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)
    orders = _sample_orders()
    kwargs = dict(upto_index=119, capital=100000.0, exec_model=exec_model,
                  timing="next_open", min_trade_shares=1e-8)
    full = build_ledger(bars, [0.0] * 120, orders, **kwargs)
    dropped = build_ledger(bars, [0.0] * 120, orders[:-1], **kwargs)
    # up to bar 80 (before the dropped close) they must be identical
    np.testing.assert_allclose(
        full.portfolio.data["equity"].to_numpy()[:80],
        dropped.portfolio.data["equity"].to_numpy()[:80], atol=1e-9,
    )


def test_order_list_insertion_order_independent():
    bars = wavy_bars(120)
    exec_model = ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)
    orders = _sample_orders()
    kwargs = dict(upto_index=119, capital=100000.0, exec_model=exec_model,
                  timing="next_open", min_trade_shares=1e-8)
    a = build_ledger(bars, [0.0] * 120, orders, **kwargs)
    b = build_ledger(bars, [0.0] * 120, list(reversed(orders)), **kwargs)
    np.testing.assert_allclose(a.portfolio.data["equity"].to_numpy(),
                               b.portfolio.data["equity"].to_numpy(), atol=1e-9)


# --- no lookahead -----------------------------------------------------------


def test_order_fills_at_next_bar():
    bars = wavy_bars(30)
    exec_model = ExecutionModel()
    orders = [ReplayOrder(id="o", bar_index=10, side="buy", qty_mode="shares", qty_value=10.0)]
    for timing, attr in (("next_open", "open"), ("next_close", "close")):
        res = build_ledger(bars, [0.0] * 30, orders, upto_index=29, capital=100000.0,
                           exec_model=exec_model, timing=timing, min_trade_shares=1e-8)
        fill = res.fills[0]
        assert fill.decision_index == 10
        assert fill.fill_index == 11
        assert fill.exec_price == pytest.approx(getattr(bars[11], attr))


def test_truncating_future_bars_does_not_change_the_past():
    bars = wavy_bars(200)
    exec_model = ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)
    orders = [ReplayOrder(id="a", bar_index=10, side="buy", qty_mode="fraction", qty_value=0.5)]
    k = 120
    full = build_ledger(bars, [0.0] * 200, orders, upto_index=k, capital=100000.0,
                        exec_model=exec_model, timing="next_open", min_trade_shares=1e-8)
    truncated = build_ledger(bars[:k + 1], [0.0] * (k + 1), orders, upto_index=k,
                            capital=100000.0, exec_model=exec_model,
                            timing="next_open", min_trade_shares=1e-8)
    np.testing.assert_allclose(full.portfolio.data["equity"].to_numpy(),
                               truncated.portfolio.data["equity"].to_numpy(), atol=1e-9)


def test_fraction_sizing_uses_prev_close_not_fill_price():
    bars = wavy_bars(30)
    exec_model = ExecutionModel()  # zero cost, so shares are exact
    orders = [ReplayOrder(id="o", bar_index=10, side="buy", qty_mode="fraction", qty_value=1.0)]
    res = build_ledger(bars, [0.0] * 30, orders, upto_index=29, capital=100000.0,
                       exec_model=exec_model, timing="next_open", min_trade_shares=1e-8)
    expected_shares = 100000.0 / bars[10].close  # prev close, the price the user saw
    assert res.fills[0].trade_shares == pytest.approx(expected_shares)


def test_audit_causality_flags_a_peeking_strategy():
    bars = wavy_bars(120)
    report = audit_causality(PeekingStrategy(), bars)
    assert report["causal"] is False
    assert report["first_divergence_index"] is not None


def test_audit_causality_passes_a_causal_strategy():
    bars = wavy_bars(120)
    report = audit_causality(ToySMA(), bars)
    assert report["causal"] is True
    assert report["first_divergence_index"] is None


# --- signal events ----------------------------------------------------------


def _events_from(signals):
    bars = wavy_bars(len(signals))
    targets = [0.0] * len(signals)
    return derive_signal_events(bars, signals, targets, start_index=0)


def test_event_kinds():
    sig = [0, 0, 1, 1, 1, 0, -1, -1, 0, 0]
    ev = _events_from(sig)
    assert [e.index for e in ev] == [2, 5, 6, 8]
    assert [e.kind for e in ev] == ["enter_long", "exit_long", "enter_short", "exit_short"]


def test_flip_kind():
    ev = _events_from([1, 1, -1, -1])
    assert len(ev) == 1
    assert ev[0].index == 2 and ev[0].kind == "flip_short"


def test_events_before_start_index_excluded():
    bars = wavy_bars(10)
    ev = derive_signal_events(bars, [0, 1, 0, 1, 0, 0, 0, 0, 0, 0], [0.0] * 10, start_index=4)
    assert all(e.index >= 4 for e in ev)


def test_float_tolerance_no_event():
    ev = _events_from([0.0, 1e-12, 0.0, 0.0])
    assert ev == []


def test_final_bar_event_dropped():
    # change on the last bar -> no fill_index -> excluded
    ev = _events_from([0, 0, 0, 1])
    assert ev == []


def test_nan_signal_treated_as_flat():
    ev = _events_from([0.0, float("nan"), 0.0, 0.0])
    assert ev == []


def test_algo_target_attached():
    bars = wavy_bars(10)
    targets = [0.0, 0.0, 0.0, 50.0, 50.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    ev = derive_signal_events(bars, [0, 0, 1, 1, 0, 0, 0, 0, 0, 0], targets)
    assert ev[0].index == 2 and ev[0].fill_index == 3
    assert ev[0].algo_target_shares == 50.0


# --- sizer statefulness -----------------------------------------------------


def test_algo_scaled_volatility_sizer_matches_engine():
    bars = wavy_bars(120)
    signals = ToySMA().generate_signals(bars)
    sizer = VolatilityBasedSizer(target_risk_per_trade=500.0, window=20)
    eng_portfolio, _ = run_engine_ref(bars, signals, sizer, "next_open")
    edf = eng_portfolio.data
    equity = edf["equity"].tolist()
    targets = edf["target_position"].tolist()

    for t in range(25, 120, 7):
        got = algo_target_for_user(
            bars, signals,
            sizer=VolatilityBasedSizer(target_risk_per_trade=500.0, window=20),
            fill_index=t, user_prev_equity=equity[t - 1],
        )
        assert got == pytest.approx(targets[t], rel=1e-9, abs=1e-9)


def test_algo_scaled_is_idempotent():
    bars = wavy_bars(80)
    signals = ToySMA().generate_signals(bars)
    kw = dict(fill_index=40, user_prev_equity=100000.0)
    a = algo_target_for_user(bars, signals,
                             sizer=VolatilityBasedSizer(target_risk_per_trade=500.0, window=20), **kw)
    b = algo_target_for_user(bars, signals,
                             sizer=VolatilityBasedSizer(target_risk_per_trade=500.0, window=20), **kw)
    assert a == pytest.approx(b)


# --- misc -------------------------------------------------------------------


def test_close_targets_zero():
    o = ReplayOrder(id="c", bar_index=5, side="close")
    bars = wavy_bars(10)
    tgt = resolve_target(o, position=123.0, bars=bars, signals=[0.0] * 10,
                         prev_bar=bars[5], prev_equity=100000.0, fill_index=6,
                         algo_target_positions=None, sizer_factory=None, whole_shares=False)
    assert tgt == 0.0


def test_whole_shares_truncates():
    o = ReplayOrder(id="w", bar_index=5, side="buy", qty_mode="shares", qty_value=10.7)
    bars = wavy_bars(10)
    tgt = resolve_target(o, position=0.0, bars=bars, signals=[0.0] * 10,
                         prev_bar=bars[5], prev_equity=100000.0, fill_index=6,
                         algo_target_positions=None, sizer_factory=None, whole_shares=True)
    assert tgt == 10.0


def test_iso_index_daily_vs_intraday():
    daily = wavy_bars(5, intraday=False)
    intra = wavy_bars(5, intraday=True)
    di = [b.timestamp for b in daily]
    ii = [b.timestamp for b in intra]
    assert is_intraday(ii) is True
    assert is_intraday(di) is False
    assert all(isinstance(x, str) for x in iso_index(di))
    assert all(isinstance(x, int) for x in iso_index(ii))


def test_classify_scale():
    assert classify_signal_change(0.5, 1.0) == "scale"

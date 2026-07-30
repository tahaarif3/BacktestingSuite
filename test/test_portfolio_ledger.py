"""Multi-symbol options portfolio ledger."""

from datetime import datetime, timedelta

import pytest

from backtest.execution import ExecutionModel
from options.portfolio_ledger import PortfolioOptionOrder, build_portfolio_options_ledger


def _axis(n=40):
    return [datetime(2023, 1, 1) + timedelta(days=i) for i in range(n)]


def _flat(n, px):
    return [px] * n


def _base(**over):
    n = 40
    kw = dict(
        dates=_axis(n),
        closes={"AAA": _flat(n, 100.0), "BBB": _flat(n, 50.0)},
        opens={"AAA": _flat(n, 100.0), "BBB": _flat(n, 50.0)},
        iv={"AAA": [0.25] * n, "BBB": [0.30] * n},
        orders=[],
        upto_index=n - 1,
        capital=100000,
        exec_model=ExecutionModel(),
        timing="next_close",
        risk_free_rate=0.04,
    )
    kw.update(over)
    return kw


def test_shared_cash_reconciles():
    orders = [
        PortfolioOptionOrder(id="a1", symbol="AAA", bar_index=0, action="open",
                             structure_type="bull_put_spread", width=5, dte_bars=15,
                             contracts=1, grid_spacing=1),
        PortfolioOptionOrder(id="b1", symbol="BBB", bar_index=2, action="open",
                             structure_type="bear_call_spread", width=2.5, dte_bars=15,
                             contracts=2, grid_spacing=0.5),
    ]
    res = build_portfolio_options_ledger(**_base(orders=orders))
    # both flat-market credit spreads expire worthless -> keep full credit
    assert res.realized_pnl > 0
    assert res.final_equity == pytest.approx(100000 + res.realized_pnl, abs=1e-6)
    assert len(res.closed_trades) == 2
    assert {c.symbol for c in res.closed_trades} == {"AAA", "BBB"}
    assert res.open_by_symbol == {}


def test_deterministic_and_non_mutating():
    orders = [PortfolioOptionOrder(id="a1", symbol="AAA", bar_index=0, action="open",
                                   structure_type="bull_put_spread", width=5, dte_bars=15,
                                   contracts=1, grid_spacing=1)]
    snap = [dict(o.__dict__) for o in orders]
    r1 = build_portfolio_options_ledger(**_base(orders=orders))
    r2 = build_portfolio_options_ledger(**_base(orders=orders))
    assert r1.equity_curve == r2.equity_curve
    assert [dict(o.__dict__) for o in orders] == snap  # inputs untouched


def test_manual_close_realizes_and_frees_cash():
    orders = [
        PortfolioOptionOrder(id="a1", symbol="AAA", bar_index=0, action="open",
                             structure_type="bull_put_spread", width=5, dte_bars=30,
                             contracts=1, grid_spacing=1),
        PortfolioOptionOrder(id="c1", symbol="AAA", bar_index=5, action="close",
                             target_structure_id="a1"),
    ]
    res = build_portfolio_options_ledger(**_base(orders=orders))
    assert any(f.action == "close" for f in res.fills)
    assert res.open_by_symbol == {}  # closed before its 30-bar expiry


def test_unknown_symbol_and_missing_price_warn_not_crash():
    n = 40
    closes = {"AAA": [None] * 10 + [100.0] * (n - 10)}  # AAA "not listed" first 10 bars
    res = build_portfolio_options_ledger(**_base(
        closes=closes, opens=closes, iv={"AAA": [0.25] * n},
        orders=[
            PortfolioOptionOrder(id="x", symbol="ZZZ", bar_index=0, action="open"),  # unknown
            PortfolioOptionOrder(id="a", symbol="AAA", bar_index=1, action="open",
                                 structure_type="bull_put_spread", width=5, dte_bars=15,
                                 contracts=1, grid_spacing=1),  # fills at bar 2 -> no price
        ],
    ))
    assert res.warnings  # both issues recorded
    assert res.final_equity == pytest.approx(100000, abs=1.0)  # nothing opened

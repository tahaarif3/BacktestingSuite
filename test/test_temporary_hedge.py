import numpy as np
import pandas as pd
import pytest

from timing.temporary_hedge import HedgeConfig, run_temporary_hedge


def _prices(n=600, falling=False):
    idx = pd.date_range("2004-01-02", periods=n, freq="B")
    close = np.linspace(200, 70, n) if falling else np.linspace(100, 200, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) * 1.001,
        "low": np.minimum(open_, close) * 0.999, "close": close,
    }, index=idx)


def _cfg(vehicle="short_overlay", **kwargs):
    return HedgeConfig(
        strategy="always", vehicle=vehicle, hedge_fraction=0.50,
        decision_frequency="weekly", exit_plan="signal_clear",
        start="2005-01-03", end="2006-03-31", cash_yield_annual=0.0,
        short_borrow_annual=0.0, cost_pct=0.0, **kwargs,
    )


def test_overlay_and_cash_derisk_are_equivalent_without_friction():
    prices = _prices(falling=True)
    overlay = run_temporary_hedge(_cfg(), prices)
    cash = run_temporary_hedge(_cfg("derisk_cash"), prices)
    assert overlay.summary["Final Value"] == pytest.approx(cash.summary["Final Value"], rel=1e-10)
    assert overlay.daily["net_exposure"].iloc[-1] == pytest.approx(0.5, abs=0.01)
    assert overlay.daily["gross_exposure"].iloc[-1] == pytest.approx(1.5, abs=0.02)


def test_short_borrow_makes_overlay_worse_than_equivalent_cash_derisk():
    prices = _prices(falling=True)
    overlay = run_temporary_hedge(HedgeConfig(
        strategy="always", vehicle="short_overlay", hedge_fraction=0.50,
        decision_frequency="weekly", exit_plan="signal_clear",
        start="2005-01-03", end="2006-03-31", cash_yield_annual=0.0,
        short_borrow_annual=0.10, cost_pct=0.0,
    ), prices)
    cash = run_temporary_hedge(_cfg("derisk_cash"), prices)
    assert overlay.summary["Short Borrow Cost"] > 0
    assert overlay.summary["Final Value"] < cash.summary["Final Value"]


def test_trades_are_causal_and_contributions_are_weekly():
    result = run_temporary_hedge(_cfg(), _prices(falling=True))
    assert (result.trades["signal_date"] < result.trades["trade_date"]).all()
    weeks = result.daily.index.isocalendar()[["year", "week"]].drop_duplicates().shape[0]
    assert result.summary["Total Contributed"] == pytest.approx(25 * weeks)


def test_fixed_profit_exits_once_until_trigger_rearms():
    prices = _prices(falling=True)
    result = run_temporary_hedge(HedgeConfig(
        strategy="always", vehicle="short_overlay", hedge_fraction=0.50,
        decision_frequency="weekly", exit_plan="profit10_reversal",
        start="2005-01-03", end="2006-03-31", cash_yield_annual=0.0,
        short_borrow_annual=0.0, cost_pct=0.0,
    ), prices)
    exits = result.trades[result.trades["action"] == "exit_hedge"]
    entries = result.trades[result.trades["action"] == "enter_hedge"]
    assert len(exits) == 1
    assert len(entries) == 1


@pytest.mark.parametrize(
    "exit_plan",
    ["profit10_only", "profit10_and_sma20", "staged_profit10_sma20"],
)
def test_new_profit_exit_plans_are_causal(exit_plan):
    idx = pd.date_range("2004-01-02", periods=700, freq="B")
    close = np.r_[
        np.linspace(160, 120, 400),
        np.linspace(120, 90, 120),
        np.linspace(90, 130, 180),
    ]
    open_ = np.r_[close[0], close[:-1]]
    prices = pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close) * 1.002,
        "low": np.minimum(open_, close) * 0.998, "close": close,
    }, index=idx)
    result = run_temporary_hedge(HedgeConfig(
        strategy="always", vehicle="derisk_cash", hedge_fraction=0.50,
        decision_frequency="monthly", exit_plan=exit_plan,
        start="2005-01-03", end=str(idx[-1].date()), cash_yield_annual=0.0,
        short_borrow_annual=0.0, cost_pct=0.0,
    ), prices)
    assert (result.trades["signal_date"] < result.trades["trade_date"]).all()
    assert (result.trades["action"] == "exit_hedge").sum() == 1
    if exit_plan == "staged_profit10_sma20":
        assert (result.trades["action"] == "reduce_hedge").sum() == 1


def test_requires_prestart_bar():
    prices = _prices(100)
    with pytest.raises(ValueError, match="pre-start"):
        run_temporary_hedge(HedgeConfig(
            start=str(prices.index[0].date()), end=str(prices.index[-1].date()),
        ), prices)


def test_incremental_contributions_do_not_rebalance_existing_book():
    prices = _prices(falling=True)
    result = run_temporary_hedge(HedgeConfig(
        strategy="always", vehicle="derisk_cash", hedge_fraction=0.50,
        decision_frequency="weekly", exit_plan="signal_clear",
        start="2005-01-03", end="2006-03-31", cash_yield_annual=0.0,
        short_borrow_annual=0.0, cost_pct=0.0, rebalance_on_contribution=False,
    ), prices)
    allocations = result.trades[result.trades["action"] == "contribution_allocation"]
    assert len(allocations) == result.summary["Weekly Contributions"]
    assert allocations["long_trade"].iloc[1:].eq(12.5).all()
    assert allocations["short_trade"].eq(0.0).all()

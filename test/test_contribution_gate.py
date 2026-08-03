import numpy as np
import pandas as pd
import pytest

from dca.contribution_gate import ContributionGateConfig, run_contribution_gate


def _prices(n=700):
    idx = pd.date_range("2000-01-03", periods=n, freq="B")
    close = np.linspace(100, 170, n)
    open_ = np.r_[close[0], close[:-1]] * 1.001
    return pd.DataFrame({"open": open_, "close": close}, index=idx)


def test_gate_uses_prior_close_and_next_open():
    result = run_contribution_gate(ContributionGateConfig(
        start="2001-01-03", end="2002-06-28", ma_period=75,
        gate_mode="above_sma", cost_pct=0.0,
    ), _prices())
    assert (result.decisions["signal_date"] < result.decisions["trade_date"]).all()
    assert (result.decisions["execution_open"] != result.decisions["prior_close"]).any()
    assert result.summary["Closed-Gate Contributions"] == 0


def test_closed_custom_gate_accumulates_then_deploys_reserve():
    prices = _prices()
    start, end = "2001-01-03", "2001-06-29"
    dates = prices.loc[start:end].index
    custom = pd.Series(True, index=prices.index)
    custom.loc[dates[:40]] = False
    result = run_contribution_gate(ContributionGateConfig(
        start=start, end=end, gate_mode="custom", cost_pct=0.0,
    ), prices, custom_weekly_gate=custom)
    closed = result.decisions[~result.decisions["gate_open"]]
    reopened = result.decisions[result.decisions["gate_open"]].iloc[0]
    assert closed["cash_deployed"].eq(0.0).all()
    assert reopened["cash_deployed"] > 25.0
    assert result.summary["Total Contributed"] == pytest.approx(
        25.0 * result.summary["Weekly Contributions"]
    )


def test_cash_yield_only_benefits_reserved_cash():
    prices = _prices()
    custom = pd.Series(False, index=prices.index)
    base = ContributionGateConfig(
        start="2001-01-03", end="2002-06-28", gate_mode="custom", cost_pct=0.0,
    )
    no_yield = run_contribution_gate(base, prices, custom_weekly_gate=custom)
    with_yield = run_contribution_gate(
        base, prices, annual_cash_yield=pd.Series(0.05, index=prices.index),
        custom_weekly_gate=custom,
    )
    assert with_yield.summary["Cash Interest"] > 0
    assert with_yield.summary["Final Value"] > no_yield.summary["Final Value"]

import numpy as np
import pandas as pd
import pytest

from timing.realistic import RealisticConfig, run_realistic, synthetic_daily_reset_ohlc


def _prices(n=300, daily=0.0004):
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    close = 100 * (1 + daily) ** np.arange(n)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)


def test_equal_weekly_contributions_and_positive_return():
    prices = _prices()
    result = run_realistic(
        RealisticConfig(start_capital=0, contribution_amount=25, cost_pct=0),
        prices,
        np.ones(len(prices)),
    )
    weeks = prices.index.isocalendar()[["year", "week"]].drop_duplicates().shape[0]
    assert result.summary["Total Contributed"] == pytest.approx(25 * weeks)
    assert result.summary["Final Value"] > result.summary["Total Contributed"]
    assert result.summary["Margin Calls"] == 0


def test_intraday_low_can_force_margin_liquidation():
    prices = _prices(120, daily=0.0)
    prices.iloc[80, prices.columns.get_loc("low")] = 55.0
    result = run_realistic(
        RealisticConfig(
            start_capital=10000, contribution_amount=0, cost_pct=0,
            maintenance_margin=0.40, liquidation_lockout_days=20,
        ),
        prices,
        np.full(len(prices), 2.0),
    )
    assert result.summary["Margin Calls"] >= 1
    assert any(x["action"] == "forced_liquidation" for x in result.log)


def test_daily_reset_etf_has_sideways_volatility_decay():
    idx = pd.date_range("2015-01-02", periods=201, freq="B")
    close = np.where(np.arange(201) % 2 == 0, 100.0, 110.0)
    spy = pd.DataFrame({"open": close, "high": close, "low": close, "close": close}, index=idx)
    etf = synthetic_daily_reset_ohlc(spy, leverage=2.0, expense_ratio=0, financing_annual=0)
    assert spy.close.iloc[-1] == pytest.approx(spy.close.iloc[0])
    assert etf.close.iloc[-1] < etf.close.iloc[0]


def test_leverage_reports_financing_and_execution_costs():
    prices = _prices(300, daily=0.0002)
    result = run_realistic(
        RealisticConfig(
            start_capital=1000, contribution_amount=25, borrow_annual=0.10,
            cost_pct=0.001, max_exposure=1.5,
        ),
        prices,
        np.full(len(prices), 1.25),
    )
    assert result.summary["Financing Cost"] > 0
    assert result.summary["Trading Cost"] > 0

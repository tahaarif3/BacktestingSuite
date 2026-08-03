import numpy as np
import pandas as pd
import pytest

from timing.short_weekly import ShortWeeklyConfig, decision_flags, run_short_weekly


def _prices(n=500, falling=False):
    idx = pd.date_range("2004-01-02", periods=n, freq="B")
    close = np.linspace(200, 50, n) if falling else np.linspace(100, 200, n)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame({
        "open": open_, "high": np.maximum(open_, close),
        "low": np.minimum(open_, close), "close": close,
    }, index=idx)


def _cfg(strategy, **kwargs):
    return ShortWeeklyConfig(
        strategy=strategy, start="2005-01-03", end="2005-12-30",
        cash_yield_annual=0.0, short_borrow_annual=0.0, cost_pct=0.0, **kwargs,
    )


def test_equal_contributions_and_causal_trade_dates():
    prices = _prices()
    results = [run_short_weekly(_cfg(s), prices) for s in (
        "buy_hold", "long_cash_sma200", "symmetric_sma200",
        "falling_sma200_short", "half_short_confirmed",
        "golden_cross_long_short", "breakdown_short", "early_bear_harvest",
    )]
    assert len({r.summary["Total Contributed"] for r in results}) == 1
    for result in results:
        assert (result.trades["signal_date"] < result.trades["trade_date"]).all()


def test_execution_day_close_cannot_change_same_open_trade():
    a = _prices()
    b = a.copy()
    trade_day = pd.Timestamp("2005-06-06")
    b.loc[trade_day, "close"] *= 0.25
    ra = run_short_weekly(_cfg("symmetric_sma200"), a)
    rb = run_short_weekly(_cfg("symmetric_sma200"), b)
    ta = ra.trades.loc[ra.trades["trade_date"] == trade_day, "target_exposure"]
    tb = rb.trades.loc[rb.trades["trade_date"] == trade_day, "target_exposure"]
    assert ta.tolist() == tb.tolist()


def test_short_profits_in_clean_decline_before_costs():
    prices = _prices(falling=True)
    short = run_short_weekly(_cfg("symmetric_sma200"), prices)
    cash = run_short_weekly(_cfg("long_cash_sma200"), prices)
    assert short.summary["Short Days"] > 0
    assert short.summary["Final Value"] > cash.summary["Final Value"]


def test_short_borrow_cost_reduces_value_and_is_reported():
    prices = _prices(falling=True)
    free = run_short_weekly(_cfg("symmetric_sma200"), prices)
    costly = run_short_weekly(ShortWeeklyConfig(
        strategy="symmetric_sma200", start="2005-01-03", end="2005-12-30",
        cash_yield_annual=0.0, short_borrow_annual=0.10, cost_pct=0.0,
    ), prices)
    assert costly.summary["Short Borrow Cost"] > 0
    assert costly.summary["Final Value"] < free.summary["Final Value"]


def test_long_control_does_not_borrow_to_pay_transaction_costs():
    result = run_short_weekly(ShortWeeklyConfig(
        strategy="buy_hold", start="2005-01-03", end="2005-12-30",
        cash_yield_annual=0.0, short_borrow_annual=0.0, cost_pct=0.001,
    ), _prices())
    assert result.summary["Minimum Cash"] >= -1e-8
    assert result.summary["Average Exposure"] <= 1.0 + 1e-8


def test_decision_schedules_use_first_available_session():
    idx = pd.date_range("2024-01-02", "2024-06-28", freq="B")
    start, end = idx[0], idx[-1]
    weekly = decision_flags(idx, start, end, "weekly")
    monthly = decision_flags(idx, start, end, "monthly")
    quarterly = decision_flags(idx, start, end, "quarterly")
    assert weekly.sum() > monthly.sum() > quarterly.sum()
    assert monthly.sum() == 6
    assert quarterly.sum() == 2
    assert all(idx[i].day <= 3 for i in np.flatnonzero(monthly))


def test_take_profit_closes_position_and_waits_for_next_decision():
    prices = _prices()
    prices["high"] = prices["open"] * 1.10
    prices["low"] = np.minimum(prices["open"], prices["close"])
    result = run_short_weekly(ShortWeeklyConfig(
        strategy="buy_hold", start="2005-01-03", end="2005-12-30",
        cash_yield_annual=0.0, short_borrow_annual=0.0, cost_pct=0.0,
        decision_frequency="monthly", take_profit_pct=0.05,
    ), prices)
    exits = result.trades[result.trades["action"] == "take_profit"]
    assert result.summary["Take Profit Exits"] == len(exits) > 0
    assert (exits["trade_date"] >= exits["signal_date"]).all()
    assert (result.daily["exposure"].abs() < 1e-9).mean() > 0.80


def test_requires_prestart_bar():
    prices = _prices(300)
    with pytest.raises(ValueError, match="pre-start"):
        run_short_weekly(ShortWeeklyConfig(
            strategy="buy_hold", start=str(prices.index[0].date()),
            end=str(prices.index[-1].date()),
        ), prices)

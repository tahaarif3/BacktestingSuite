import numpy as np
import pandas as pd
import pytest

from dca.adaptive_weekly import AdaptiveWeeklyConfig, STRATEGY_LABELS, run_adaptive_weekly


def _prices(n=600):
    idx = pd.date_range("2018-01-01", periods=n, freq="B")
    close = 100.0 * np.exp(np.linspace(0.0, 0.5, n) + 0.08 * np.sin(np.arange(n) / 20))
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1_000_000.0,
    }, index=idx)


def test_every_strategy_uses_equal_contributions_and_never_borrows():
    prices = _prices()
    results = []
    for strategy in STRATEGY_LABELS:
        result = run_adaptive_weekly(
            AdaptiveWeeklyConfig(strategy=strategy, start="2019-01-01", end="2020-03-31"),
            prices,
        )
        results.append(result)
        assert result.daily["cash"].min() >= -1e-9
        assert (result.decisions["signal_date"] < result.decisions["trade_date"]).all()
        assert (result.decisions["actual_purchase"] <= (
            result.decisions["cash_before_deposit"] + 25.0 + 1e-9
        )).all()
    totals = {round(r.summary["Total Contributed"], 8) for r in results}
    counts = {r.summary["Weekly Contributions"] for r in results}
    assert len(totals) == 1
    assert len(counts) == 1


def test_trade_size_cannot_see_execution_day_close():
    prices = _prices()
    cfg = AdaptiveWeeklyConfig(strategy="composite", start="2019-01-01", end="2019-03-31")
    original = run_adaptive_weekly(cfg, prices)
    first_trade = original.decisions.iloc[0]["trade_date"]

    changed = prices.copy()
    changed.loc[first_trade, ["close", "high", "low"]] *= 10.0
    rerun = run_adaptive_weekly(cfg, changed)

    assert rerun.decisions.iloc[0]["signal_date"] == original.decisions.iloc[0]["signal_date"]
    assert rerun.decisions.iloc[0]["multiplier"] == original.decisions.iloc[0]["multiplier"]
    assert rerun.decisions.iloc[0]["desired_purchase"] == original.decisions.iloc[0]["desired_purchase"]


def test_buy_hold_buys_one_contribution_each_week_at_adverse_open():
    prices = _prices()
    result = run_adaptive_weekly(
        AdaptiveWeeklyConfig(strategy="buy_hold", start="2019-01-01", end="2019-12-31", cost_pct=0.001),
        prices,
    )
    assert (result.decisions["desired_purchase"] == 25.0).all()
    assert (result.decisions["fill"] > result.decisions["open"]).all()
    assert result.summary["Ending Cash"] == pytest.approx(0.0, abs=1e-8)


def test_requires_prestart_bar_for_signal():
    prices = _prices(50)
    with pytest.raises(ValueError, match="pre-start"):
        run_adaptive_weekly(
            AdaptiveWeeklyConfig(start=str(prices.index[0].date()), end=str(prices.index[-1].date())),
            prices,
        )


def test_monthly_and_quarterly_reviews_keep_weekly_contributions():
    prices = _prices(700)
    results = [run_adaptive_weekly(AdaptiveWeeklyConfig(
        strategy="drawdown_ladder", start="2019-01-01", end="2020-06-30",
        decision_frequency=frequency, cash_yield_annual=0.0, cost_pct=0.0,
    ), prices) for frequency in ("weekly", "monthly", "quarterly")]
    assert len({r.summary["Total Contributed"] for r in results}) == 1
    assert results[0].summary["Decision Updates"] > results[1].summary["Decision Updates"]
    assert results[1].summary["Decision Updates"] > results[2].summary["Decision Updates"]

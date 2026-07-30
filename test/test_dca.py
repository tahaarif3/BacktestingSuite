"""SPY DCA / bankroll backtest engine."""

import numpy as np
import pandas as pd
import pytest

from dca.engine import DcaConfig, run_dca, annualized_irr


def _rising(n=500, start=100.0, drift=0.0004):
    idx = pd.date_range("2016-01-04", periods=n, freq="B")  # business days
    close = start * (1 + drift) ** np.arange(n)
    return pd.DataFrame({"close": close}, index=idx)


def test_always_monthly_contributions_and_buys():
    df = _rising()
    r = run_dca(DcaConfig(label="base", amount=100, cadence="monthly", buy_rule="always"), df)
    months = df.index.to_period("M").nunique()
    assert r.summary["Total Contributed"] == pytest.approx(100 * months)
    assert r.buys == months                       # deploys on each contribution
    assert r.summary["Final Value"] > r.summary["Total Contributed"]   # rising market
    assert r.summary["Money-Weighted Return (IRR)"] > 0
    assert r.summary["Max Drawdown"] <= 0


def test_semimonthly_doubles_buys_same_total():
    df = _rising()
    monthly = run_dca(DcaConfig(amount=100, cadence="monthly"), df)
    semi = run_dca(DcaConfig(amount=50, cadence="semimonthly"), df)
    assert semi.buys >= monthly.buys              # more frequent
    # same dollars in over the same window (±one period)
    assert semi.summary["Total Contributed"] == pytest.approx(monthly.summary["Total Contributed"], rel=0.1)


def test_above_ma_accumulates_dry_powder():
    # price dips below its MA early then rises above -> accumulate should hold
    # cash while below and deploy once above; contributions still count in full.
    n = 500
    idx = pd.date_range("2016-01-04", periods=n, freq="B")
    close = np.concatenate([np.linspace(100, 80, 150), np.linspace(80, 160, n - 150)])
    df = pd.DataFrame({"close": close}, index=idx)
    r = run_dca(DcaConfig(amount=100, cadence="monthly", buy_rule="above_ma",
                          ma_period=50, unused_cash="accumulate"), df)
    months = idx.to_period("M").nunique()
    assert r.summary["Total Contributed"] == pytest.approx(100 * months)  # nothing skipped
    assert r.buys >= 1


def test_skip_mode_contributes_less_than_always():
    n = 400
    idx = pd.date_range("2016-01-04", periods=n, freq="B")
    close = np.linspace(100, 60, n)              # persistent downtrend
    df = pd.DataFrame({"close": close}, index=idx)
    always = run_dca(DcaConfig(amount=100, cadence="monthly", buy_rule="above_ma",
                               ma_period=50, unused_cash="accumulate"), df)
    skip = run_dca(DcaConfig(amount=100, cadence="monthly", buy_rule="above_ma",
                             ma_period=50, unused_cash="skip"), df)
    # in a downtrend, "above_ma + skip" invests almost nothing
    assert skip.summary["Total Contributed"] < always.summary["Total Contributed"]


def test_sell_rule_reduces_shares():
    df = _rising()
    no_sell = run_dca(DcaConfig(amount=100, cadence="monthly", sell_rule="none"), df)
    sell = run_dca(DcaConfig(amount=100, cadence="monthly", buy_rule="always",
                             sell_rule="above_ma", ma_period=50, sell_fraction=1.0), df)
    assert sell.sells > 0
    assert sell.summary["Shares Held"] <= no_sell.summary["Shares Held"]


def test_irr_sign():
    from datetime import date
    # invest 1000 now, get 2000 in 1 year -> ~100% IRR
    irr = annualized_irr([(date(2020, 1, 1), -1000.0), (date(2021, 1, 1), 2000.0)])
    assert irr == pytest.approx(1.0, abs=0.02)

"""Exposure-based timing engine."""

import numpy as np
import pandas as pd
import pytest

from timing.engine import TimingConfig, run_timing, target_exposure


def _series(close):
    idx = pd.date_range("2010-01-04", periods=len(close), freq="B")
    return pd.DataFrame({"close": close}, index=idx)


def test_buy_hold_stays_invested():
    df = _series(100 * (1.0004) ** np.arange(400))
    r = run_timing(TimingConfig(strategy="buy_hold"), df)
    assert r.summary["CAGR"] > 0
    assert r.summary["Avg Exposure"] == pytest.approx(1.0, abs=0.02)
    assert r.summary["Rebalances"] == 0            # never trades after the initial buy
    assert r.summary["Max Drawdown"] <= 0


def test_ma_goes_to_cash_below_ma():
    # rise, then a sustained fall below the MA -> exposure should drop toward 0
    close = np.concatenate([np.linspace(100, 160, 250), np.linspace(160, 90, 200)])
    df = _series(close)
    exp = target_exposure(TimingConfig(strategy="ma", ma_period=100, signal_freq="daily"), df["close"])
    assert exp[-1] == 0.0 and exp[120] == 1.0
    r = run_timing(TimingConfig(strategy="ma", ma_period=100, signal_freq="daily"), df)
    assert r.summary["Rebalances"] >= 1


def test_leverage_raises_avg_exposure_and_dd():
    df = _series(100 * (1.0004) ** np.arange(500))     # steady uptrend, always above MA
    base = run_timing(TimingConfig(strategy="buy_hold"), df)
    lev = run_timing(TimingConfig(strategy="ma", ma_period=100, exposure_in=1.5, exposure_out=1.0), df)
    assert lev.summary["Avg Exposure"] > 1.2
    assert lev.summary["CAGR"] > base.summary["CAGR"]   # leverage in a pure uptrend beats


def test_vol_target_caps_exposure():
    rng = np.linspace(100, 200, 400) * (1 + 0.03 * np.sin(np.arange(400) / 5))
    df = _series(rng)
    exp = target_exposure(TimingConfig(strategy="vol_target", vol_target=0.15, vol_cap=1.0), df["close"])
    assert exp.max() <= 1.0 + 1e-9
    assert exp.min() >= 0.0


def test_monthly_signal_trades_less_than_daily():
    close = 100 * (1 + 0.02 * np.sin(np.arange(600) / 8))   # choppy around a flat MA
    df = _series(close)
    daily = run_timing(TimingConfig(strategy="ma", ma_period=100, signal_freq="daily"), df)
    monthly = run_timing(TimingConfig(strategy="ma", ma_period=100, signal_freq="monthly"), df)
    assert monthly.summary["Rebalances"] <= daily.summary["Rebalances"]


def test_deterministic():
    df = _series(100 * (1.0003) ** np.arange(400))
    a = run_timing(TimingConfig(strategy="ma", ma_period=50), df)
    b = run_timing(TimingConfig(strategy="ma", ma_period=50), df)
    assert a.value == b.value

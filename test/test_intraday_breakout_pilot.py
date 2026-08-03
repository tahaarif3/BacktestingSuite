from datetime import date

import numpy as np
import pandas as pd

from intraday_breakout.pilot import (
    IntradayBreakoutConfig,
    _confirmed_hh_hl,
    detect_daily_resistance,
    normalize_ohlcv,
    simulate_trade,
)


def _daily_with_level(n=180):
    idx = pd.bdate_range("2024-01-02", periods=n)
    close = np.linspace(90.0, 99.0, n)
    high = close + 1.0
    low = close - 1.0
    # Three separated, confirmed rejections around 105.
    for i in (40, 90, 140):
        high[i] = 105.0
        close[i] = 103.0
    return pd.DataFrame(
        {"open": close - 0.2, "high": high, "low": low, "close": close, "volume": 20_000_000},
        index=idx,
    )


def test_daily_level_uses_only_information_before_session():
    d = _daily_with_level()
    cfg = IntradayBreakoutConfig(cluster_tolerance_atr=0.0)
    session = (d.index[-1] + pd.offsets.BDay(1)).date()
    a = detect_daily_resistance(d, session, cfg)
    future = pd.DataFrame(
        {"open": [99.0], "high": [130.0], "low": [98.0], "close": [125.0], "volume": [30_000_000]},
        index=[pd.Timestamp(session) + pd.offsets.BDay(2)],
    )
    b = detect_daily_resistance(pd.concat([d, future]), session, cfg)
    assert a is not None and b is not None
    assert a["level_center"] == b["level_center"]
    assert a["level_touches"] == b["level_touches"]


def test_minute_pivots_require_right_hand_confirmation():
    idx = pd.date_range("2025-01-02 09:00", periods=9, freq="min", tz="America/New_York")
    # Confirmed highs 3, 4 and lows 1, 2; final apparent high cannot be a pivot.
    d = pd.DataFrame(
        {
            "open": [1, 2, 1, 3, 2, 4, 3, 5, 9],
            "high": [1, 2, 1, 3, 2, 4, 3, 5, 9],
            "low": [1, 1.5, 0.8, 2, 1.5, 3, 2.5, 4, 8],
            "close": [1, 2, 1, 3, 2, 4, 3, 5, 9],
            "volume": 100,
        },
        index=idx,
    )
    ok, detail = _confirmed_hh_hl(d, 1)
    assert ok
    assert detail["last_swing_high"] == 4
    assert detail["last_swing_low"] == 2.5


def test_trade_cannot_enter_before_0935_and_stop_wins_same_bar():
    idx = pd.date_range("2025-01-02 09:35", periods=3, freq="min", tz="America/New_York")
    m = pd.DataFrame(
        {
            "open": [100.0, 100.5, 100.0],
            "high": [103.0, 101.0, 100.5],
            "low": [98.5, 99.0, 99.5],
            "close": [101.0, 100.0, 100.0],
            "volume": [1000, 1000, 1000],
        },
        index=idx,
    )
    cfg = IntradayBreakoutConfig(entry_slippage_bps=0, exit_slippage_bps=0)
    sig = {"signal": True, "ticker": "AAA", "date": "2025-01-02", "raw_entry": 100.0, "stop": 99.0}
    trade = simulate_trade(sig, m, cfg, target_r=2.0)
    assert trade["exit_time"] == idx[0]
    assert trade["exit_reason"] == "stop"
    assert trade["realized_r"] == -1.0


def test_scale_out_uses_multiple_exit_legs_and_one_initial_risk():
    idx = pd.date_range("2025-01-02 09:35", periods=4, freq="min", tz="America/New_York")
    m = pd.DataFrame(
        {
            "open": [100, 101, 102, 103],
            "high": [101.1, 102.1, 103.1, 103.2],
            "low": [100, 101, 102, 103],
            "close": [101, 102, 103, 103],
            "volume": 1000,
        },
        index=idx,
    )
    cfg = IntradayBreakoutConfig(entry_slippage_bps=0, exit_slippage_bps=0, risk_dollars=99)
    sig = {"signal": True, "ticker": "AAA", "date": "2025-01-02", "raw_entry": 100.0, "stop": 99.0}
    trade = simulate_trade(sig, m, cfg, scale_targets=[1, 2, 3])
    assert len(trade["exit_legs"]) == 3
    assert trade["realized_r"] == 2.0
    assert trade["initial_risk_dollars"] == 99.0


def test_naive_intraday_index_is_localized_to_new_york():
    d = pd.DataFrame(
        {"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]},
        index=[pd.Timestamp("2025-01-02 09:30")],
    )
    assert str(normalize_ohlcv(d, intraday=True).index.tz) == "America/New_York"


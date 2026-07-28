"""Network-free tests for market_meta's validators and window planner."""

from datetime import date

import pytest

from desktop.backend.services.market_meta import (
    INTERVALS,
    list_intervals,
    validate_range,
    clamp_range,
    plan_fetch_windows,
    friendly_fetch_error,
)

TODAY = date(2026, 7, 28)


def test_validate_range_1m_too_far_back():
    with pytest.raises(ValueError) as ei:
        validate_range("1m", "2026-01-01", "2026-01-15", today=TODAY)
    msg = str(ei.value)
    assert "30 days" in msg
    # a concrete suggested start date (30 days before today)
    assert "2026-06-28" in msg


def test_validate_range_1h_limit_mentions_730():
    with pytest.raises(ValueError) as ei:
        validate_range("1h", "2023-01-01", "2026-07-01", today=TODAY)
    assert "730" in str(ei.value)


def test_validate_range_daily_ok():
    validate_range("1d", "2010-01-01", "2026-07-01", today=TODAY)  # no raise


def test_validate_range_end_before_start():
    with pytest.raises(ValueError):
        validate_range("1d", "2026-07-01", "2026-01-01", today=TODAY)


def test_unknown_interval():
    with pytest.raises(ValueError):
        validate_range("7s", "2026-01-01", "2026-07-01", today=TODAY)


def test_clamp_range_pulls_start_forward():
    s, e = clamp_range("1m", "2020-01-01", "2026-07-28", today=TODAY)
    assert s == "2026-06-28"
    assert e == "2026-07-28"


def test_clamp_range_caps_end_at_today():
    s, e = clamp_range("1d", "2010-01-01", "2030-01-01", today=TODAY)
    assert e == "2026-07-28"


def test_clamp_range_all_intervals():
    for iid in INTERVALS:
        s, e = clamp_range(iid, "2000-01-01", "2026-07-28", today=TODAY)
        # must not raise when fed back through validation
        validate_range(iid, s, e, today=TODAY)


def test_plan_fetch_windows_1m_splits_into_weekly():
    windows = plan_fetch_windows("1m", "2026-06-01", "2026-06-30")
    assert len(windows) == 5
    for s, e in windows:
        span = (date.fromisoformat(e) - date.fromisoformat(s)).days
        assert span <= 6  # <= 7 days inclusive
    # contiguous, no overlap, covers exactly
    assert windows[0][0] == "2026-06-01"
    assert windows[-1][1] == "2026-06-30"
    for (s1, e1), (s2, e2) in zip(windows, windows[1:]):
        assert date.fromisoformat(s2) == date.fromisoformat(e1) + __import__("datetime").timedelta(days=1)


def test_plan_fetch_windows_daily_single():
    windows = plan_fetch_windows("1d", "2010-01-01", "2026-01-01")
    assert windows == [("2010-01-01", "2026-01-01")]


def test_plan_fetch_windows_empty_when_reversed():
    assert plan_fetch_windows("1d", "2026-01-02", "2026-01-01") == []


def test_friendly_fetch_error_no_leak():
    err = friendly_fetch_error(
        ValueError("No data returned for ticker XYZ from yfinance."),
        "XYZ", "1m", "2026-01-01", "2026-01-07",
    )
    assert "No data returned for ticker" not in err
    assert "XYZ" in err


def test_friendly_fetch_error_network():
    err = friendly_fetch_error(
        ConnectionError("Failed to resolve host"), "AAPL", "1d", "2020-01-01", "2021-01-01"
    )
    assert "Yahoo Finance" in err


def test_interval_table_integrity():
    for iid, spec in INTERVALS.items():
        assert spec.id == iid
        # intraday flag consistent with having a lookback cap
        assert spec.intraday == (spec.max_lookback_days is not None)


def test_list_intervals_shape():
    rows = list_intervals()
    assert any(r["id"] == "1d" for r in rows)
    assert all({"id", "label", "intraday", "note"} <= set(r) for r in rows)

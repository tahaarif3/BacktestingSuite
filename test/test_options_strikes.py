"""Strike-selection helpers."""

import pytest

from options.pricing import bs_delta
from options.strikes import StrikeGrid, nearest_strike, strike_for_delta, strike_for_pct_otm


def test_grid_snap():
    g = StrikeGrid(5.0)
    assert g.snap(103) == 105
    assert g.snap(102) == 100
    assert StrikeGrid(2.5).snap(101.2) == 100.0


def test_pct_otm():
    g = StrikeGrid(1.0)
    assert strike_for_pct_otm(100, 0.05, "call", g) == 105
    assert strike_for_pct_otm(100, 0.05, "put", g) == 95


def test_nearest():
    assert nearest_strike(100, 107.3, StrikeGrid(5)) == 105


def test_strike_for_delta_recovers_target():
    S, T, r, sig = 100.0, 30 / 252, 0.04, 0.25
    for target in (0.20, 0.30, 0.40):
        k = strike_for_delta(S, T, r, sig, target, "call")  # unsnapped
        got = abs(bs_delta(S, k, T, r, sig, "call"))
        assert got == pytest.approx(target, abs=5e-3)


def test_strike_for_delta_put():
    S, T, r, sig = 100.0, 30 / 252, 0.04, 0.25
    k = strike_for_delta(S, T, r, sig, 0.30, "put")
    assert abs(bs_delta(S, k, T, r, sig, "put")) == pytest.approx(0.30, abs=5e-3)
    assert k < S  # a 0.30-delta put is OTM (below spot)

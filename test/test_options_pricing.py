"""Black-Scholes pricing + greeks correctness."""

import math

import pytest

from options.pricing import bs_price, bs_greeks, bs_delta


def test_reference_values():
    # Textbook: S=100,K=100,T=1,r=5%,sigma=20%
    c = bs_price(100, 100, 1.0, 0.05, 0.20, "call")
    p = bs_price(100, 100, 1.0, 0.05, 0.20, "put")
    assert c == pytest.approx(10.4506, abs=1e-3)
    assert p == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    S, K, T, r, sig = 120.0, 100.0, 0.75, 0.03, 0.35
    c = bs_price(S, K, T, r, sig, "call")
    p = bs_price(S, K, T, r, sig, "put")
    # C - P = S - K e^{-rT}
    assert (c - p) == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_greeks_finite_difference():
    S, K, T, r, sig = 100.0, 105.0, 0.5, 0.02, 0.25
    g = bs_greeks(S, K, T, r, sig, "call")
    h = 1e-4
    # delta = dPrice/dS
    fd_delta = (bs_price(S + h, K, T, r, sig, "call") - bs_price(S - h, K, T, r, sig, "call")) / (2 * h)
    assert g["delta"] == pytest.approx(fd_delta, abs=1e-4)
    # gamma = d2Price/dS2
    fd_gamma = (bs_price(S + h, K, T, r, sig, "call") - 2 * bs_price(S, K, T, r, sig, "call")
                + bs_price(S - h, K, T, r, sig, "call")) / (h * h)
    assert g["gamma"] == pytest.approx(fd_gamma, abs=1e-3)
    # vega per 1 vol point ~ dPrice/dsigma / 100
    fd_vega = (bs_price(S, K, T, r, sig + h, "call") - bs_price(S, K, T, r, sig - h, "call")) / (2 * h)
    assert g["vega"] == pytest.approx(fd_vega / 100.0, abs=1e-4)


def test_expiry_intrinsic():
    assert bs_price(110, 100, 0.0, 0.05, 0.2, "call") == pytest.approx(10.0, abs=1e-9)
    assert bs_price(90, 100, 0.0, 0.05, 0.2, "call") == pytest.approx(0.0, abs=1e-9)
    assert bs_price(90, 100, 0.0, 0.05, 0.2, "put") == pytest.approx(10.0, abs=1e-9)


def test_zero_vol_no_crash():
    v = bs_price(100, 90, 0.5, 0.05, 0.0, "call")
    assert v > 0.0 and math.isfinite(v)
    # deep OTM with zero vol -> worthless
    assert bs_price(100, 200, 0.5, 0.05, 0.0, "call") == pytest.approx(0.0, abs=1e-9)


def test_bars_per_year_and_theta_scaling():
    from options.pricing import bars_per_year
    assert bars_per_year("1d") == 252
    assert bars_per_year("1h") == 1764
    assert bars_per_year("5m") == 19656
    # theta is "per bar": doubling bars/year halves per-bar decay; price unchanged.
    g1 = bs_greeks(100, 100, 1.0, 0.04, 0.2, "call", annualization=252)
    g2 = bs_greeks(100, 100, 1.0, 0.04, 0.2, "call", annualization=504)
    assert g1["theta"] == pytest.approx(2 * g2["theta"])
    assert bs_price(100, 100, 1.0, 0.05, 0.2, "call") == pytest.approx(10.4506, abs=1e-3)


def test_delta_bounds():
    # call delta in (0,1), put delta in (-1,0)
    assert 0.0 < bs_delta(100, 100, 1.0, 0.02, 0.2, "call") < 1.0
    assert -1.0 < bs_delta(100, 100, 1.0, 0.02, 0.2, "put") < 0.0
    # deep ITM call delta -> ~1
    assert bs_delta(100, 10, 0.5, 0.02, 0.2, "call") == pytest.approx(1.0, abs=1e-3)

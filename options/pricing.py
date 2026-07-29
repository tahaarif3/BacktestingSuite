"""Black-Scholes option pricing and greeks — stdlib ``math`` only.

Design notes
------------
* **No scipy.** The standard normal CDF is ``0.5*(1+erf(x/sqrt(2)))`` using
  ``math.erf`` (exact, C-speed). Marking is scalar per-leg-per-bar work, so this
  beats scipy and needs no new dependency / no PyInstaller change.
* **T is in trading-day years** (``T = dte_bars / 252``) so theta is "decay per
  trading bar", consistent with the suite's ``sqrt(252)`` annualisation
  everywhere else.
* **Greeks scaling:** ``theta`` is returned *per trading day* (annual / 252) and
  ``vega`` / ``rho`` *per 1.00 volatility / rate point* (annual / 100), matching
  how traders read them.
* Prices/greeks are **per share**; multiply by :data:`CONTRACT_MULTIPLIER` and
  signed contracts for cash.
"""

from __future__ import annotations

import math
from typing import Dict, Tuple

CONTRACT_MULTIPLIER = 100
TRADING_DAYS = 252.0
_SQRT2 = math.sqrt(2.0)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)

# A vol at/below this is treated as zero (degenerate → intrinsic).
SIGMA_EPS = 1e-9
T_EPS = 1e-12


def _phi(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / _SQRT2))


def _pdf(x: float) -> float:
    """Standard normal PDF."""
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


def _norm_kind(kind: str) -> str:
    k = kind.lower().strip()
    if k in ("c", "call"):
        return "call"
    if k in ("p", "put"):
        return "put"
    raise ValueError(f"kind must be 'call' or 'put', got {kind!r}")


def _intrinsic(S: float, K: float, kind: str) -> float:
    return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)


def d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0) -> Tuple[float, float]:
    """Black-Scholes d1/d2. Assumes S,K,T,sigma all strictly positive."""
    vol_sqrt_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def bs_price(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    """Per-share Black-Scholes price of a European call/put.

    Degenerate inputs collapse gracefully to (discounted) intrinsic value so the
    caller never has to special-case expiry or zero-vol bars.
    """
    kind = _norm_kind(kind)
    if S <= 0.0 or K <= 0.0:
        # Nonsensical inputs — return intrinsic on a clamped spot.
        return _intrinsic(max(S, 0.0), K, kind)

    if T <= T_EPS or sigma <= SIGMA_EPS:
        # At/near expiry, or no vol: discounted intrinsic (forward-based) so a
        # deep-ITM option is worth its discounted intrinsic, not raw intrinsic.
        disc_S = S * math.exp(-q * T) if T > 0 else S
        disc_K = K * math.exp(-r * T) if T > 0 else K
        if kind == "call":
            return max(disc_S - disc_K, 0.0)
        return max(disc_K - disc_S, 0.0)

    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    disc_S = S * math.exp(-q * T)
    disc_K = K * math.exp(-r * T)
    if kind == "call":
        return disc_S * _phi(d1) - disc_K * _phi(d2)
    return disc_K * _phi(-d2) - disc_S * _phi(-d1)


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> float:
    """Per-share delta. Used by the strike solver, so kept cheap and standalone."""
    kind = _norm_kind(kind)
    if T <= T_EPS or sigma <= SIGMA_EPS or S <= 0.0 or K <= 0.0:
        # Step function at expiry.
        itm = (S > K) if kind == "call" else (S < K)
        if not itm:
            return 0.0
        return 1.0 if kind == "call" else -1.0
    d1, _ = d1_d2(S, K, T, r, sigma, q)
    disc_q = math.exp(-q * T)
    if kind == "call":
        return disc_q * _phi(d1)
    return disc_q * (_phi(d1) - 1.0)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, kind: str, q: float = 0.0) -> Dict[str, float]:
    """Per-share greeks.

    Returns delta, gamma, theta (per trading day), vega (per 1 vol point),
    rho (per 1% rate). Degenerate bars return delta as a step and the rest 0.
    """
    kind = _norm_kind(kind)
    if T <= T_EPS or sigma <= SIGMA_EPS or S <= 0.0 or K <= 0.0:
        return {
            "delta": bs_delta(S, K, T, r, sigma, kind, q),
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
            "rho": 0.0,
        }

    d1, d2 = d1_d2(S, K, T, r, sigma, q)
    sqrt_t = math.sqrt(T)
    disc_q = math.exp(-q * T)
    disc_r = math.exp(-r * T)
    pdf_d1 = _pdf(d1)

    gamma = disc_q * pdf_d1 / (S * sigma * sqrt_t)
    vega_annual = S * disc_q * pdf_d1 * sqrt_t  # per 1.00 vol
    common_theta = -(S * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if kind == "call":
        delta = disc_q * _phi(d1)
        theta_annual = common_theta - r * K * disc_r * _phi(d2) + q * S * disc_q * _phi(d1)
        rho_annual = K * T * disc_r * _phi(d2)
    else:
        delta = disc_q * (_phi(d1) - 1.0)
        theta_annual = common_theta + r * K * disc_r * _phi(-d2) - q * S * disc_q * _phi(-d1)
        rho_annual = -K * T * disc_r * _phi(-d2)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta_annual / TRADING_DAYS,  # per trading day
        "vega": vega_annual / 100.0,           # per 1 vol point
        "rho": rho_annual / 100.0,             # per 1% rate
    }

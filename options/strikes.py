"""Strike selection helpers: by target delta, by %OTM, or nearest absolute.

``strike_for_delta`` inverts the (monotonic) BS delta curve by **bisection** —
no inverse-normal-CDF needed, so still scipy-free and robust.
"""

from __future__ import annotations

from dataclasses import dataclass

from options.pricing import bs_delta


@dataclass(frozen=True)
class StrikeGrid:
    """A discrete grid of tradeable strikes (e.g. $1 / $2.50 / $5 spacing)."""

    spacing: float = 5.0

    def snap(self, strike: float) -> float:
        if self.spacing <= 0:
            return float(strike)
        return round(strike / self.spacing) * self.spacing


def nearest_strike(spot: float, absolute: float, grid: StrikeGrid | None = None) -> float:
    """Nearest grid strike to an absolute price."""
    return grid.snap(absolute) if grid else float(absolute)


def strike_for_pct_otm(spot: float, pct: float, kind: str, grid: StrikeGrid | None = None) -> float:
    """Strike ``pct`` out-of-the-money from ``spot`` (pct as a fraction, e.g. 0.05).

    Calls go OTM above spot, puts go OTM below spot.
    """
    k = kind.lower()
    if k.startswith("c"):
        raw = spot * (1.0 + abs(pct))
    else:
        raw = spot * (1.0 - abs(pct))
    return grid.snap(raw) if grid else float(raw)


def strike_for_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float,
    kind: str,
    q: float = 0.0,
    grid: StrikeGrid | None = None,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """Strike whose option has |delta| ≈ ``target_delta`` (0<td<1).

    delta is strictly monotonic in K, so bisection converges. For a call,
    |delta| decreases as K rises; for a put, |delta| increases as K rises.
    Result is snapped to ``grid`` if provided.
    """
    k = kind.lower()
    kind = "call" if k.startswith("c") else "put"
    td = min(max(abs(target_delta), 1e-4), 0.9999)

    lo, hi = max(S * 0.2, 0.01), S * 3.0

    def abs_delta(K: float) -> float:
        return abs(bs_delta(S, K, T, r, sigma, kind, q))

    # |delta| is monotonic in K, but the DIRECTION differs by option kind:
    #   call |delta| = Phi(d1)     -> DECREASES as K rises;
    #   put  |delta| = 1 - Phi(d1) -> INCREASES as K rises.
    d_lo = abs_delta(lo)
    d_hi = abs_delta(hi)
    increasing = d_hi > d_lo

    # Clamp when the target lies outside the achievable range.
    if td <= min(d_lo, d_hi):
        strike = lo if d_lo <= d_hi else hi
        return grid.snap(strike) if grid else strike
    if td >= max(d_lo, d_hi):
        strike = lo if d_lo >= d_hi else hi
        return grid.snap(strike) if grid else strike

    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        d_mid = abs_delta(mid)
        if abs(d_mid - td) < tol:
            break
        # Move the bound that keeps the target bracketed, respecting direction.
        if (d_mid < td) == increasing:
            lo = mid
        else:
            hi = mid
    strike = 0.5 * (lo + hi)
    return grid.snap(strike) if grid else float(strike)

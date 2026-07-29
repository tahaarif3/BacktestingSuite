"""Synthetic implied-volatility model.

There is no market IV available, so we use the underlying's **rolling realized
volatility** (annualised stdev of log returns) as the IV input, with a
user-settable multiplier / absolute override and a floor.

Honest limitation
-----------------
Realized-vol-as-IV prices options with **no volatility risk premium**. In the
real market, options — especially the ones you *sell* in a credit spread — trade
richer than realized vol, and that gap is a big part of why premium selling is
profitable. So this model **understates** the edge of short-premium structures
(bear call spreads, iron condors). ``iv_multiplier`` (e.g. 1.1–1.3) is the
manual escape hatch; it is a modelling assumption, not market truth.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

DEFAULT_WINDOW = 20
DEFAULT_ANNUALIZATION = 252.0
DEFAULT_FLOOR = 0.05
DEFAULT_CAP = 3.0


def realized_vol_series(
    closes: Sequence[float],
    window: int = DEFAULT_WINDOW,
    annualization: float = DEFAULT_ANNUALIZATION,
) -> List[float]:
    """Per-bar rolling annualised realized volatility of log returns.

    Warm-up bars (before ``window`` returns exist) reuse the first computable
    value so every bar has a usable vol (mirrors ``VolatilityBasedSizer``'s
    ffill/bfill behaviour). Returns a list aligned 1:1 with ``closes``.
    """
    n = len(closes)
    if n == 0:
        return []
    if n == 1:
        return [DEFAULT_FLOOR]

    log_rets: List[float] = [0.0]  # bar 0 has no prior return
    for i in range(1, n):
        prev, cur = closes[i - 1], closes[i]
        if prev > 0.0 and cur > 0.0:
            log_rets.append(math.log(cur / prev))
        else:
            log_rets.append(0.0)

    sqrt_ann = math.sqrt(annualization)
    out: List[float] = [0.0] * n
    for i in range(n):
        lo = max(1, i - window + 1)  # returns from bar 1 onward
        sample = log_rets[lo:i + 1]
        if len(sample) >= 2:
            mean = sum(sample) / len(sample)
            var = sum((x - mean) ** 2 for x in sample) / (len(sample) - 1)
            out[i] = math.sqrt(var) * sqrt_ann
        else:
            out[i] = 0.0

    # Backfill/forward-fill zeros so warm-up bars get a real vol.
    first_valid = next((v for v in out if v > 0.0), DEFAULT_FLOOR)
    last = first_valid
    for i in range(n):
        if out[i] <= 0.0:
            out[i] = last
        else:
            last = out[i]
    return out


def iv_for_bar(
    rv: float,
    *,
    iv_multiplier: float = 1.0,
    iv_override: Optional[float] = None,
    iv_floor: float = DEFAULT_FLOOR,
    iv_cap: float = DEFAULT_CAP,
) -> float:
    """Turn a realized-vol reading into the IV used for pricing.

    Precedence: an absolute ``iv_override`` wins; otherwise ``rv * iv_multiplier``.
    The result is clamped to ``[iv_floor, iv_cap]``.
    """
    base = iv_override if iv_override is not None else rv * iv_multiplier
    if base < iv_floor:
        base = iv_floor
    if base > iv_cap:
        base = iv_cap
    return float(base)

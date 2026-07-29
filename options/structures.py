"""Option structure factories.

One dispatcher, :func:`build_structure`, turns a structure *spec* (type + strike
selection + width + DTE + contracts) into a concrete, priced
:class:`options.instruments.OptionStructure` at a given bar. Every leg is priced
with Black-Scholes at open (``bs_price``). ``bear_call_spread`` is the headline
path but all templates share the same machinery.

Strike selection modes:
    "delta"     anchor strike at a target |delta| (short leg for credit spreads).
    "pct_otm"   anchor strike a fraction OTM from spot.
    "absolute"  explicit strike(s) provided in ``strikes``.

Time is trading-day years: ``T = dte_bars / 252``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from options.instruments import OptionLeg, OptionStructure, STRUCTURE_TYPES
from options.pricing import TRADING_DAYS, bs_price
from options.strikes import StrikeGrid, nearest_strike, strike_for_delta, strike_for_pct_otm

# Metadata surfaced to the UI via GET /api/options/structures.
CATALOG = [
    {"id": "long_call",       "name": "Long Call",        "legs": 1, "direction": "bullish", "defined_risk": True,  "net": "debit",  "needs_width": False},
    {"id": "long_put",        "name": "Long Put",         "legs": 1, "direction": "bearish", "defined_risk": True,  "net": "debit",  "needs_width": False},
    {"id": "short_call",      "name": "Short Call",       "legs": 1, "direction": "bearish", "defined_risk": False, "net": "credit", "needs_width": False},
    {"id": "short_put",       "name": "Short Put",        "legs": 1, "direction": "bullish", "defined_risk": False, "net": "credit", "needs_width": False},
    {"id": "bull_call_spread","name": "Bull Call Spread", "legs": 2, "direction": "bullish", "defined_risk": True,  "net": "debit",  "needs_width": True},
    {"id": "bear_call_spread","name": "Bear Call Spread", "legs": 2, "direction": "bearish", "defined_risk": True,  "net": "credit", "needs_width": True},
    {"id": "bull_put_spread", "name": "Bull Put Spread",  "legs": 2, "direction": "bullish", "defined_risk": True,  "net": "credit", "needs_width": True},
    {"id": "bear_put_spread", "name": "Bear Put Spread",  "legs": 2, "direction": "bearish", "defined_risk": True,  "net": "debit",  "needs_width": True},
    {"id": "straddle",        "name": "Long Straddle",    "legs": 2, "direction": "neutral", "defined_risk": True,  "net": "debit",  "needs_width": False},
    {"id": "strangle",        "name": "Long Strangle",    "legs": 2, "direction": "neutral", "defined_risk": True,  "net": "debit",  "needs_width": True},
    {"id": "iron_condor",     "name": "Iron Condor",      "legs": 4, "direction": "neutral", "defined_risk": True,  "net": "credit", "needs_width": True},
]

DEFINED_RISK_IDS = {c["id"] for c in CATALOG if c["defined_risk"]}


@dataclass(frozen=True)
class StructureSpec:
    """Everything needed to build a structure at a bar."""

    structure_type: str = "bear_call_spread"
    selection: str = "delta"          # "delta" | "pct_otm" | "absolute"
    short_delta: float = 0.30
    pct_otm: float = 0.05
    width: float = 5.0
    strikes: Optional[List[float]] = None
    dte_bars: int = 30
    contracts: int = 1
    grid_spacing: float = 5.0

    @property
    def grid(self) -> StrikeGrid:
        return StrikeGrid(spacing=self.grid_spacing)


def _anchor_strike(spec: StructureSpec, S: float, T: float, r: float, sigma: float, kind: str) -> float:
    """Resolve the primary/anchor strike per the selection mode."""
    grid = spec.grid
    if spec.selection == "absolute" and spec.strikes:
        return nearest_strike(S, spec.strikes[0], grid)
    if spec.selection == "pct_otm":
        return strike_for_pct_otm(S, spec.pct_otm, kind, grid)
    # default: delta
    return strike_for_delta(S, T, r, sigma, spec.short_delta, kind, grid=grid)


def _leg(kind: str, strike: float, qty: int, S: float, T: float, r: float, sigma: float,
         expiry_index: int, open_index: int) -> OptionLeg:
    price = bs_price(S, strike, T, r, sigma, kind)
    return OptionLeg(
        kind=kind,
        strike=float(strike),
        expiry_index=expiry_index,
        quantity=int(qty),
        entry_price=float(price),
        entry_index=open_index,
    )


def build_structure(
    spec: StructureSpec,
    S: float,
    sigma: float,
    r: float,
    open_index: int,
    structure_id: str,
) -> OptionStructure:
    """Build a concrete, priced structure. ``S`` is the spot (fill price),
    ``sigma`` the IV for this bar, ``r`` the risk-free rate."""
    st = spec.structure_type
    if st not in STRUCTURE_TYPES:
        raise ValueError(f"Unknown structure type: {st}")
    T = max(spec.dte_bars, 0) / TRADING_DAYS
    expiry_index = open_index + max(spec.dte_bars, 0)
    n = max(int(spec.contracts), 1)
    grid = spec.grid
    legs: List[OptionLeg] = []

    def mk(kind, strike, qty):
        legs.append(_leg(kind, strike, qty, S, T, r, sigma, expiry_index, open_index))

    if st == "long_call":
        mk("call", _anchor_strike(spec, S, T, r, sigma, "call"), n)
    elif st == "long_put":
        mk("put", _anchor_strike(spec, S, T, r, sigma, "put"), n)
    elif st == "short_call":
        mk("call", _anchor_strike(spec, S, T, r, sigma, "call"), -n)
    elif st == "short_put":
        mk("put", _anchor_strike(spec, S, T, r, sigma, "put"), -n)

    elif st == "bull_call_spread":  # debit: long lower call, short higher call
        k1 = _anchor_strike(spec, S, T, r, sigma, "call")
        k2 = grid.snap(k1 + spec.width)
        mk("call", k1, n)
        mk("call", k2, -n)
    elif st == "bear_call_spread":  # credit: short lower call, long higher call
        k1 = _anchor_strike(spec, S, T, r, sigma, "call")
        k2 = grid.snap(k1 + spec.width)
        mk("call", k1, -n)
        mk("call", k2, n)
    elif st == "bull_put_spread":   # credit: short higher put, long lower put
        k1 = _anchor_strike(spec, S, T, r, sigma, "put")
        k2 = grid.snap(k1 - spec.width)
        mk("put", k1, -n)
        mk("put", k2, n)
    elif st == "bear_put_spread":   # debit: long higher put, short lower put
        k1 = _anchor_strike(spec, S, T, r, sigma, "put")
        k2 = grid.snap(k1 - spec.width)
        mk("put", k1, n)
        mk("put", k2, -n)

    elif st == "straddle":          # long call + long put, same (ATM) strike
        k = nearest_strike(S, S, grid)
        mk("call", k, n)
        mk("put", k, n)
    elif st == "strangle":          # long OTM call + long OTM put
        kc = strike_for_pct_otm(S, spec.pct_otm, "call", grid)
        kp = strike_for_pct_otm(S, spec.pct_otm, "put", grid)
        mk("call", kc, n)
        mk("put", kp, n)
    elif st == "iron_condor":       # short put spread + short call spread
        sc = _anchor_strike(spec, S, T, r, sigma, "call")   # short call
        lc = grid.snap(sc + spec.width)                     # long call
        sp = _anchor_strike(spec, S, T, r, sigma, "put")    # short put
        lp = grid.snap(sp - spec.width)                     # long put
        mk("call", sc, -n)
        mk("call", lc, n)
        mk("put", sp, -n)
        mk("put", lp, n)

    return OptionStructure(
        id=structure_id,
        structure_type=st,
        legs=tuple(legs),
        open_index=open_index,
        label=st,
    )

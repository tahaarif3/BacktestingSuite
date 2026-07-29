"""Option instrument model: legs, structures, margin.

Quantities are **signed contracts** (+long / -short). Cash and P&L multiply by
:data:`options.pricing.CONTRACT_MULTIPLIER` (100). Expiry is stored as an
absolute *bar index* so the ledger can settle deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from options.pricing import CONTRACT_MULTIPLIER

# All structure templates the layer understands.
STRUCTURE_TYPES = (
    "long_call",
    "long_put",
    "short_call",
    "short_put",
    "bull_call_spread",
    "bear_call_spread",
    "bull_put_spread",
    "bear_put_spread",
    "straddle",
    "strangle",
    "iron_condor",
)


@dataclass(frozen=True)
class OptionLeg:
    """A single option leg. ``entry_price`` is the per-share premium at fill."""

    kind: str            # "call" | "put"
    strike: float
    expiry_index: int    # absolute bar index at which the leg settles
    quantity: int        # signed contracts: +long / -short
    entry_price: float   # per-share premium paid(+)/received(-) at open
    entry_index: int

    @property
    def is_short(self) -> bool:
        return self.quantity < 0


@dataclass(frozen=True)
class OptionStructure:
    """A named collection of legs opened together (one expiry)."""

    id: str
    structure_type: str
    legs: Tuple[OptionLeg, ...]
    open_index: int
    label: str = ""

    @property
    def expiry_index(self) -> int:
        return max(leg.expiry_index for leg in self.legs)

    @property
    def contracts(self) -> int:
        """Nominal contract count = max |leg quantity| (spreads are 1:1)."""
        return max((abs(leg.quantity) for leg in self.legs), default=0)

    @property
    def net_premium_per_share(self) -> float:
        """Signed net premium per share at open: >0 debit paid, <0 credit received."""
        return sum(leg.quantity * leg.entry_price for leg in self.legs)

    @property
    def net_cash_at_open(self) -> float:
        """Signed cash effect at open (before costs): debit is negative cash."""
        return -self.net_premium_per_share * CONTRACT_MULTIPLIER

    def intrinsic_value(self, spot: float) -> float:
        """Total intrinsic value of the whole structure at ``spot`` (per structure,
        already ×multiplier×contracts)."""
        total = 0.0
        for leg in self.legs:
            if leg.kind == "call":
                intr = max(spot - leg.strike, 0.0)
            else:
                intr = max(leg.strike - spot, 0.0)
            total += leg.quantity * intr * CONTRACT_MULTIPLIER
        return total

    # --- risk profile (evaluated at expiry across a strike grid) -------------

    def _payoff_at(self, spot: float) -> float:
        """P&L at expiry for a given terminal spot (per structure, in $)."""
        payoff = self.intrinsic_value(spot)
        # entry premium: long paid (cost), short received (credit)
        entry = -self.net_premium_per_share * CONTRACT_MULTIPLIER
        return payoff + entry

    def _payoff_bounds(self) -> Tuple[float, float]:
        """(max_profit, max_loss) sampled across strikes + tails. max_loss is
        returned as a negative number; +inf magnitude when undefined."""
        strikes = sorted({leg.strike for leg in self.legs})
        lo, hi = strikes[0], strikes[-1]
        span = max(hi - lo, hi * 0.5, 1.0)
        samples = [0.0, lo, hi]
        # midpoints between strikes
        for a, b in zip(strikes, strikes[1:]):
            samples.append((a + b) / 2.0)
        # tails far below/above to detect unbounded legs
        samples.append(max(hi + span * 5.0, hi * 3.0))
        samples.append(max(lo - span * 5.0, 0.0))
        payoffs = [self._payoff_at(s) for s in samples]

        max_profit = max(payoffs)
        max_loss = min(payoffs)

        # Detect unbounded profit/loss by pushing the tails much further.
        far_hi = self._payoff_at(hi * 20.0 + 1000.0)
        far_lo = self._payoff_at(0.0)
        if far_hi > max_profit * 5.0 and far_hi > 0:
            max_profit = float("inf")
        if far_lo < max_loss * 5.0 and far_lo < 0:
            max_loss = float("-inf")
        # A far-hi very negative (naked short call) → unbounded loss.
        if far_hi < max_loss:
            max_loss = float("-inf")
        return max_profit, max_loss

    @property
    def max_profit(self) -> float:
        return self._payoff_bounds()[0]

    @property
    def max_loss(self) -> float:
        """Negative number (or -inf if undefined)."""
        return self._payoff_bounds()[1]

    @property
    def is_defined_risk(self) -> bool:
        return self.max_loss != float("-inf")

    @property
    def breakevens(self) -> Tuple[float, ...]:
        """Terminal spots where expiry P&L crosses zero (sampled + refined)."""
        strikes = sorted({leg.strike for leg in self.legs})
        lo, hi = strikes[0], strikes[-1]
        span = max(hi - lo, hi * 0.5, 1.0)
        grid = [max(lo - span * 3.0, 0.01)]
        step = (hi + span * 3.0 - grid[0]) / 400.0
        for i in range(1, 401):
            grid.append(grid[0] + step * i)
        crossings = []
        prev_s = grid[0]
        prev_p = self._payoff_at(prev_s)
        for s in grid[1:]:
            p = self._payoff_at(s)
            if prev_p == 0.0:
                crossings.append(prev_s)
            elif (prev_p < 0.0) != (p < 0.0):
                # linear interpolate the zero crossing
                frac = prev_p / (prev_p - p) if (prev_p - p) != 0 else 0.5
                crossings.append(prev_s + frac * (s - prev_s))
            prev_s, prev_p = s, p
        # dedupe near-equal
        out = []
        for c in crossings:
            if not any(abs(c - o) < 1e-6 for o in out):
                out.append(round(c, 4))
        return tuple(out)

    def margin_requirement(self, spot: float, margin_policy: str = "defined_risk") -> float:
        """Buying-power reduction to open this structure.

        Defined-risk structures use |max_loss|. Undefined-risk (naked short)
        structures require ``margin_policy == 'reg_t'`` and use an approximate
        Reg-T formula; otherwise this returns +inf (caller should reject).
        """
        ml = self.max_loss
        if ml != float("-inf"):
            return abs(ml)
        if margin_policy != "reg_t":
            return float("inf")
        # Approximate Reg-T naked-short margin: 20% of underlying - OTM amount,
        # floored at 10% of strike, plus premium received, per contract.
        req = 0.0
        for leg in self.legs:
            if leg.quantity >= 0:
                continue
            if leg.kind == "call":
                otm = max(leg.strike - spot, 0.0)
            else:
                otm = max(spot - leg.strike, 0.0)
            base = max(0.20 * spot - otm, 0.10 * leg.strike)
            req += (base + leg.entry_price) * CONTRACT_MULTIPLIER * abs(leg.quantity)
        return req

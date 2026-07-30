"""Deterministic ranking of competing signals on a given day.

Only information available at the signal close is used (no future prices)."""

from __future__ import annotations

from typing import Dict, List

from portfolio_backtest.config import PortfolioBacktestConfig


def _norm(values: List[float]) -> List[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-12:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def rank_candidates(candidates: List[Dict], cfg: PortfolioBacktestConfig) -> List[Dict]:
    """Return candidates sorted best-first."""
    if not candidates:
        return []
    if cfg.rank_mode == "composite":
        rs_n = _norm([c["rs"] for c in candidates])
        vol_n = _norm([c["volume_ratio"] for c in candidates])
        bo_n = _norm([c["breakout_pct"] for c in candidates])
        for c, r, v, b in zip(candidates, rs_n, vol_n, bo_n):
            c["score"] = cfg.w_rs * r + cfg.w_volume * v + cfg.w_breakout * b
        return sorted(candidates, key=lambda c: c["score"], reverse=True)
    # default: relative strength, then volume ratio, then dollar volume
    for c in candidates:
        c["score"] = c["rs"]
    return sorted(candidates, key=lambda c: (c["rs"], c["volume_ratio"], c["dollar_vol"]), reverse=True)

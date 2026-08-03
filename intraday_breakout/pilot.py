"""Causal pilot for the premarket psychological-resistance breakout.

The module deliberately keeps the daily, premarket, opening-five-minute and
post-entry clocks separate.  It is a research scanner/trade logger, not a claim
that free recent intraday data validates a durable edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from math import exp, log
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

NY_TZ = "America/New_York"


@dataclass(frozen=True)
class IntradayBreakoutConfig:
    daily_lookback: int = 504
    daily_pivot_span: int = 5
    cluster_tolerance_pct: float = 0.005
    cluster_tolerance_atr: float = 0.25
    min_level_touches: int = 3
    min_level_span_days: int = 20
    recency_half_life: int = 126
    max_level_distance_pct: float = 0.10
    adv_window: int = 20
    min_avg_daily_volume: float = 10_000_000.0
    minute_pivot_span: int = 2
    premarket_trend_start: time = time(9, 0)
    min_premarket_volume: float = 100_000.0
    min_relative_overnight_return: float = 0.0
    premarket_close_location_min: float = 0.75
    opening_close_location_min: float = 0.75
    opening_volume_window: int = 20
    opening_volume_mult: float = 1.0
    min_opening_volume_sessions: int = 5
    stop_buffer_first5_range: float = 0.10
    min_stop_pct: float = 0.0025
    max_stop_pct: float = 0.05
    max_entry_extension_pct: float = 0.02
    entry_slippage_bps: float = 10.0
    exit_slippage_bps: float = 10.0
    risk_dollars: float = 100.0
    time_exit: time = time(15, 55)


def normalize_ohlcv(frame: pd.DataFrame, *, intraday: bool = False) -> pd.DataFrame:
    """Return sorted lowercase OHLCV with a consistent datetime index."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    d = frame.copy()
    if isinstance(d.columns, pd.MultiIndex):
        # Single-symbol downloads sometimes retain a ticker level.
        d.columns = [str(c[0]).lower() for c in d.columns]
    else:
        d.columns = [str(c).lower() for c in d.columns]
    required = ["open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in d.columns]
    if missing:
        raise ValueError(f"OHLCV data missing columns: {', '.join(missing)}")
    d = d[required].apply(pd.to_numeric, errors="coerce")
    d.index = pd.DatetimeIndex(d.index)
    if intraday:
        if d.index.tz is None:
            d.index = d.index.tz_localize(NY_TZ, ambiguous="infer", nonexistent="shift_forward")
        else:
            d.index = d.index.tz_convert(NY_TZ)
    elif d.index.tz is not None:
        d.index = d.index.tz_convert(NY_TZ).tz_localize(None)
    return d[~d.index.duplicated(keep="last")].sort_index().dropna(subset=["open", "high", "low", "close"])


def _atr(d: pd.DataFrame, window: int = 20) -> pd.Series:
    pc = d["close"].shift(1)
    tr = pd.concat(
        [d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window, min_periods=window).mean()


def _pivots(values: np.ndarray, span: int, mode: str) -> List[int]:
    out: List[int] = []
    for i in range(span, len(values) - span):
        window = values[i - span : i + span + 1]
        if not np.isfinite(window).all():
            continue
        if mode == "high" and values[i] == np.max(window) and np.sum(window == values[i]) == 1:
            out.append(i)
        elif mode == "low" and values[i] == np.min(window) and np.sum(window == values[i]) == 1:
            out.append(i)
    return out


def detect_daily_resistance(
    daily: pd.DataFrame,
    session_date: date,
    cfg: IntradayBreakoutConfig,
) -> Optional[Dict[str, Any]]:
    """Find the strongest confirmed daily pivot cluster known before session."""
    d = normalize_ohlcv(daily)
    d = d[d.index.date < session_date].tail(cfg.daily_lookback)
    warm = max(20, cfg.adv_window, cfg.daily_pivot_span * 2 + 1)
    if len(d) < warm:
        return None
    atr = _atr(d, 20)
    latest_atr = float(atr.iloc[-1])
    prev_close = float(d["close"].iloc[-1])
    adv20 = float(d["volume"].tail(cfg.adv_window).mean())
    if not np.isfinite(latest_atr) or latest_atr <= 0:
        return None

    raw: List[Dict[str, Any]] = []
    for kind, col in (("high", "high"), ("low", "low")):
        for i in _pivots(d[col].to_numpy(float), cfg.daily_pivot_span, kind):
            price = float(d[col].iloc[i])
            a = float(atr.iloc[i]) if np.isfinite(atr.iloc[i]) and atr.iloc[i] > 0 else latest_atr
            if kind == "high":
                wick = price - max(float(d["open"].iloc[i]), float(d["close"].iloc[i]))
            else:
                wick = min(float(d["open"].iloc[i]), float(d["close"].iloc[i])) - price
            raw.append({
                "price": price,
                "kind": kind,
                "index": i,
                "date": pd.Timestamp(d.index[i]),
                "rejection": max(0.0, wick / a),
                "bars_ago": len(d) - 1 - i,
            })
    if not raw:
        return None

    tol_abs = max(prev_close * cfg.cluster_tolerance_pct, latest_atr * cfg.cluster_tolerance_atr)
    clusters: List[List[Dict[str, Any]]] = []
    for pivot in sorted(raw, key=lambda p: p["price"]):
        best: Optional[List[Dict[str, Any]]] = None
        best_gap = float("inf")
        for cluster in clusters:
            center = float(np.median([p["price"] for p in cluster]))
            gap = abs(pivot["price"] - center)
            if gap <= tol_abs and gap < best_gap:
                best, best_gap = cluster, gap
        if best is None:
            clusters.append([pivot])
        else:
            best.append(pivot)

    candidates: List[Dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) < cfg.min_level_touches:
            continue
        dates = [p["date"] for p in cluster]
        span_days = int((max(dates) - min(dates)).days)
        if span_days < cfg.min_level_span_days:
            continue
        center = float(np.median([p["price"] for p in cluster]))
        if center <= prev_close or center > prev_close * (1.0 + cfg.max_level_distance_pct):
            continue
        weighted = 0.0
        for p in cluster:
            recency = exp(-log(2.0) * p["bars_ago"] / cfg.recency_half_life)
            weighted += recency * (1.0 + min(3.0, p["rejection"]))
        spread_mult = 1.0 + min(1.0, log(1.0 + span_days) / log(253.0))
        score = weighted * spread_mult
        candidates.append({
            "level_center": center,
            "level_lower": center - tol_abs,
            "level_upper": center + tol_abs,
            "level_score": score,
            "level_touches": len(cluster),
            "level_span_days": span_days,
            "level_last_touch": max(dates),
            "prev_close": prev_close,
            "adv20": adv20,
            "daily_atr20": latest_atr,
        })
    return max(candidates, key=lambda x: x["level_score"], default=None)


def _slice_day(frame: pd.DataFrame, day: date, start: time, end: time) -> pd.DataFrame:
    mask = (frame.index.date == day) & (frame.index.time >= start) & (frame.index.time <= end)
    return frame.loc[mask]


def _vwap(d: pd.DataFrame) -> float:
    vol = d["volume"].clip(lower=0).fillna(0.0)
    denom = float(vol.sum())
    typical = (d["high"] + d["low"] + d["close"]) / 3.0
    if denom <= 0:
        # Yahoo currently emits extended-hours prices with zero volume.  A
        # time-weighted typical price is an explicit pilot proxy, never called
        # a true VWAP in the report.
        return float(typical.mean())
    return float((typical * vol).sum() / denom)


def _confirmed_hh_hl(d: pd.DataFrame, span: int) -> Tuple[bool, Dict[str, float]]:
    hi = _pivots(d["high"].to_numpy(float), span, "high")
    lo = _pivots(d["low"].to_numpy(float), span, "low")
    detail: Dict[str, float] = {}
    if len(hi) >= 2:
        detail.update(prev_swing_high=float(d["high"].iloc[hi[-2]]), last_swing_high=float(d["high"].iloc[hi[-1]]))
    if len(lo) >= 2:
        detail.update(prev_swing_low=float(d["low"].iloc[lo[-2]]), last_swing_low=float(d["low"].iloc[lo[-1]]))
    ok = len(hi) >= 2 and len(lo) >= 2 and d["high"].iloc[hi[-1]] > d["high"].iloc[hi[-2]] and d["low"].iloc[lo[-1]] > d["low"].iloc[lo[-2]]
    return bool(ok), detail


def _opening_volume_baseline(minute: pd.DataFrame, session_date: date, window: int) -> Tuple[float, int]:
    prior = minute[minute.index.date < session_date]
    totals: List[float] = []
    for day in sorted(set(prior.index.date), reverse=True)[:window]:
        first5 = _slice_day(prior, day, time(9, 30), time(9, 34))
        if len(first5) == 5:
            totals.append(float(first5["volume"].sum()))
    return (float(np.median(totals)), len(totals)) if totals else (float("nan"), 0)


def scan_symbol_day(
    symbol: str,
    session_date: date,
    daily: pd.DataFrame,
    minute: pd.DataFrame,
    spy_daily: pd.DataFrame,
    spy_minute: pd.DataFrame,
    cfg: IntradayBreakoutConfig,
) -> Dict[str, Any]:
    """Return a complete filter audit; ``signal`` is true only if all pass."""
    m = normalize_ohlcv(minute, intraday=True)
    sm = normalize_ohlcv(spy_minute, intraday=True)
    level = detect_daily_resistance(daily, session_date, cfg)
    row: Dict[str, Any] = {
        "ticker": symbol,
        "date": session_date.isoformat(),
        "premarket_candidate": False,
        "signal": False,
    }
    if level is None:
        return {**row, "reject_reason": "no_valid_resistance"}
    row.update(level)
    if level["adv20"] <= cfg.min_avg_daily_volume:
        return {**row, "reject_reason": "adv20"}

    sd = normalize_ohlcv(spy_daily)
    sd = sd[sd.index.date < session_date]
    if sd.empty:
        return {**row, "reject_reason": "missing_spy_previous_close"}
    stock_pre = _slice_day(m, session_date, time(4, 0), time(9, 29))
    spy_pre = _slice_day(sm, session_date, time(4, 0), time(9, 29))
    if stock_pre.empty or spy_pre.empty:
        return {**row, "reject_reason": "missing_premarket"}
    stock_last = float(stock_pre["close"].iloc[-1])
    spy_last = float(spy_pre["close"].iloc[-1])
    stock_overnight = stock_last / level["prev_close"] - 1.0
    spy_prev = float(sd["close"].iloc[-1])
    spy_overnight = spy_last / spy_prev - 1.0
    relative = stock_overnight - spy_overnight
    pre_vwap = _vwap(stock_pre)
    pre_high, pre_low = float(stock_pre["high"].max()), float(stock_pre["low"].min())
    pre_loc = (stock_last - pre_low) / (pre_high - pre_low) if pre_high > pre_low else 0.0
    pre_vol = float(stock_pre["volume"].sum())
    premarket_volume_supported = bool((stock_pre["volume"] > 0).any())
    trend = stock_pre[stock_pre.index.time >= cfg.premarket_trend_start]
    hh_hl, swing = _confirmed_hh_hl(trend, cfg.minute_pivot_span) if len(trend) >= 8 else (False, {})
    row.update({
        "stock_overnight_return": stock_overnight,
        "spy_overnight_return": spy_overnight,
        "relative_overnight_return": relative,
        "premarket_vwap": pre_vwap,
        "premarket_last": stock_last,
        "premarket_high": pre_high,
        "premarket_low": pre_low,
        "premarket_close_location": pre_loc,
        "premarket_volume": pre_vol,
        "premarket_volume_supported": premarket_volume_supported,
        "premarket_reference_mode": "vwap" if premarket_volume_supported else "twap_proxy",
        "hh_hl": hh_hl,
        **swing,
    })
    pre_filters = [
        (stock_overnight > 0, "negative_overnight"),
        (relative > cfg.min_relative_overnight_return, "relative_overnight"),
        (np.isfinite(pre_vwap) and stock_last > pre_vwap, "below_premarket_vwap"),
        (pre_loc >= cfg.premarket_close_location_min, "premarket_close_location"),
        (not premarket_volume_supported or pre_vol >= cfg.min_premarket_volume, "premarket_volume"),
        (hh_hl, "no_confirmed_hh_hl"),
    ]
    for passed, reason in pre_filters:
        if not passed:
            return {**row, "reject_reason": reason}

    # This is what the trader could see in the scanner at 9:29.  The opening
    # breakout is a later event and must not be folded into this label.
    row["premarket_candidate"] = True

    first5 = _slice_day(m, session_date, time(9, 30), time(9, 34))
    spy5 = _slice_day(sm, session_date, time(9, 30), time(9, 34))
    if len(first5) != 5 or len(spy5) != 5:
        return {**row, "reject_reason": "incomplete_first5"}
    o, h, l, c = (float(first5["open"].iloc[0]), float(first5["high"].max()),
                  float(first5["low"].min()), float(first5["close"].iloc[-1]))
    vol = float(first5["volume"].sum())
    clv = (c - l) / (h - l) if h > l else 0.0
    baseline, baseline_n = _opening_volume_baseline(m, session_date, cfg.opening_volume_window)
    stock_rth = c / o - 1.0
    spy_rth = float(spy5["close"].iloc[-1]) / float(spy5["open"].iloc[0]) - 1.0
    row.update({
        "first5_open": o, "first5_high": h, "first5_low": l, "first5_close": c,
        "first5_volume": vol, "first5_close_location": clv,
        "opening_volume_baseline": baseline, "opening_volume_baseline_n": baseline_n,
        "opening_relative_return": stock_rth - spy_rth,
    })
    open_filters = [
        (o <= level["level_upper"], "gapped_over_level"),
        (h > level["level_upper"], "did_not_cross_level"),
        (c > level["level_upper"], "did_not_close_above_level"),
        (c > o, "first5_not_green"),
        (clv >= cfg.opening_close_location_min, "first5_close_location"),
        (stock_rth - spy_rth > 0, "opening_relative_strength"),
    ]
    for passed, reason in open_filters:
        if not passed:
            return {**row, "reject_reason": reason}

    entry_bar = _slice_day(m, session_date, time(9, 35), time(9, 35))
    if entry_bar.empty:
        return {**row, "reject_reason": "missing_0935_entry_bar"}
    raw_entry = float(entry_bar["open"].iloc[0])
    if raw_entry > level["level_upper"] * (1.0 + cfg.max_entry_extension_pct):
        return {**row, "reject_reason": "entry_too_extended"}
    stop = min(l, level["level_lower"]) - cfg.stop_buffer_first5_range * (h - l)
    stop_pct = (raw_entry - stop) / raw_entry
    if stop_pct < cfg.min_stop_pct or stop_pct > cfg.max_stop_pct:
        return {**row, "reject_reason": "invalid_stop_distance", "raw_entry": raw_entry, "stop": stop, "stop_pct": stop_pct}
    return {**row, "signal": True, "reject_reason": "", "raw_entry": raw_entry, "stop": stop, "stop_pct": stop_pct}


def simulate_trade(
    signal: Dict[str, Any],
    minute: pd.DataFrame,
    cfg: IntradayBreakoutConfig,
    *,
    target_r: float = 2.0,
    scale_targets: Optional[Iterable[float]] = None,
) -> Dict[str, Any]:
    """Simulate one causal trade; stop wins all same-minute ambiguities."""
    if not signal.get("signal"):
        raise ValueError("simulate_trade requires a completed signal")
    m = normalize_ohlcv(minute, intraday=True)
    day = date.fromisoformat(str(signal["date"]))
    path = _slice_day(m, day, time(9, 35), cfg.time_exit)
    if path.empty:
        raise ValueError("No post-signal bars")
    raw_entry = float(signal["raw_entry"])
    entry = raw_entry * (1.0 + cfg.entry_slippage_bps / 10_000.0)
    original_stop = float(signal["stop"])
    risk_per_share = entry - original_stop
    if risk_per_share <= 0:
        raise ValueError("Non-positive risk")
    shares = max(1, int(cfg.risk_dollars // risk_per_share))
    remaining = float(shares)
    pnl = 0.0
    exits: List[Dict[str, Any]] = []
    targets = sorted(float(x) for x in (scale_targets or [target_r]))
    fractions = [1.0 / len(targets)] * len(targets)
    target_index = 0
    active_stop = original_stop
    pending_breakeven = False

    for ts, bar in path.iterrows():
        if pending_breakeven:
            active_stop = max(active_stop, entry)
            pending_breakeven = False
        if float(bar["low"]) <= active_stop:
            raw_exit = min(float(bar["open"]), active_stop)
            fill = raw_exit * (1.0 - cfg.exit_slippage_bps / 10_000.0)
            pnl += remaining * (fill - entry)
            exits.append({"time": ts, "reason": "stop", "shares": remaining, "price": fill})
            remaining = 0.0
            break
        while target_index < len(targets) and float(bar["high"]) >= entry + targets[target_index] * risk_per_share:
            raw_target = entry + targets[target_index] * risk_per_share
            fill = raw_target * (1.0 - cfg.exit_slippage_bps / 10_000.0)
            qty = remaining if target_index == len(targets) - 1 else min(remaining, shares * fractions[target_index])
            pnl += qty * (fill - entry)
            remaining -= qty
            exits.append({"time": ts, "reason": f"target_{targets[target_index]:g}R", "shares": qty, "price": fill})
            target_index += 1
            if target_index == 1 and remaining > 0:
                pending_breakeven = True
            if remaining <= 1e-9:
                break
        if remaining <= 1e-9:
            break

    if remaining > 1e-9:
        ts, bar = path.index[-1], path.iloc[-1]
        raw_exit = float(bar["open"])
        fill = raw_exit * (1.0 - cfg.exit_slippage_bps / 10_000.0)
        pnl += remaining * (fill - entry)
        exits.append({"time": ts, "reason": "time", "shares": remaining, "price": fill})
        remaining = 0.0

    risk_dollars = shares * risk_per_share
    realized_r = pnl / risk_dollars
    highs = path["high"].to_numpy(float)
    lows = path["low"].to_numpy(float)
    mfe_r = float((np.max(highs) - entry) / risk_per_share)
    mae_r = float((np.min(lows) - entry) / risk_per_share)
    return {
        **signal,
        "entry": entry,
        "shares": shares,
        "initial_risk_dollars": risk_dollars,
        "target_plan": "/".join(f"{x:g}R" for x in targets),
        "exit_time": exits[-1]["time"],
        "exit_reason": exits[-1]["reason"],
        "exit_price": exits[-1]["price"],
        "net_pnl": pnl,
        "realized_r": realized_r,
        "outcome": "win" if realized_r > 1e-12 else "loss" if realized_r < -1e-12 else "breakeven",
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "exit_legs": exits,
    }

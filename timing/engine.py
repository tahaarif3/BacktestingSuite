"""Exposure-based timing engine.

A strategy maps each bar to a target *exposure* (0 = all cash, 1 = fully in,
>1 = leveraged). The simulator holds shares + cash, rebalances toward the target
when it drifts past a band, pays a per-side trading cost on turnover, earns yield
on idle cash, and pays margin interest on borrowed (negative) cash. Long-only by
construction (exposure is clamped ≥ 0). No look-ahead: every signal at bar t uses
data through t and executes at t's close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd

TRADING_DAYS = 252.0


@dataclass
class TimingConfig:
    label: str = "Strategy"
    strategy: str = "buy_hold"   # buy_hold|ma|golden_cross|momentum|vol_target|vol_derisk|seasonal|dip
    # moving-average regime
    ma_type: str = "sma"         # sma|ema
    ma_period: int = 200
    signal_freq: str = "daily"   # daily|monthly (monthly = evaluate at month-end, hold through)
    band_pct: float = 0.0        # re-entry/exit hysteresis band around the MA
    # golden cross
    fast_period: int = 50
    slow_period: int = 200
    # momentum
    mom_lookback: int = 252
    require_ma: bool = False     # also require price > ma_period MA
    # volatility
    vol_window: int = 20
    vol_target: float = 0.15
    vol_cap: float = 1.0
    vol_thr: float = 0.20
    derisk_exposure: float = 0.5
    # seasonal (out of market during [out_start..out_end] months, inclusive)
    season_out_start: int = 5
    season_out_end: int = 10
    season_require_ma: bool = False
    # dip
    dip_lookback: int = 60
    dip_threshold: float = 0.10
    dip_base_exposure: float = 0.80
    # generic in/out exposure (leverage via exposure_in > 1)
    exposure_in: float = 1.0
    exposure_out: float = 0.0
    # simulator
    start_capital: float = 10000.0
    cost_pct: float = 0.0005
    cash_yield_annual: float = 0.045
    borrow_annual: float = 0.055
    rebalance_band: float = 0.03


@dataclass
class TimingResult:
    label: str
    dates: List[str]
    value: List[float]
    exposure: List[float]
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def _ma(close: pd.Series, kind: str, period: int) -> np.ndarray:
    if kind == "ema":
        return close.ewm(span=period, adjust=False).mean().to_numpy()
    return close.rolling(period).mean().to_numpy()


def _month_end(idx: pd.DatetimeIndex) -> np.ndarray:
    m = idx.month.to_numpy()
    flags = np.zeros(len(m), bool)
    if len(m):
        flags[:-1] = m[:-1] != m[1:]
        flags[-1] = True
    return flags


def target_exposure(cfg: TimingConfig, close: pd.Series) -> np.ndarray:
    px = close.to_numpy()
    idx = pd.DatetimeIndex(close.index)
    n = len(px)
    s = cfg.strategy

    if s == "buy_hold":
        return np.full(n, cfg.exposure_in)

    if s in ("ma", "golden_cross", "momentum", "seasonal"):
        if s == "ma":
            ma = _ma(close, cfg.ma_type, cfg.ma_period)
            if cfg.signal_freq == "monthly":
                me = _month_end(idx)
                sig = np.ones(n); state = 1.0
                for t in range(n):
                    if me[t] and not np.isnan(ma[t]):
                        state = 1.0 if px[t] > ma[t] else 0.0
                    sig[t] = state
            elif cfg.band_pct > 0:
                sig = np.ones(n); state = 1.0
                for t in range(n):
                    if not np.isnan(ma[t]):
                        if px[t] > ma[t] * (1 + cfg.band_pct):
                            state = 1.0
                        elif px[t] < ma[t] * (1 - cfg.band_pct):
                            state = 0.0
                    sig[t] = state
            else:
                sig = np.where(px > ma, 1.0, 0.0); sig[np.isnan(ma)] = 1.0
        elif s == "golden_cross":
            fast = _ma(close, cfg.ma_type, cfg.fast_period)
            slow = _ma(close, cfg.ma_type, cfg.slow_period)
            sig = np.where(fast > slow, 1.0, 0.0); sig[np.isnan(slow)] = 1.0
        elif s == "momentum":
            r = (close / close.shift(cfg.mom_lookback) - 1).to_numpy()
            sig = np.where(r > 0, 1.0, 0.0); sig[np.isnan(r)] = 1.0
            if cfg.require_ma:
                ma = _ma(close, cfg.ma_type, cfg.ma_period)
                mflag = np.where(px > ma, 1.0, 0.0); mflag[np.isnan(ma)] = 1.0
                sig = np.minimum(sig, mflag)
        else:  # seasonal
            month = idx.month.to_numpy()
            lo, hi = cfg.season_out_start, cfg.season_out_end
            out = (month >= lo) & (month <= hi) if lo <= hi else (month >= lo) | (month <= hi)
            sig = np.where(out, 0.0, 1.0).astype(float)
            if cfg.season_require_ma:
                ma = _ma(close, cfg.ma_type, cfg.ma_period)
                mflag = np.where(px > ma, 1.0, 0.0); mflag[np.isnan(ma)] = 1.0
                sig = np.minimum(sig, mflag)
        return np.where(sig >= 0.5, cfg.exposure_in, cfg.exposure_out)

    if s in ("vol_target", "vol_derisk"):
        logret = np.diff(np.log(px), prepend=np.log(px[0]))
        vol = pd.Series(logret).rolling(cfg.vol_window).std().to_numpy() * np.sqrt(TRADING_DAYS)
        if s == "vol_target":
            safe = np.where(np.isnan(vol) | (vol <= 0), cfg.vol_target, vol)
            return np.minimum(cfg.vol_cap, cfg.vol_target / safe)
        e = np.where(vol > cfg.vol_thr, cfg.derisk_exposure, cfg.exposure_in)
        e[np.isnan(vol)] = cfg.exposure_in
        return e

    if s == "dip":
        roll_high = close.rolling(cfg.dip_lookback).max().to_numpy()
        return np.where((~np.isnan(roll_high)) & (px < (1 - cfg.dip_threshold) * roll_high),
                        cfg.exposure_in, cfg.dip_base_exposure)

    return np.full(n, cfg.exposure_in)


def _simulate(cfg: TimingConfig, px: np.ndarray, idx, exposure: np.ndarray):
    n = len(px)
    cash = cfg.start_capital
    shares = 0.0
    vals = np.zeros(n)
    exp_curve = np.zeros(n)
    turnover = 0.0
    log: List[Dict[str, Any]] = []
    first = True
    for t in range(n):
        if cash > 0:
            cash *= (1 + cfg.cash_yield_annual / TRADING_DAYS)
        elif cash < 0:
            cash *= (1 + cfg.borrow_annual / TRADING_DAYS)
        value = cash + shares * px[t]
        cur = (shares * px[t]) / value if value > 0 else 0.0
        tgt = max(0.0, exposure[t])
        if first or abs(cur - tgt) > cfg.rebalance_band:
            tgt_dollars = tgt * value
            trade = tgt_dollars - shares * px[t]
            cost_paid = abs(trade) * cfg.cost_pct
            shares = tgt_dollars / px[t] if px[t] > 0 else 0.0
            cash = value - tgt_dollars - cost_paid
            turnover += abs(trade)
            if not first and abs(trade) > 1e-6:
                log.append({"date": idx[t].strftime("%Y-%m-%d"),
                            "action": "increase" if trade > 0 else "reduce",
                            "price": float(px[t]), "from_exposure": float(cur),
                            "to_exposure": float(tgt), "trade": float(trade),
                            "value": float(cash + shares * px[t])})
            first = False
        v = cash + shares * px[t]
        vals[t] = v
        exp_curve[t] = (shares * px[t]) / v if v > 0 else 0.0
    return vals, exp_curve, turnover, log


def run_timing(cfg: TimingConfig, prices: pd.DataFrame) -> TimingResult:
    close = prices["close"].astype(float)
    idx = pd.DatetimeIndex(close.index)
    px = close.to_numpy()
    n = len(px)
    if n < 30:
        raise ValueError("Not enough price history.")
    exposure = target_exposure(cfg, close)
    vals, exp_curve, turnover, log = _simulate(cfg, px, idx, exposure)

    years = max((idx[-1] - idx[0]).days / 365.25, 1e-9)
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if vals[0] > 0 else 0.0
    peak = np.maximum.accumulate(vals)
    mdd = float(((vals - peak) / np.where(peak == 0, 1, peak)).min())
    r = pd.Series(vals).pct_change().fillna(0.0)
    sharpe = float((r.mean() / r.std()) * np.sqrt(TRADING_DAYS)) if r.std() > 0 else 0.0
    downside = np.minimum(r.to_numpy(), 0.0)
    dstd = np.sqrt(np.mean(downside ** 2))
    sortino = float((r.mean() * TRADING_DAYS) / (dstd * np.sqrt(TRADING_DAYS))) if dstd > 0 else 0.0

    def snum(x):
        return 0.0 if (x is None or np.isnan(x) or np.isinf(x)) else float(x)

    summary = {
        "Final Value": snum(vals[-1]),
        "CAGR": snum(cagr),
        "Max Drawdown": snum(mdd),
        "Sharpe Ratio": snum(sharpe),
        "Sortino Ratio": snum(sortino),
        "Calmar Ratio": snum(cagr / abs(mdd)) if mdd < 0 else 0.0,
        "Avg Exposure": snum(np.mean(exp_curve)),
        "Turnover / yr": snum(turnover / cfg.start_capital / years),
        "Rebalances": len(log),
    }
    return TimingResult(
        label=cfg.label,
        dates=[d.strftime("%Y-%m-%d") for d in idx],
        value=[snum(v) for v in vals],
        exposure=[snum(e) for e in exp_curve],
        summary=summary,
        log=log,
    )

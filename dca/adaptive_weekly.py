"""Adaptive weekly SPY contribution sizing with causal next-open execution.

Every strategy receives the same owner contribution on the first trading day
of each ISO week.  Its purchase budget is decided from the *previous completed
bar* and filled at the current open.  Unspent contributions remain in cash;
there are no sales, shorts, leverage, or future-contribution borrowing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from dca.engine import TRADING_DAYS, annualized_irr


STRATEGY_LABELS = {
    "buy_hold": "Weekly buy & hold",
    "core_crash_reserve": "Core + crash reserve",
    "drawdown_ladder": "Drawdown ladder",
    "trend_confirmed_dip": "Trend-confirmed dip buyer",
    "trend_throttle_catchup": "Trend throttle + catch-up",
    "volatility_recovery": "Volatility throttle + recovery",
    "rsi_discount": "RSI discount buyer",
    "composite": "Composite opportunity score",
}


@dataclass
class AdaptiveWeeklyConfig:
    strategy: str = "buy_hold"
    label: str = ""
    weekly_amount: float = 25.0
    start: str = "2005-01-03"
    end: str = "2026-07-30"
    cash_yield_annual: float = 0.03
    cost_pct: float = 0.0005
    decision_frequency: str = "weekly"  # weekly|monthly|quarterly


@dataclass
class AdaptiveWeeklyResult:
    label: str
    daily: pd.DataFrame
    decisions: pd.DataFrame
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0.0)
    loss = -change.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    return result.where(avg_loss > 0, 100.0)


def build_adaptive_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    """Indicators known at each close; no shifting is done here."""
    close = prices["close"].astype(float)
    out = pd.DataFrame(index=prices.index)
    out["close"] = close
    out["sma20"] = close.rolling(20, min_periods=20).mean()
    out["sma50"] = close.rolling(50, min_periods=50).mean()
    out["sma200"] = close.rolling(200, min_periods=200).mean()
    out["sma200_rising"] = out["sma200"] > out["sma200"].shift(20)
    out["drawdown"] = close / close.cummax() - 1.0
    out["vol20"] = close.pct_change().rolling(20, min_periods=20).std(ddof=0) * np.sqrt(TRADING_DAYS)
    out["rsi14"] = _rsi(close, 14)
    out["above20"] = close > out["sma20"]
    out["above50"] = close > out["sma50"]
    out["above200"] = close > out["sma200"]
    out["cross_above200"] = out["above200"] & ~out["above200"].shift(1, fill_value=False)
    return out


def _first_trading_day_flags(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    iso = idx.isocalendar()
    keys = (iso.year.astype(int) * 100 + iso.week.astype(int)).to_numpy()
    eligible = (idx >= start) & (idx <= end)
    flags = np.zeros(len(idx), dtype=bool)
    last_key = None
    for i, key in enumerate(keys):
        if not eligible[i]:
            continue
        if last_key != key:
            flags[i] = True
            last_key = key
    return flags


def _decision_flags(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp,
                    frequency: str) -> np.ndarray:
    idx = pd.DatetimeIndex(index)
    if frequency == "weekly":
        return _first_trading_day_flags(idx, start, end)
    eligible = (idx >= start) & (idx <= end)
    if frequency == "monthly":
        keys = idx.year.to_numpy() * 100 + idx.month.to_numpy()
    elif frequency == "quarterly":
        keys = idx.year.to_numpy() * 10 + ((idx.month.to_numpy() - 1) // 3 + 1)
    else:
        raise ValueError("decision_frequency must be weekly, monthly, or quarterly")
    flags = np.zeros(len(idx), dtype=bool)
    prior = None
    for i, key in enumerate(keys):
        if eligible[i] and key != prior:
            flags[i] = True
            prior = key
    return flags


def _size_rule(strategy: str, row: pd.Series, state: Dict[str, int]) -> Tuple[float, str]:
    dd = float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0
    above20 = bool(row["above20"])
    above50 = bool(row["above50"])
    above200 = bool(row["above200"])
    rising200 = bool(row["sma200_rising"])
    cross200 = bool(row["cross_above200"])
    vol = float(row["vol20"]) if pd.notna(row["vol20"]) else 0.20
    rsi = float(row["rsi14"]) if pd.notna(row["rsi14"]) else 50.0

    if strategy == "buy_hold":
        return 1.0, "constant weekly purchase"

    if strategy == "core_crash_reserve":
        if dd <= -0.30:
            return 5.0, "30%+ drawdown"
        if dd <= -0.20:
            return 3.0, "20-30% drawdown"
        if dd <= -0.10:
            return 1.6, "10-20% drawdown"
        return 0.8, "build 20% crash reserve"

    if strategy == "drawdown_ladder":
        if dd <= -0.30:
            return 4.0, "30%+ drawdown"
        if dd <= -0.20:
            return 2.5, "20-30% drawdown"
        if dd <= -0.10:
            return 1.5, "10-20% drawdown"
        if dd <= -0.05:
            return 1.0, "5-10% drawdown"
        return 0.75, "within 5% of high"

    if strategy == "trend_confirmed_dip":
        if cross200:
            state["recovery_weeks"] = 4
        if state.get("recovery_weeks", 0) > 0:
            state["recovery_weeks"] -= 1
            return 3.0, "four-week SMA200 recovery release"
        if dd <= -0.20 and above50:
            return 3.0, "20% drawdown with SMA50 recovery"
        if dd <= -0.10 and above20:
            return 2.0, "10% drawdown with SMA20 recovery"
        if not above200 and not rising200:
            return 0.5, "below falling SMA200"
        return 1.0, "normal trend"

    if strategy == "trend_throttle_catchup":
        if cross200:
            state["catchup_weeks"] = 8
        if state.get("catchup_weeks", 0) > 0:
            state["catchup_weeks"] -= 1
            return 2.0, "eight-week SMA200 catch-up"
        if above200 and rising200:
            return 1.25, "above rising SMA200"
        if above200:
            return 1.0, "above non-rising SMA200"
        return 0.5, "below SMA200"

    if strategy == "volatility_recovery":
        if vol < 0.25 and above20:
            return 2.0, "volatility normalized above SMA20"
        if vol < 0.15:
            return 1.25, "low volatility"
        if vol < 0.25:
            return 1.0, "normal volatility"
        if vol < 0.35:
            return 0.75, "elevated volatility"
        return 0.5, "high volatility"

    if strategy == "rsi_discount":
        if rsi > 70:
            mult, reason = 0.5, "RSI above 70"
        elif rsi > 55:
            mult, reason = 0.75, "RSI 55-70"
        elif rsi >= 40:
            mult, reason = 1.0, "RSI 40-55"
        elif rsi >= 30:
            mult, reason = 1.5, "RSI 30-40"
        else:
            mult, reason = 3.0, "RSI below 30"
        if not above200 and not rising200 and mult > 1.5:
            return 1.5, f"{reason}; falling-SMA200 cap"
        return mult, reason

    if strategy == "composite":
        mult = 1.0
        reasons = []
        if not above200 and not rising200:
            mult -= 0.50
            reasons.append("below falling SMA200")
        if vol > 0.30:
            mult -= 0.25
            reasons.append("volatility >30%")
        if dd <= -0.10:
            mult += 0.50
            reasons.append("drawdown >10%")
        if dd <= -0.20:
            mult += 0.50
            reasons.append("drawdown >20%")
        if rsi < 35:
            mult += 0.50
            reasons.append("RSI <35")
        if above20 and not bool(row.get("above20_prev", False)):
            mult += 0.50
            reasons.append("SMA20 recovery")
        return min(3.0, max(0.25, mult)), "; ".join(reasons) or "neutral score"

    raise ValueError(f"Unknown adaptive weekly strategy: {strategy}")


def _unitized_nav(values: np.ndarray, external_flows: np.ndarray) -> np.ndarray:
    nav = np.ones(len(values), dtype=float)
    for t in range(len(values)):
        if t == 0 or values[t - 1] <= 0:
            nav[t] = values[t] / external_flows[t] if external_flows[t] > 0 else 1.0
        else:
            nav[t] = nav[t - 1] * ((values[t] - external_flows[t]) / values[t - 1])
    return nav


def run_adaptive_weekly(cfg: AdaptiveWeeklyConfig, prices: pd.DataFrame) -> AdaptiveWeeklyResult:
    required = {"open", "close"}
    if not required.issubset(prices.columns):
        raise ValueError("prices must contain open and close columns")
    frame = prices.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if start <= frame.index.min():
        raise ValueError("At least one pre-start bar is required for causal sizing.")
    indicators = build_adaptive_indicators(frame)
    indicators["above20_prev"] = indicators["above20"].shift(1, fill_value=False)
    trade_flags = _first_trading_day_flags(frame.index, start, end)
    review_flags = _decision_flags(frame.index, start, end, cfg.decision_frequency)

    n = len(frame)
    cash = shares = contributed = total_spent = total_cost = 0.0
    values = np.zeros(n)
    cash_curve = np.zeros(n)
    shares_curve = np.zeros(n)
    contributed_curve = np.zeros(n)
    exposure_curve = np.zeros(n)
    flow_curve = np.zeros(n)
    state: Dict[str, int] = {}
    multiplier = 1.0
    reason = "initial neutral size"
    cached_signal_i = max(0, int(np.flatnonzero(frame.index >= start)[0]) - 1)
    decision_updates = 0
    flows: List[Tuple[date, float]] = []
    decisions: List[Dict[str, Any]] = []

    for t, dt in enumerate(frame.index):
        if cash > 0:
            cash *= 1.0 + cfg.cash_yield_annual / TRADING_DAYS

        if review_flags[t]:
            cached_signal_i = t - 1
            multiplier, reason = _size_rule(cfg.strategy, indicators.iloc[cached_signal_i], state)
            decision_updates += 1

        if trade_flags[t]:
            cash_before_deposit = cash
            cash += cfg.weekly_amount
            contributed += cfg.weekly_amount
            flow_curve[t] = cfg.weekly_amount
            flows.append((dt.date(), -cfg.weekly_amount))

            signal_i = cached_signal_i
            signal = indicators.iloc[signal_i]
            desired = max(0.0, cfg.weekly_amount * multiplier)
            spend = min(desired, cash)
            raw_open = float(frame["open"].iloc[t])
            fill = raw_open * (1.0 + cfg.cost_pct)
            bought = spend / fill if fill > 0 else 0.0
            cost = bought * (fill - raw_open)
            shares += bought
            cash -= spend
            total_spent += spend
            total_cost += cost
            decisions.append({
                "trade_date": dt,
                "signal_date": frame.index[signal_i],
                "strategy": cfg.strategy,
                "multiplier": multiplier,
                "desired_purchase": desired,
                "actual_purchase": spend,
                "cash_before_deposit": cash_before_deposit,
                "cash_after_trade": cash,
                "open": raw_open,
                "fill": fill,
                "shares_bought": bought,
                "reason": reason,
                "decision_updated": bool(review_flags[t]),
                "signal_close": float(signal["close"]),
                "drawdown": float(signal["drawdown"]),
                "vol20": float(signal["vol20"]) if pd.notna(signal["vol20"]) else np.nan,
                "rsi14": float(signal["rsi14"]) if pd.notna(signal["rsi14"]) else np.nan,
            })

        close = float(frame["close"].iloc[t])
        value = cash + shares * close
        values[t] = value
        cash_curve[t] = cash
        shares_curve[t] = shares
        contributed_curve[t] = contributed
        exposure_curve[t] = shares * close / value if value > 0 else 0.0

    study_mask = (frame.index >= start) & (frame.index <= end)
    daily = pd.DataFrame({
        "value": values,
        "cash": cash_curve,
        "shares": shares_curve,
        "contributed": contributed_curve,
        "external_flow": flow_curve,
        "exposure": exposure_curve,
    }, index=frame.index).loc[study_mask]
    if daily.empty:
        raise ValueError("No prices in requested study period.")

    nav = _unitized_nav(daily["value"].to_numpy(), daily["external_flow"].to_numpy())
    daily["nav"] = nav
    daily["drawdown"] = nav / np.maximum.accumulate(nav) - 1.0
    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    final_value = float(daily["value"].iloc[-1])
    flows.append((daily.index[-1].date(), final_value))
    irr = annualized_irr(flows)
    twr_cagr = nav[-1] ** (1.0 / years) - 1.0 if nav[-1] > 0 else 0.0
    decisions_frame = pd.DataFrame(decisions)

    summary = {
        "Final Value": final_value,
        "Total Contributed": float(contributed),
        "Profit": final_value - contributed,
        "Money-Weighted Return (IRR)": float(irr),
        "Time-Weighted CAGR": float(twr_cagr),
        "Cash-Flow Adjusted Max Drawdown": float(daily["drawdown"].min()),
        "Avg Exposure": float(daily["exposure"].mean()),
        "Average Cash": float(daily["cash"].mean()),
        "Ending Cash": float(daily["cash"].iloc[-1]),
        "Total Purchase Cash": float(total_spent),
        "Execution Cost": float(total_cost),
        "Weekly Contributions": int(len(decisions_frame)),
        "Average Requested Multiplier": float(decisions_frame["multiplier"].mean()),
        "Decision Updates": int(decision_updates),
    }
    label = cfg.label or STRATEGY_LABELS[cfg.strategy]
    log = decisions_frame.assign(
        trade_date=lambda x: x["trade_date"].dt.strftime("%Y-%m-%d"),
        signal_date=lambda x: x["signal_date"].dt.strftime("%Y-%m-%d"),
    ).to_dict("records")
    return AdaptiveWeeklyResult(label, daily, decisions_frame, summary, log)

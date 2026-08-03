"""Causal SPY long/short timing with equal weekly owner contributions.

Signals are calculated at a completed close and executed at the following
session's open.  The simulator supports signed exposure without treating short
sale proceeds as investable capital, charges stock-borrow and transaction costs,
and checks short maintenance margin at the open and intraday high.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from dca.adaptive_weekly import _first_trading_day_flags, _rsi, _unitized_nav
from dca.engine import TRADING_DAYS, annualized_irr


STRATEGY_LABELS = {
    "buy_hold": "Weekly buy & hold",
    "long_cash_sma200": "SMA200 long / cash",
    "symmetric_sma200": "SMA200 long / short",
    "falling_sma200_short": "Falling-SMA200 confirmed short",
    "half_short_confirmed": "Half-short confirmed bear",
    "golden_cross_long_short": "SMA50/200 long / short",
    "breakdown_short": "20-day breakdown short",
    "early_bear_harvest": "Early-bear short and harvest",
    "momentum20_long_short": "20-day momentum long / short",
    "momentum60_long_short": "60-day momentum long / short",
    "momentum120_long_short": "120-day momentum long / short",
    "trend_momentum_vote": "Trend + momentum confirmation",
    "channel_breakout_long_short": "20-day channel long / short",
    "composite_long_short": "Composite regime long / short",
}


@dataclass
class ShortWeeklyConfig:
    strategy: str = "buy_hold"
    label: str = ""
    weekly_amount: float = 25.0
    start: str = "2005-01-03"
    end: str = "2026-07-30"
    cash_yield_annual: float = 0.03
    short_borrow_annual: float = 0.01
    cost_pct: float = 0.0005
    rebalance_band: float = 0.03
    maintenance_margin: float = 0.30
    liquidation_lockout_days: int = 20
    decision_frequency: str = "daily"  # daily|weekly|monthly|quarterly
    take_profit_pct: float = 0.0


@dataclass
class ShortWeeklyResult:
    label: str
    daily: pd.DataFrame
    trades: pd.DataFrame
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def build_short_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    close = prices["close"].astype(float)
    out = pd.DataFrame(index=prices.index)
    out["close"] = close
    out["sma20"] = close.rolling(20, min_periods=20).mean()
    out["sma50"] = close.rolling(50, min_periods=50).mean()
    out["sma200"] = close.rolling(200, min_periods=200).mean()
    out["sma200_rising"] = out["sma200"] > out["sma200"].shift(20)
    out["ret20"] = close / close.shift(20) - 1.0
    out["ret60"] = close / close.shift(60) - 1.0
    out["ret120"] = close / close.shift(120) - 1.0
    out["prior_high20"] = close.shift(1).rolling(20, min_periods=20).max()
    out["prior_low20"] = close.shift(1).rolling(20, min_periods=20).min()
    out["drawdown"] = close / close.cummax() - 1.0
    out["vol20"] = close.pct_change().rolling(20, min_periods=20).std(ddof=0) * np.sqrt(TRADING_DAYS)
    out["rsi14"] = _rsi(close, 14)
    return out


def decision_flags(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp,
                   frequency: str) -> np.ndarray:
    """Flag scheduled decision sessions without looking past each session."""
    idx = pd.DatetimeIndex(index)
    eligible = (idx >= start) & (idx <= end)
    if frequency == "daily":
        return np.asarray(eligible, dtype=bool)
    if frequency == "weekly":
        keys = idx.isocalendar().year.astype(int).to_numpy() * 100 + idx.isocalendar().week.astype(int).to_numpy()
    elif frequency == "monthly":
        keys = idx.year.to_numpy() * 100 + idx.month.to_numpy()
    elif frequency == "quarterly":
        keys = idx.year.to_numpy() * 10 + ((idx.month.to_numpy() - 1) // 3 + 1)
    else:
        raise ValueError("decision_frequency must be daily, weekly, monthly, or quarterly")
    flags = np.zeros(len(idx), dtype=bool)
    prior = None
    for i, key in enumerate(keys):
        if eligible[i] and key != prior:
            flags[i] = True
            prior = key
    return flags


def target_exposure(strategy: str, indicators: pd.DataFrame,
                    evaluation_flags: np.ndarray | None = None) -> Tuple[np.ndarray, List[str]]:
    """Return close-known signed targets; the simulator shifts them one bar."""
    targets = np.ones(len(indicators), dtype=float)
    reasons = ["warm-up long"] * len(indicators)
    state = 1.0
    if evaluation_flags is None:
        evaluation_flags = np.ones(len(indicators), dtype=bool)
    if len(evaluation_flags) != len(indicators):
        raise ValueError("evaluation_flags must match indicators length")

    for i, row in enumerate(indicators.itertuples(index=False)):
        if not evaluation_flags[i]:
            targets[i] = targets[i - 1] if i else 1.0
            reasons[i] = reasons[i - 1] if i else "warm-up long"
            continue
        ready = pd.notna(row.sma200)
        above200 = ready and row.close > row.sma200
        falling200 = ready and not bool(row.sma200_rising)

        if strategy == "buy_hold":
            target, reason = 1.0, "constant long"
        elif not ready:
            target, reason = 1.0, "SMA200 warm-up"
        elif strategy == "long_cash_sma200":
            target, reason = (1.0, "above SMA200") if above200 else (0.0, "below SMA200")
        elif strategy == "symmetric_sma200":
            target, reason = (1.0, "above SMA200") if above200 else (-1.0, "below SMA200")
        elif strategy == "falling_sma200_short":
            if above200:
                target, reason = 1.0, "above SMA200"
            elif falling200:
                target, reason = -1.0, "below falling SMA200"
            else:
                target, reason = 0.0, "below but SMA200 not falling"
        elif strategy == "half_short_confirmed":
            confirmed = falling200 and pd.notna(row.ret20) and row.ret20 < 0
            if above200:
                target, reason = 1.0, "above SMA200"
            elif confirmed:
                target, reason = -0.5, "falling SMA200 and negative 20-day return"
            else:
                target, reason = 0.0, "unconfirmed bear"
        elif strategy == "golden_cross_long_short":
            if pd.isna(row.sma50):
                target, reason = 1.0, "moving-average warm-up"
            elif row.sma50 >= row.sma200:
                target, reason = 1.0, "SMA50 above SMA200"
            else:
                target, reason = -1.0, "SMA50 below SMA200"
        elif strategy == "breakdown_short":
            breakdown = falling200 and pd.notna(row.prior_low20) and row.close < row.prior_low20
            if above200:
                state, reason = 1.0, "above SMA200"
            elif breakdown:
                state, reason = -1.0, "new 20-day low below falling SMA200"
            elif state < 0 and row.close > row.sma20:
                state, reason = 0.0, "short covered above SMA20"
            else:
                state, reason = min(state, 0.0), "hold bear state"
            target = state
        elif strategy == "early_bear_harvest":
            breakdown = falling200 and pd.notna(row.prior_low20) and row.close < row.prior_low20
            stretched = row.drawdown <= -0.15 or (pd.notna(row.rsi14) and row.rsi14 < 30)
            if above200:
                state, reason = 1.0, "above SMA200"
            elif state < 0 and (stretched or row.close > row.sma20):
                state, reason = 0.0, "cover stretched or recovered decline"
            elif breakdown and not stretched:
                state, reason = -1.0, "early bear breakdown"
            elif state > 0:
                state, reason = 0.0, "below SMA200; await breakdown"
            else:
                reason = "hold bear state"
            target = state
        elif strategy in ("momentum20_long_short", "momentum60_long_short", "momentum120_long_short"):
            lookback = strategy.removeprefix("momentum").removesuffix("_long_short")
            momentum = getattr(row, f"ret{lookback}")
            if pd.isna(momentum):
                target, reason = 1.0, f"{lookback}-day momentum warm-up"
            elif momentum >= 0:
                target, reason = 1.0, f"positive {lookback}-day return"
            else:
                target, reason = -1.0, f"negative {lookback}-day return"
        elif strategy == "trend_momentum_vote":
            if above200 and pd.notna(row.ret60) and row.ret60 > 0:
                target, reason = 1.0, "above SMA200 with positive 60-day return"
            elif not above200 and falling200 and pd.notna(row.ret60) and row.ret60 < 0:
                target, reason = -1.0, "below falling SMA200 with negative 60-day return"
            else:
                target, reason = 0.0, "trend and momentum disagree"
        elif strategy == "channel_breakout_long_short":
            if pd.notna(row.prior_high20) and row.close > row.prior_high20:
                state, reason = 1.0, "close above prior 20-day high"
            elif pd.notna(row.prior_low20) and row.close < row.prior_low20:
                state, reason = -1.0, "close below prior 20-day low"
            else:
                reason = "hold channel direction"
            target = state
        elif strategy == "composite_long_short":
            score = 0
            score += 2 if above200 else -2
            score += 1 if bool(row.sma200_rising) else -1
            if pd.notna(row.ret20):
                score += 1 if row.ret20 > 0 else -1
            if pd.notna(row.ret60):
                score += 1 if row.ret60 > 0 else -1
            if pd.notna(row.sma50):
                score += 1 if row.sma50 > row.sma200 else -1
            if score >= 2:
                target, reason = 1.0, f"bull composite score {score}"
            elif score <= -2:
                target, reason = -1.0, f"bear composite score {score}"
            else:
                target, reason = 0.0, f"neutral composite score {score}"
        else:
            raise ValueError(f"Unknown short strategy: {strategy}")

        targets[i] = target
        reasons[i] = reason
    return targets, reasons


def _margin_ratio(cash: float, shares: float, price: float) -> float:
    short_value = abs(min(0.0, shares * price))
    if short_value <= 0:
        return float("inf")
    return (cash + shares * price) / short_value


def run_short_weekly(cfg: ShortWeeklyConfig, prices: pd.DataFrame,
                     prepared_indicators: pd.DataFrame | None = None) -> ShortWeeklyResult:
    required = {"open", "high", "close"}
    if cfg.take_profit_pct > 0:
        required.add("low")
    if not required.issubset(prices.columns):
        raise ValueError(f"prices must include {sorted(required)}")
    if cfg.strategy not in STRATEGY_LABELS:
        raise ValueError(f"Unknown short strategy: {cfg.strategy}")
    if cfg.take_profit_pct < 0:
        raise ValueError("take_profit_pct cannot be negative")

    frame = prices.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if start <= frame.index.min():
        raise ValueError("At least one pre-start bar is required for causal execution.")
    if prepared_indicators is None:
        indicators = build_short_indicators(frame)
    else:
        indicators = prepared_indicators.reindex(frame.index)
        if not indicators.index.equals(frame.index) or indicators["close"].isna().all():
            raise ValueError("prepared_indicators must align with prices")
    scheduled_decisions = decision_flags(frame.index, start, end, cfg.decision_frequency)
    signal_evaluations = np.zeros(len(frame), dtype=bool)
    decision_locations = np.flatnonzero(scheduled_decisions)
    signal_evaluations[np.maximum(0, decision_locations - 1)] = True
    targets, reasons = target_exposure(cfg.strategy, indicators, signal_evaluations)
    contribution_flags = _first_trading_day_flags(frame.index, start, end)

    cash = shares = contributed = turnover = trading_cost = borrow_cost = interest = 0.0
    prior_target: float | None = None
    active_target = 0.0
    active_reason = "await first decision"
    entry_price = 0.0
    take_profit_exits = 0
    tp_wait = False
    lockout = margin_calls = 0
    flows: List[Tuple[date, float]] = []
    records: List[Dict[str, Any]] = []
    n = len(frame)
    values = np.zeros(n)
    cash_curve = np.zeros(n)
    shares_curve = np.zeros(n)
    exposure_curve = np.zeros(n)
    contributed_curve = np.zeros(n)
    flow_curve = np.zeros(n)

    def cover(t: int, price: float, reason: str) -> None:
        nonlocal cash, shares, turnover, trading_cost, margin_calls, lockout
        nonlocal prior_target, active_target, entry_price, tp_wait
        notional = abs(shares * price)
        cost = notional * cfg.cost_pct
        cash += shares * price - cost
        turnover += notional
        trading_cost += cost
        shares = 0.0
        margin_calls += 1
        lockout = max(0, int(cfg.liquidation_lockout_days))
        prior_target = 0.0
        active_target = 0.0
        entry_price = 0.0
        tp_wait = True
        records.append({
            "trade_date": frame.index[t], "signal_date": frame.index[max(0, t - 1)],
            "action": "forced_cover", "reason": reason, "target_exposure": 0.0,
            "price": float(price), "trade_notional": float(notional), "cost": float(cost),
        })

    for t, dt in enumerate(frame.index):
        in_study = start <= dt <= end
        if not in_study:
            continue

        prev_close = float(frame["close"].iloc[t - 1])
        equity_prev = cash + shares * prev_close
        short_notional = abs(min(0.0, shares * prev_close))
        fee = short_notional * cfg.short_borrow_annual / TRADING_DAYS
        eligible_cash = max(0.0, equity_prev - abs(shares * prev_close))
        credit = eligible_cash * cfg.cash_yield_annual / TRADING_DAYS
        cash += credit - fee
        borrow_cost += fee
        interest += credit

        open_px = float(frame["open"].iloc[t])
        high_px = float(frame["high"].iloc[t])
        low_px = float(frame["low"].iloc[t]) if "low" in frame else open_px
        if shares < 0 and _margin_ratio(cash, shares, open_px) < cfg.maintenance_margin:
            cover(t, open_px, "open-gap maintenance breach")

        deposited = 0.0
        if contribution_flags[t]:
            deposited = float(cfg.weekly_amount)
            cash += deposited
            contributed += deposited
            flow_curve[t] = deposited
            flows.append((dt.date(), -deposited))

        signal_i = t - 1
        is_decision = bool(scheduled_decisions[t])
        if is_decision:
            active_target = float(np.clip(targets[signal_i], -1.0, 1.0))
            active_reason = reasons[signal_i]
            tp_wait = False
        desired = 0.0 if tp_wait else active_target
        if lockout > 0 and desired < 0:
            desired = 0.0
        equity_open = cash + shares * open_px
        current = shares * open_px / equity_open if equity_open > 0 else 0.0
        force = (deposited > 0 and not tp_wait) or is_decision or prior_target is None or desired != prior_target
        if equity_open > 0 and (force or abs(current - desired) > cfg.rebalance_band):
            # Solve target exposure on *post-cost* equity.  In particular, a
            # +1 target must spend the contribution net of fees rather than
            # create a tiny negative cash balance to pay those fees.
            cost = 0.0
            for _ in range(5):
                post_cost_equity = max(0.0, equity_open - cost)
                target_dollars = desired * post_cost_equity
                trade = target_dollars - shares * open_px
                cost = abs(trade) * cfg.cost_pct
            old_shares = shares
            shares += trade / open_px
            cash -= trade + cost
            turnover += abs(trade)
            trading_cost += cost
            records.append({
                "trade_date": dt, "signal_date": frame.index[signal_i],
                "action": "rebalance", "reason": active_reason,
                "target_exposure": desired, "prior_exposure": current,
                "price": open_px, "trade_notional": float(trade), "cost": float(cost),
            })
            prior_target = desired
            if abs(shares) < 1e-12:
                entry_price = 0.0
            elif abs(old_shares) < 1e-12 or np.sign(old_shares) != np.sign(shares):
                entry_price = open_px
            elif np.sign(trade) == np.sign(shares) and abs(shares) > abs(old_shares):
                added = abs(shares) - abs(old_shares)
                entry_price = ((abs(old_shares) * entry_price + added * open_px) / abs(shares))

        if shares < 0 and _margin_ratio(cash, shares, high_px) < cfg.maintenance_margin:
            cover(t, high_px, "intraday-high maintenance breach")

        if cfg.take_profit_pct > 0 and entry_price > 0 and shares != 0:
            if shares > 0:
                exit_price = entry_price * (1.0 + cfg.take_profit_pct)
                hit = high_px >= exit_price
            else:
                exit_price = entry_price * (1.0 - cfg.take_profit_pct)
                hit = low_px <= exit_price
            if hit:
                notional = abs(shares * exit_price)
                cost = notional * cfg.cost_pct
                closing_trade = -shares * exit_price
                cash += shares * exit_price - cost
                turnover += notional
                trading_cost += cost
                records.append({
                    "trade_date": dt, "signal_date": frame.index[signal_i],
                    "action": "take_profit", "reason": f"{cfg.take_profit_pct:.1%} target hit",
                    "target_exposure": 0.0, "prior_exposure": desired,
                    "price": float(exit_price), "trade_notional": float(closing_trade),
                    "cost": float(cost),
                })
                shares = 0.0
                entry_price = 0.0
                active_target = 0.0
                prior_target = 0.0
                tp_wait = True
                take_profit_exits += 1

        close_px = float(frame["close"].iloc[t])
        value = cash + shares * close_px
        values[t] = value
        cash_curve[t] = cash
        shares_curve[t] = shares
        contributed_curve[t] = contributed
        exposure_curve[t] = shares * close_px / value if value > 0 else 0.0
        if lockout > 0:
            lockout -= 1

    study_mask = (frame.index >= start) & (frame.index <= end)
    daily = pd.DataFrame({
        "value": values, "cash": cash_curve, "shares": shares_curve,
        "contributed": contributed_curve, "external_flow": flow_curve,
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
    twr = nav[-1] ** (1.0 / years) - 1.0 if nav[-1] > 0 else 0.0
    trades = pd.DataFrame(records)
    short_days = int((daily["exposure"] < -0.01).sum())

    summary = {
        "Final Value": final_value,
        "Total Contributed": float(contributed),
        "Profit": final_value - contributed,
        "Money-Weighted Return (IRR)": float(irr),
        "Time-Weighted CAGR": float(twr),
        "Cash-Flow Adjusted Max Drawdown": float(daily["drawdown"].min()),
        "Average Exposure": float(daily["exposure"].mean()),
        "Short Days": short_days,
        "Percent Days Short": short_days / len(daily),
        "Turnover": float(turnover),
        "Trading Cost": float(trading_cost),
        "Short Borrow Cost": float(borrow_cost),
        "Cash Interest": float(interest),
        "Margin Calls": int(margin_calls),
        "Take Profit Exits": int(take_profit_exits),
        "Minimum Cash": float(daily["cash"].min()),
        "Weekly Contributions": int(contribution_flags.sum()),
    }
    label = cfg.label or STRATEGY_LABELS[cfg.strategy]
    log = trades.assign(
        trade_date=lambda x: x["trade_date"].dt.strftime("%Y-%m-%d"),
        signal_date=lambda x: x["signal_date"].dt.strftime("%Y-%m-%d"),
    ).to_dict("records") if not trades.empty else []
    return ShortWeeklyResult(label, daily, trades, summary, log)

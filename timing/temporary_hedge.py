"""Core-long SPY portfolio with causal temporary short hedges.

The overlay implementation keeps a 1x long core and adds a 0.25x or 0.50x
short book.  The cash implementation sells the equivalent fraction of the long
book instead.  Both therefore have the same net market exposure before costs,
while the explicit overlay carries short borrow and extra implementation drag.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from dca.adaptive_weekly import _first_trading_day_flags, _unitized_nav
from dca.engine import TRADING_DAYS, annualized_irr
from timing.short_weekly import build_short_indicators, decision_flags


STRATEGY_LABELS = {
    "sma200": "Below-SMA200 hedge",
    "falling_sma200": "Falling-SMA200 hedge",
    "breakdown20": "20-day breakdown hedge",
    "volatility_breakdown": "Volatility-breakdown hedge",
    "drawdown_momentum": "Drawdown + momentum hedge",
    "fast_crash": "Fast-crash hedge",
}

EXIT_LABELS = {
    "signal_clear": "Trigger clears",
    "sma20_reversal": "SMA20 bullish reversal",
    "trail6_reversal": "6% rebound trail or SMA20",
    "profit10_reversal": "10% hedge profit or SMA20",
    "profit10_only": "10% decline only",
    "profit10_and_sma20": "10% decline then SMA20 recovery",
    "staged_profit10_sma20": "Half at 10% decline, rest above SMA20",
}


@dataclass
class HedgeConfig:
    strategy: str = "falling_sma200"
    vehicle: str = "short_overlay"  # short_overlay|derisk_cash
    hedge_fraction: float = 0.25
    decision_frequency: str = "weekly"
    exit_plan: str = "trail6_reversal"
    weekly_amount: float = 25.0
    start: str = "2005-01-03"
    end: str = "2026-07-30"
    cash_yield_annual: float = 0.03
    short_borrow_annual: float = 0.01
    cost_pct: float = 0.0005
    maintenance_margin: float = 0.30
    profit_target_pct: float = 0.10
    rebalance_on_contribution: bool = True


@dataclass
class HedgeResult:
    label: str
    daily: pd.DataFrame
    trades: pd.DataFrame
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def hedge_trigger(strategy: str, row: pd.Series) -> Tuple[bool, str]:
    ready = pd.notna(row["sma200"])
    above200 = ready and row["close"] > row["sma200"]
    falling200 = ready and not bool(row["sma200_rising"])
    ret20 = float(row["ret20"]) if pd.notna(row["ret20"]) else 0.0
    vol20 = float(row["vol20"]) if pd.notna(row["vol20"]) else 0.0
    drawdown = float(row["drawdown"]) if pd.notna(row["drawdown"]) else 0.0

    if strategy == "always":
        return True, "test hedge always active"
    if not ready:
        return False, "indicator warm-up"
    if strategy == "sma200":
        return not above200, "close below SMA200"
    if strategy == "falling_sma200":
        return not above200 and falling200, "close below falling SMA200"
    if strategy == "breakdown20":
        hit = (not above200 and falling200 and pd.notna(row["prior_low20"])
               and row["close"] < row["prior_low20"])
        return bool(hit), "new 20-day low below falling SMA200"
    if strategy == "volatility_breakdown":
        return not above200 and ret20 < 0 and vol20 > 0.30, "below SMA200, negative momentum, vol >30%"
    if strategy == "drawdown_momentum":
        return drawdown <= -0.10 and ret20 < 0, "10% drawdown with negative 20-day return"
    if strategy == "fast_crash":
        hit = pd.notna(row["sma50"]) and row["close"] < row["sma50"] and ret20 <= -0.08 and vol20 > 0.25
        return bool(hit), "below SMA50, 8% monthly loss, elevated volatility"
    raise ValueError(f"Unknown hedge strategy: {strategy}")


def run_temporary_hedge(cfg: HedgeConfig, prices: pd.DataFrame,
                        prepared_indicators: pd.DataFrame | None = None) -> HedgeResult:
    required = {"open", "high", "low", "close"}
    if not required.issubset(prices.columns):
        raise ValueError(f"prices must include {sorted(required)}")
    if cfg.strategy not in STRATEGY_LABELS and cfg.strategy != "always":
        raise ValueError(f"Unknown hedge strategy: {cfg.strategy}")
    if cfg.vehicle not in ("short_overlay", "derisk_cash"):
        raise ValueError("vehicle must be short_overlay or derisk_cash")
    if cfg.exit_plan not in EXIT_LABELS:
        raise ValueError(f"Unknown exit plan: {cfg.exit_plan}")
    if not 0 <= cfg.hedge_fraction <= 0.50:
        raise ValueError("hedge_fraction must be between 0 and 0.50")

    frame = prices.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if start <= frame.index.min():
        raise ValueError("At least one pre-start bar is required for causal execution.")
    indicators = (build_short_indicators(frame) if prepared_indicators is None
                  else prepared_indicators.reindex(frame.index))
    contribution_flags = _first_trading_day_flags(frame.index, start, end)
    review_flags = decision_flags(frame.index, start, end, cfg.decision_frequency)

    cash = long_shares = short_shares = contributed = 0.0
    turnover = trading_cost = borrow_cost = cash_interest = 0.0
    hedge_active = False
    hedge_armed = True
    hedge_entry = lowest_close = 0.0
    active_fraction = 0.0
    profit_target_hit = False
    hedge_entries = hedge_exits = margin_calls = 0
    flows: List[Tuple[date, float]] = []
    records: List[Dict[str, Any]] = []
    n = len(frame)
    values = np.zeros(n)
    long_curve = np.zeros(n)
    short_curve = np.zeros(n)
    cash_curve = np.zeros(n)
    net_curve = np.zeros(n)
    gross_curve = np.zeros(n)
    contributed_curve = np.zeros(n)
    flow_curve = np.zeros(n)

    def desired_books(active: bool, fraction: float | None = None) -> Tuple[float, float]:
        if not active:
            return 1.0, 0.0
        fraction = cfg.hedge_fraction if fraction is None else fraction
        if cfg.vehicle == "short_overlay":
            return 1.0, -fraction
        return 1.0 - fraction, 0.0

    def rebalance(t: int, price: float, active: bool, action: str, reason: str,
                  signal_i: int, fraction: float | None = None) -> None:
        nonlocal cash, long_shares, short_shares, turnover, trading_cost
        equity = cash + (long_shares + short_shares) * price
        if equity <= 0:
            return
        long_fraction, short_fraction = desired_books(active, fraction)
        cost = 0.0
        for _ in range(6):
            post_equity = max(0.0, equity - cost)
            target_long = long_fraction * post_equity
            target_short = short_fraction * post_equity
            long_trade = target_long - long_shares * price
            short_trade = target_short - short_shares * price
            cost = (abs(long_trade) + abs(short_trade)) * cfg.cost_pct
        long_shares += long_trade / price
        short_shares += short_trade / price
        cash -= long_trade + short_trade + cost
        turnover += abs(long_trade) + abs(short_trade)
        trading_cost += cost
        records.append({
            "trade_date": frame.index[t], "signal_date": frame.index[signal_i],
            "action": action, "reason": reason, "vehicle": cfg.vehicle,
            "hedge_fraction": (cfg.hedge_fraction if fraction is None else fraction) if active else 0.0,
            "price": float(price), "long_trade": float(long_trade),
            "short_trade": float(short_trade), "cost": float(cost),
        })

    def allocate_contribution(t: int, price: float, deposited: float,
                              signal_i: int) -> None:
        """Invest only new money, leaving the existing book untouched."""
        nonlocal cash, long_shares, short_shares, turnover, trading_cost
        long_fraction, short_fraction = desired_books(
            hedge_active, active_fraction if hedge_active else None)
        gross_fraction = abs(long_fraction) + abs(short_fraction)
        scale = deposited / (1.0 + gross_fraction * cfg.cost_pct)
        long_trade = long_fraction * scale
        short_trade = short_fraction * scale
        cost = (abs(long_trade) + abs(short_trade)) * cfg.cost_pct
        long_shares += long_trade / price
        short_shares += short_trade / price
        cash -= long_trade + short_trade + cost
        turnover += abs(long_trade) + abs(short_trade)
        trading_cost += cost
        records.append({
            "trade_date": frame.index[t], "signal_date": frame.index[signal_i],
            "action": "contribution_allocation", "reason": "allocate weekly contribution",
            "vehicle": cfg.vehicle,
            "hedge_fraction": active_fraction if hedge_active else 0.0,
            "price": float(price), "long_trade": float(long_trade),
            "short_trade": float(short_trade), "cost": float(cost),
        })

    for t, dt in enumerate(frame.index):
        if not (start <= dt <= end):
            continue
        signal_i = t - 1
        prev_close = float(frame["close"].iloc[signal_i])
        equity_prev = cash + (long_shares + short_shares) * prev_close
        short_notional = abs(short_shares * prev_close)
        fee = short_notional * cfg.short_borrow_annual / TRADING_DAYS
        eligible_cash = max(0.0, cash) if cfg.vehicle == "derisk_cash" else max(0.0, equity_prev - abs(long_shares * prev_close))
        credit = eligible_cash * cfg.cash_yield_annual / TRADING_DAYS
        cash += credit - fee
        borrow_cost += fee
        cash_interest += credit

        open_px = float(frame["open"].iloc[t])
        high_px = float(frame["high"].iloc[t])
        low_px = float(frame["low"].iloc[t])
        signal = indicators.iloc[signal_i]
        trigger, trigger_reason = hedge_trigger(cfg.strategy, signal)
        exited_today = False

        deposited = 0.0
        if contribution_flags[t]:
            deposited = float(cfg.weekly_amount)
            cash += deposited
            contributed += deposited
            flow_curve[t] = deposited
            flows.append((dt.date(), -deposited))
            # The contribution arrives at the open.  If an intraday hedge
            # target later fires, this new capital participated until that exit.
            if cfg.rebalance_on_contribution:
                rebalance(t, open_px, hedge_active, "contribution_rebalance",
                          "allocate weekly contribution", signal_i,
                          active_fraction if hedge_active else None)
            else:
                allocate_contribution(t, open_px, deposited, signal_i)

        if hedge_active:
            exit_price = None
            exit_reason = ""
            bullish_reversal = pd.notna(signal["sma20"]) and signal["close"] > signal["sma20"]
            if cfg.exit_plan == "signal_clear" and not trigger:
                exit_price, exit_reason = open_px, "entry trigger cleared"
            elif cfg.exit_plan in ("sma20_reversal", "trail6_reversal", "profit10_reversal") and bullish_reversal:
                exit_price, exit_reason = open_px, "prior close above SMA20"
            elif cfg.exit_plan == "trail6_reversal" and lowest_close > 0:
                stop = lowest_close * 1.06
                if open_px >= stop:
                    exit_price, exit_reason = open_px, "gap above 6% rebound trail"
                elif high_px >= stop:
                    exit_price, exit_reason = stop, "6% rebound trail"
            elif cfg.exit_plan in ("profit10_reversal", "profit10_only") and hedge_entry > 0:
                target = hedge_entry * (1.0 - cfg.profit_target_pct)
                if open_px <= target:
                    exit_price, exit_reason = open_px, "gap through 10% hedge-profit target"
                elif low_px <= target:
                    exit_price, exit_reason = target, "10% hedge-profit target"
            elif cfg.exit_plan == "profit10_and_sma20" and hedge_entry > 0:
                target = hedge_entry * (1.0 - cfg.profit_target_pct)
                target_price = None
                if not profit_target_hit and (open_px <= target or low_px <= target):
                    profit_target_hit = True
                    target_price = open_px if open_px <= target else target
                if profit_target_hit and bullish_reversal:
                    exit_price = open_px if target_price is None else target_price
                    exit_reason = "10% decline completed and prior close above SMA20"
            elif cfg.exit_plan == "staged_profit10_sma20" and hedge_entry > 0:
                target = hedge_entry * (1.0 - cfg.profit_target_pct)
                stage_price = None
                if not profit_target_hit and (open_px <= target or low_px <= target):
                    stage_price = open_px if open_px <= target else target
                    active_fraction = cfg.hedge_fraction / 2.0
                    rebalance(t, float(stage_price), True, "reduce_hedge",
                              "cover half after 10% decline", signal_i, active_fraction)
                    profit_target_hit = True
                if profit_target_hit and bullish_reversal:
                    exit_price = open_px if stage_price is None else stage_price
                    exit_reason = "cover remainder above SMA20"
            if exit_price is not None:
                rebalance(t, float(exit_price), False, "exit_hedge", exit_reason, signal_i)
                hedge_active = False
                hedge_armed = False
                hedge_entry = lowest_close = 0.0
                active_fraction = 0.0
                profit_target_hit = False
                hedge_exits += 1
                exited_today = True

        if review_flags[t] and not hedge_active and not exited_today:
            if not trigger:
                hedge_armed = True
            elif hedge_armed and cfg.hedge_fraction > 0:
                rebalance(t, open_px, True, "enter_hedge", trigger_reason, signal_i)
                hedge_active = True
                hedge_entry = lowest_close = open_px
                active_fraction = cfg.hedge_fraction
                profit_target_hit = False
                hedge_entries += 1

        if short_shares < 0:
            equity_high = cash + (long_shares + short_shares) * high_px
            ratio = equity_high / abs(short_shares * high_px)
            if ratio < cfg.maintenance_margin:
                rebalance(t, high_px, False, "forced_cover", "maintenance-margin breach", signal_i)
                hedge_active = False
                hedge_armed = False
                hedge_entry = lowest_close = 0.0
                active_fraction = 0.0
                profit_target_hit = False
                hedge_exits += 1
                margin_calls += 1

        close_px = float(frame["close"].iloc[t])
        if hedge_active:
            lowest_close = min(lowest_close, close_px) if lowest_close > 0 else close_px
        value = cash + (long_shares + short_shares) * close_px
        long_value = long_shares * close_px
        short_value = short_shares * close_px
        values[t] = value
        long_curve[t] = long_value / value if value > 0 else 0.0
        short_curve[t] = short_value / value if value > 0 else 0.0
        cash_curve[t] = cash
        net_curve[t] = (long_value + short_value) / value if value > 0 else 0.0
        gross_curve[t] = (abs(long_value) + abs(short_value)) / value if value > 0 else 0.0
        contributed_curve[t] = contributed

    mask = (frame.index >= start) & (frame.index <= end)
    daily = pd.DataFrame({
        "value": values, "cash": cash_curve, "long_exposure": long_curve,
        "short_exposure": short_curve, "net_exposure": net_curve,
        "gross_exposure": gross_curve, "contributed": contributed_curve,
        "external_flow": flow_curve,
    }, index=frame.index).loc[mask]
    nav = _unitized_nav(daily["value"].to_numpy(), daily["external_flow"].to_numpy())
    daily["nav"] = nav
    daily["drawdown"] = nav / np.maximum.accumulate(nav) - 1.0
    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    final_value = float(daily["value"].iloc[-1])
    flows.append((daily.index[-1].date(), final_value))
    trades = pd.DataFrame(records)
    summary = {
        "Final Value": final_value,
        "Total Contributed": float(contributed),
        "Profit": final_value - contributed,
        "Money-Weighted Return (IRR)": float(annualized_irr(flows)),
        "Time-Weighted CAGR": float(nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else 0.0,
        "Cash-Flow Adjusted Max Drawdown": float(daily["drawdown"].min()),
        "Average Net Exposure": float(daily["net_exposure"].mean()),
        "Average Gross Exposure": float(daily["gross_exposure"].mean()),
        "Percent Days Hedged": float((daily["short_exposure"] < -0.001).mean()
                                     if cfg.vehicle == "short_overlay"
                                     else (daily["net_exposure"] < 0.999).mean()),
        "Hedge Entries": int(hedge_entries),
        "Hedge Exits": int(hedge_exits),
        "Turnover": float(turnover),
        "Trading Cost": float(trading_cost),
        "Short Borrow Cost": float(borrow_cost),
        "Cash Interest": float(cash_interest),
        "Margin Calls": int(margin_calls),
        "Weekly Contributions": int(contribution_flags.sum()),
    }
    strategy_label = STRATEGY_LABELS.get(cfg.strategy, cfg.strategy)
    label = f"{strategy_label} · {cfg.hedge_fraction:.0%} · {EXIT_LABELS[cfg.exit_plan]}"
    log = trades.assign(
        trade_date=lambda x: x["trade_date"].dt.strftime("%Y-%m-%d"),
        signal_date=lambda x: x["signal_date"].dt.strftime("%Y-%m-%d"),
    ).to_dict("records") if not trades.empty else []
    return HedgeResult(label, daily, trades, summary, log)

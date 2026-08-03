"""Causal contribution-only gating for recurring SPY purchases.

Existing shares are never sold. Each weekly deposit either joins a reserve or,
when the gate is open, the entire reserve is invested at that session's open.
The gate uses only the prior completed close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from dca.adaptive_weekly import _first_trading_day_flags, _unitized_nav
from dca.engine import TRADING_DAYS, annualized_irr


@dataclass
class ContributionGateConfig:
    label: str = "Weekly buy & hold"
    start: str = "1994-01-03"
    end: str = "2026-07-30"
    weekly_amount: float = 25.0
    ma_period: int = 75
    gate_mode: str = "always"  # always|above_sma|custom
    cost_pct: float = 0.0005
    fixed_cash_yield: float = 0.0


@dataclass
class ContributionGateResult:
    label: str
    daily: pd.DataFrame
    decisions: pd.DataFrame
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def run_contribution_gate(
    cfg: ContributionGateConfig,
    prices: pd.DataFrame,
    annual_cash_yield: pd.Series | None = None,
    custom_weekly_gate: pd.Series | None = None,
) -> ContributionGateResult:
    required = {"open", "close"}
    if not required.issubset(prices.columns):
        raise ValueError(f"prices must include {sorted(required)}")
    if cfg.gate_mode not in {"always", "above_sma", "custom"}:
        raise ValueError("gate_mode must be always, above_sma, or custom")
    if cfg.gate_mode == "custom" and custom_weekly_gate is None:
        raise ValueError("custom_weekly_gate is required for custom mode")

    frame = prices.sort_index().copy()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    start, end = pd.Timestamp(cfg.start), pd.Timestamp(cfg.end)
    if start <= frame.index.min():
        raise ValueError("At least one pre-start bar is required for causal execution.")

    close = frame["close"].astype(float)
    sma = close.rolling(cfg.ma_period, min_periods=cfg.ma_period).mean()
    contribution_flags = _first_trading_day_flags(frame.index, start, end)
    if annual_cash_yield is None:
        yields = pd.Series(cfg.fixed_cash_yield, index=frame.index, dtype=float)
    else:
        yields = annual_cash_yield.reindex(frame.index).ffill().fillna(0.0).astype(float)
    custom = None if custom_weekly_gate is None else custom_weekly_gate.reindex(frame.index).fillna(False)

    cash = shares = contributed = 0.0
    trading_cost = cash_interest = turnover = 0.0
    flows: List[Tuple[date, float]] = []
    records: List[Dict[str, Any]] = []
    n = len(frame)
    values = np.zeros(n)
    cash_curve = np.zeros(n)
    contributed_curve = np.zeros(n)
    flow_curve = np.zeros(n)
    invested_curve = np.zeros(n)
    gate_curve = np.ones(n, dtype=float)

    for t, dt in enumerate(frame.index):
        if not (start <= dt <= end):
            continue

        rate = max(0.0, float(yields.iloc[t]))
        credit = cash * rate / TRADING_DAYS if cash > 0 else 0.0
        cash += credit
        cash_interest += credit

        signal_i = t - 1
        if cfg.gate_mode == "always":
            gate_open = True
        elif cfg.gate_mode == "above_sma":
            gate_open = bool(
                pd.notna(sma.iloc[signal_i])
                and close.iloc[signal_i] > sma.iloc[signal_i]
            )
        else:
            gate_open = bool(custom.iloc[t])
        gate_curve[t] = float(gate_open)

        deposited = 0.0
        if contribution_flags[t]:
            deposited = float(cfg.weekly_amount)
            cash += deposited
            contributed += deposited
            flow_curve[t] = deposited
            flows.append((dt.date(), -deposited))

            deployed = 0.0
            cost = 0.0
            bought = 0.0
            if gate_open and cash > 0:
                deployed = cash / (1.0 + cfg.cost_pct)
                cost = deployed * cfg.cost_pct
                bought = deployed / float(frame["open"].iloc[t])
                shares += bought
                cash -= deployed + cost
                trading_cost += cost
                turnover += deployed
            records.append({
                "trade_date": dt, "signal_date": frame.index[signal_i],
                "prior_close": float(close.iloc[signal_i]),
                "sma": float(sma.iloc[signal_i]) if pd.notna(sma.iloc[signal_i]) else np.nan,
                "gate_open": gate_open, "contribution": deposited,
                "cash_deployed": deployed, "execution_open": float(frame["open"].iloc[t]),
                "shares_bought": bought, "cost": cost,
                "reserve_after": cash, "cash_yield_rate": rate,
            })

        value = cash + shares * float(close.iloc[t])
        values[t] = value
        cash_curve[t] = cash
        contributed_curve[t] = contributed
        invested_curve[t] = shares * float(close.iloc[t]) / value if value > 0 else 0.0

    mask = (frame.index >= start) & (frame.index <= end)
    daily = pd.DataFrame({
        "value": values, "cash": cash_curve, "contributed": contributed_curve,
        "external_flow": flow_curve, "invested_fraction": invested_curve,
        "gate_open": gate_curve,
    }, index=frame.index).loc[mask]
    nav = _unitized_nav(daily["value"].to_numpy(), daily["external_flow"].to_numpy())
    daily["nav"] = nav
    daily["drawdown"] = nav / np.maximum.accumulate(nav) - 1.0
    years = max((daily.index[-1] - daily.index[0]).days / 365.25, 1e-9)
    final_value = float(daily["value"].iloc[-1])
    flows.append((daily.index[-1].date(), final_value))
    decisions = pd.DataFrame(records)
    closed = int((~decisions["gate_open"]).sum()) if not decisions.empty else 0
    summary = {
        "Final Value": final_value,
        "Total Contributed": float(contributed),
        "Profit": final_value - contributed,
        "Money-Weighted Return (IRR)": float(annualized_irr(flows)),
        "Time-Weighted CAGR": float(nav[-1] ** (1 / years) - 1) if nav[-1] > 0 else 0.0,
        "Cash-Flow Adjusted Max Drawdown": float(daily["drawdown"].min()),
        "Average Invested Fraction": float(daily["invested_fraction"].mean()),
        "Average Reserve Cash": float(daily["cash"].mean()),
        "Ending Reserve Cash": float(daily["cash"].iloc[-1]),
        "Cash Interest": float(cash_interest),
        "Trading Cost": float(trading_cost),
        "Turnover": float(turnover),
        "Weekly Contributions": int(contribution_flags[mask].sum()),
        "Closed-Gate Contributions": closed,
        "Percent Contributions Delayed": closed / len(decisions) if len(decisions) else 0.0,
    }
    log = decisions.assign(
        trade_date=lambda x: x["trade_date"].dt.strftime("%Y-%m-%d"),
        signal_date=lambda x: x["signal_date"].dt.strftime("%Y-%m-%d"),
    ).to_dict("records") if not decisions.empty else []
    return ContributionGateResult(cfg.label, daily, decisions, summary, log)

"""Contribution / bankroll backtest engine.

Deterministic daily walk over a price series:
  * contributions land in cash on a schedule (weekly … quarterly),
  * a buy rule decides when accumulated cash is deployed into the index,
  * an optional sell rule trims holdings back to cash,
  * everything is marked daily so we get a value curve + money-weighted return.

No look-ahead: the MA at bar t uses closes up to t, and a decision at t executes
at t's close (contributions are cash you already hold; this isn't intraday
timing so same-bar close execution is fine for a monthly-DCA study).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

TRADING_DAYS = 252.0


@dataclass
class DcaConfig:
    label: str = "Scheme"
    amount: float = 100.0                 # cash added per contribution
    cadence: str = "monthly"              # weekly|biweekly|semimonthly|monthly|quarterly
    buy_rule: str = "always"              # always|above_ma|below_ma
    ma_type: str = "sma"                  # sma|ema
    ma_period: int = 200
    unused_cash: str = "accumulate"       # accumulate|skip
    cash_yield_annual: float = 0.0        # yield on idle cash (e.g. 0.04)
    sell_rule: str = "none"               # none|above_ma|below_ma
    sell_fraction: float = 1.0            # fraction of shares sold when sell triggers


@dataclass
class DcaResult:
    label: str
    dates: List[str]
    value: List[float]                    # portfolio value (cash + holdings)
    contributed: List[float]              # cumulative cash contributed
    invested_frac: List[float]            # holdings / value (time in market)
    summary: Dict[str, Any]
    buys: int
    sells: int
    log: List[Dict[str, Any]] = field(default_factory=list)   # per buy/sell event


def _ma(close: pd.Series, kind: str, period: int) -> pd.Series:
    if kind == "ema":
        return close.ewm(span=period, adjust=False).mean()
    return close.rolling(period).mean()


def _contribution_flags(index: pd.DatetimeIndex, cadence: str) -> np.ndarray:
    """True on the first trading day of each contribution period."""
    d = pd.DatetimeIndex(index)
    flags = np.zeros(len(d), dtype=bool)
    if cadence == "weekly":
        key = d.isocalendar().week.to_numpy() + d.isocalendar().year.to_numpy() * 100
    elif cadence == "biweekly":
        wk = d.isocalendar().week.to_numpy() + d.isocalendar().year.to_numpy() * 100
        # every other ISO week
        key = np.where((d.isocalendar().week.to_numpy() % 2) == 0, wk, wk - 1)
    elif cadence == "semimonthly":
        key = d.year.to_numpy() * 10000 + d.month.to_numpy() * 100 + (d.day.to_numpy() > 15).astype(int)
    elif cadence == "quarterly":
        key = d.year.to_numpy() * 10 + ((d.month.to_numpy() - 1) // 3)
    else:  # monthly
        key = d.year.to_numpy() * 100 + d.month.to_numpy()
    prev = np.empty_like(key)
    prev[0] = key[0] - 1  # force first day to be a contribution
    prev[1:] = key[:-1]
    return key != prev


def annualized_irr(flows: List[Tuple[date, float]]) -> float:
    """Money-weighted (IRR) annualized return from dated cash flows (outflows
    negative). Bisection on the annual rate; returns 0.0 if no sign change."""
    if len(flows) < 2:
        return 0.0
    t0 = flows[0][0]
    yrs = [((d - t0).days / 365.25) for d, _ in flows]
    amts = [cf for _, cf in flows]

    def npv(rate: float) -> float:
        base = 1.0 + rate
        if base <= 0:
            return float("inf")
        return sum(a / (base ** y) for a, y in zip(amts, yrs))

    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if not np.isfinite(flo) or not np.isfinite(fhi) or flo * fhi > 0:
        return 0.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        fm = npv(mid)
        if abs(fm) < 1e-6:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def _max_drawdown(values: np.ndarray) -> float:
    peak = np.maximum.accumulate(values)
    dd = (values - peak) / np.where(peak == 0, 1, peak)
    return float(dd.min()) if len(dd) else 0.0


def run_dca(cfg: DcaConfig, prices: pd.DataFrame) -> DcaResult:
    """prices: DataFrame with a 'close' column and a DatetimeIndex."""
    close = prices["close"].astype(float)
    idx = pd.DatetimeIndex(close.index)
    n = len(close)
    if n < max(cfg.ma_period, 5):
        raise ValueError("Not enough price history for the configured MA.")

    ma = _ma(close, cfg.ma_type, cfg.ma_period).to_numpy()
    px = close.to_numpy()
    contrib_day = _contribution_flags(idx, cfg.cadence)
    daily_yield = cfg.cash_yield_annual / TRADING_DAYS

    cash = 0.0
    shares = 0.0
    contributed = 0.0
    buys = sells = 0
    value_curve = np.zeros(n)
    contributed_curve = np.zeros(n)
    invested_frac = np.zeros(n)
    flows: List[Tuple[date, float]] = []
    log: List[Dict[str, Any]] = []

    for t in range(n):
        if daily_yield and cash > 0:
            cash *= (1.0 + daily_yield)

        uptrend = not np.isnan(ma[t]) and px[t] > ma[t]
        downtrend = not np.isnan(ma[t]) and px[t] < ma[t]
        buy_ok = (cfg.buy_rule == "always"
                  or (cfg.buy_rule == "above_ma" and uptrend)
                  or (cfg.buy_rule == "below_ma" and downtrend))

        # 1) contribution
        if contrib_day[t]:
            if cfg.unused_cash == "skip" and cfg.buy_rule != "always" and not buy_ok:
                pass  # skip this period's contribution entirely
            else:
                cash += cfg.amount
                contributed += cfg.amount
                flows.append((idx[t].date(), -cfg.amount))

        # 2) deploy cash when the buy rule allows
        if buy_ok and cash > 0 and px[t] > 0:
            deployed = cash
            bought = cash / px[t]
            shares += bought
            cash = 0.0
            buys += 1
            log.append({"date": idx[t].strftime("%Y-%m-%d"), "action": "buy", "price": float(px[t]),
                        "cash": float(deployed), "shares": float(bought),
                        "shares_after": float(shares), "value": float(shares * px[t])})

        # 3) sell overlay
        sell_ok = ((cfg.sell_rule == "above_ma" and uptrend)
                   or (cfg.sell_rule == "below_ma" and downtrend))
        if sell_ok and shares > 0:
            sold = shares * min(max(cfg.sell_fraction, 0.0), 1.0)
            proceeds = sold * px[t]
            cash += proceeds
            shares -= sold
            sells += 1
            log.append({"date": idx[t].strftime("%Y-%m-%d"), "action": "sell", "price": float(px[t]),
                        "cash": float(proceeds), "shares": float(-sold),
                        "shares_after": float(shares), "value": float(cash + shares * px[t])})

        val = cash + shares * px[t]
        value_curve[t] = val
        contributed_curve[t] = contributed
        invested_frac[t] = (shares * px[t]) / val if val > 0 else 0.0

    final_value = value_curve[-1]
    flows.append((idx[-1].date(), final_value))
    irr = annualized_irr(flows)
    profit = final_value - contributed
    years = max((idx[-1] - idx[0]).days / 365.25, 1e-9)

    summary = {
        "Final Value": float(final_value),
        "Total Contributed": float(contributed),
        "Profit": float(profit),
        "ROI on Contributions": float(profit / contributed) if contributed > 0 else 0.0,
        "Money-Weighted Return (IRR)": float(irr),
        "Max Drawdown": _max_drawdown(value_curve),
        "Avg Time in Market": float(np.mean(invested_frac)),
        "Shares Held": float(shares),
        "Buys": buys,
        "Sells": sells,
        "Years": float(years),
    }
    return DcaResult(
        label=cfg.label,
        dates=[d.strftime("%Y-%m-%d") for d in idx],
        value=[float(v) for v in value_curve],
        contributed=[float(v) for v in contributed_curve],
        invested_frac=[float(v) for v in invested_frac],
        summary=summary, buys=buys, sells=sells, log=log,
    )

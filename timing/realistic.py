"""More conservative timing simulator for leveraged strategy research.

Unlike the original close-to-close exposure engine, this module executes a
prior-close signal at the next open, charges financing daily, checks maintenance
margin against both the open and intraday low, and can force liquidation.
It also builds synthetic daily-reset leveraged ETF OHLC series so volatility
decay, fund expenses, and a financing proxy are represented explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from dca.engine import _contribution_flags, annualized_irr
from timing.engine import TRADING_DAYS, _ma


@dataclass
class RealisticConfig:
    label: str = "Strategy"
    start_capital: float = 0.0
    contribution_amount: float = 25.0
    contribution_cadence: str = "weekly"
    contribution_day: str = "start"
    contribution_buy_rule: str = "always"
    contribution_ma_type: str = "sma"
    contribution_ma_period: int = 100
    cash_yield_annual: float = 0.045
    borrow_annual: float = 0.10
    cost_pct: float = 0.0005
    rebalance_band: float = 0.03
    initial_margin: float = 0.50
    maintenance_margin: float = 0.40
    liquidation_lockout_days: int = 20
    enable_margin_calls: bool = True
    max_exposure: float = 2.0


@dataclass
class RealisticResult:
    label: str
    dates: List[str]
    value: List[float]
    nav: List[float]
    drawdown: List[float]
    exposure: List[float]
    summary: Dict[str, Any]
    log: List[Dict[str, Any]] = field(default_factory=list)


def _unitize(values: np.ndarray, external_flows: np.ndarray) -> np.ndarray:
    nav = np.ones(len(values))
    for t in range(len(values)):
        if t == 0 or values[t - 1] <= 0:
            nav[t] = values[t] / external_flows[t] if external_flows[t] > 0 else 1.0
        else:
            nav[t] = nav[t - 1] * ((values[t] - external_flows[t]) / values[t - 1])
    return nav


def _margin_ratio(cash: float, reserve: float, shares: float, price: float) -> float:
    market_value = shares * price
    if market_value <= 0:
        return float("inf")
    return (cash + reserve + market_value) / market_value


def run_realistic(
    cfg: RealisticConfig,
    prices: pd.DataFrame,
    target_exposure: np.ndarray,
) -> RealisticResult:
    required = {"open", "high", "low", "close"}
    if not required.issubset(prices.columns):
        raise ValueError(f"prices must include {sorted(required)}")
    if len(prices) != len(target_exposure):
        raise ValueError("target_exposure must match prices length")

    idx = pd.DatetimeIndex(prices.index)
    open_px = prices["open"].astype(float).to_numpy()
    low_px = prices["low"].astype(float).to_numpy()
    close_px = prices["close"].astype(float).to_numpy()
    n = len(prices)
    if n < 30:
        raise ValueError("Not enough price history")

    contribution_flags = (
        _contribution_flags(idx, cfg.contribution_cadence, cfg.contribution_day, close_px)
        if cfg.contribution_amount > 0 else np.zeros(n, dtype=bool)
    )
    gate_ma = _ma(
        pd.Series(close_px, index=idx),
        cfg.contribution_ma_type,
        cfg.contribution_ma_period,
    )

    cash = float(cfg.start_capital)
    reserve = 0.0
    shares = 0.0
    contributed = max(0.0, float(cfg.start_capital))
    flows: List[Tuple[date, float]] = []
    if contributed > 0:
        flows.append((idx[0].date(), -contributed))
    external_flows = np.zeros(n)
    if contributed > 0:
        external_flows[0] = contributed

    values = np.zeros(n)
    exposures = np.zeros(n)
    turnover = 0.0
    trading_cost = 0.0
    financing_cost = 0.0
    cash_interest = 0.0
    margin_calls = 0
    lockout = 0
    min_margin_ratio = float("inf")
    log: List[Dict[str, Any]] = []
    previous_target = None

    def liquidate(t: int, price: float, reason: str) -> None:
        nonlocal cash, shares, turnover, trading_cost, margin_calls, lockout
        proceeds = shares * price
        cost = proceeds * cfg.cost_pct
        turnover += proceeds
        trading_cost += cost
        cash += proceeds - cost
        shares = 0.0
        margin_calls += 1
        lockout = max(0, int(cfg.liquidation_lockout_days))
        log.append({
            "date": idx[t].strftime("%Y-%m-%d"), "action": "forced_liquidation",
            "reason": reason, "price": float(price), "value": float(cash + reserve),
        })

    for t in range(n):
        if cash > 0:
            credit = cash * cfg.cash_yield_annual / TRADING_DAYS
            cash += credit
            cash_interest += credit
        elif cash < 0:
            fee = -cash * cfg.borrow_annual / TRADING_DAYS
            cash -= fee
            financing_cost += fee
        if reserve > 0:
            credit = reserve * cfg.cash_yield_annual / TRADING_DAYS
            reserve += credit
            cash_interest += credit

        signal_t = max(0, t - 1)
        gate_up = not np.isnan(gate_ma[signal_t]) and close_px[signal_t] > gate_ma[signal_t]
        gate_down = not np.isnan(gate_ma[signal_t]) and close_px[signal_t] < gate_ma[signal_t]
        gate_open = (
            cfg.contribution_buy_rule == "always"
            or (cfg.contribution_buy_rule == "above_ma" and gate_up)
            or (cfg.contribution_buy_rule == "below_ma" and gate_down)
        )

        deposited = 0.0
        if contribution_flags[t]:
            deposited = float(cfg.contribution_amount)
            external_flows[t] += deposited
            contributed += deposited
            flows.append((idx[t].date(), -deposited))
            if gate_open:
                cash += deposited
            else:
                reserve += deposited

        released = 0.0
        if gate_open and reserve > 0:
            released = reserve
            cash += reserve
            reserve = 0.0

        # A gap can violate maintenance before the planned next-open rebalance.
        if cfg.enable_margin_calls and shares > 0 and cash < 0:
            ratio_open = _margin_ratio(cash, reserve, shares, open_px[t])
            min_margin_ratio = min(min_margin_ratio, ratio_open)
            if ratio_open < cfg.maintenance_margin:
                liquidate(t, open_px[t], "open_gap")

        reg_t_cap = 1.0 / cfg.initial_margin if cfg.initial_margin > 0 else cfg.max_exposure
        desired = float(np.clip(target_exposure[signal_t], 0.0, min(cfg.max_exposure, reg_t_cap)))
        if lockout > 0:
            desired = 0.0

        active_equity = cash + shares * open_px[t]
        current = shares * open_px[t] / active_equity if active_equity > 0 else 0.0
        force = deposited > 0 and gate_open or released > 0 or previous_target != desired
        if active_equity > 0 and (force or abs(current - desired) > cfg.rebalance_band):
            target_dollars = desired * active_equity
            trade = target_dollars - shares * open_px[t]
            cost = abs(trade) * cfg.cost_pct
            shares = target_dollars / open_px[t]
            cash = active_equity - target_dollars - cost
            turnover += abs(trade)
            trading_cost += cost
            previous_target = desired

        # Conservative assumption: if the observed adjusted low breaches house
        # maintenance, the broker liquidates the full position at that low.
        if cfg.enable_margin_calls and shares > 0 and cash < 0:
            ratio_low = _margin_ratio(cash, reserve, shares, low_px[t])
            min_margin_ratio = min(min_margin_ratio, ratio_low)
            if ratio_low < cfg.maintenance_margin:
                liquidate(t, low_px[t], "intraday_low")

        value = cash + reserve + shares * close_px[t]
        values[t] = value
        exposures[t] = shares * close_px[t] / value if value > 0 else 0.0
        if lockout > 0:
            lockout -= 1

    nav = _unitize(values, external_flows)
    peak = np.maximum.accumulate(nav)
    drawdown = (nav - peak) / np.where(peak == 0, 1, peak)
    years = max((idx[-1] - idx[0]).days / 365.25, 1e-9)
    twr = nav[-1] ** (1 / years) - 1 if nav[-1] > 0 else -1.0
    irr = annualized_irr([*flows, (idx[-1].date(), float(values[-1]))]) if values[-1] > 0 else -1.0

    return RealisticResult(
        label=cfg.label,
        dates=[d.strftime("%Y-%m-%d") for d in idx],
        value=[float(x) for x in values],
        nav=[float(x) for x in nav],
        drawdown=[float(x) for x in drawdown],
        exposure=[float(x) for x in exposures],
        summary={
            "Total Contributed": float(contributed),
            "Final Value": float(values[-1]),
            "Profit": float(values[-1] - contributed),
            "IRR": float(irr),
            "Time-Weighted CAGR": float(twr),
            "Max Drawdown": float(drawdown.min()),
            "Avg Exposure": float(exposures.mean()),
            "Turnover / yr": float(turnover / max(contributed, 1.0) / years),
            "Trading Cost": float(trading_cost),
            "Financing Cost": float(financing_cost),
            "Cash Interest": float(cash_interest),
            "Margin Calls": int(margin_calls),
            "Minimum Margin Ratio": float(min_margin_ratio) if np.isfinite(min_margin_ratio) else 1.0,
        },
        log=log,
    )


def synthetic_daily_reset_ohlc(
    spy: pd.DataFrame,
    leverage: float,
    expense_ratio: float = 0.0089,
    financing_annual: float = 0.10,
) -> pd.DataFrame:
    """Approximate a daily-reset leveraged ETF from adjusted SPY OHLC.

    The extra notional pays the financing proxy and the fund pays its stated
    expense ratio.  Daily resetting creates the volatility/compounding path.
    """
    out = np.zeros((len(spy), 4), dtype=float)
    cols = ["open", "high", "low", "close"]
    source = spy[cols].astype(float).to_numpy()
    out[0, :] = 100.0
    daily_drag = (expense_ratio + max(0.0, leverage - 1.0) * financing_annual) / TRADING_DAYS
    for t in range(1, len(spy)):
        prev_spy = source[t - 1, 3]
        prev_etf = out[t - 1, 3]
        ratios = source[t, :] / prev_spy - 1.0
        factors = np.maximum(0.001, 1.0 + leverage * ratios - daily_drag)
        out[t, :] = prev_etf * factors
        out[t, 1] = max(out[t, 0], out[t, 1], out[t, 3])
        out[t, 2] = min(out[t, 0], out[t, 2], out[t, 3])
    return pd.DataFrame(out, index=spy.index, columns=cols)

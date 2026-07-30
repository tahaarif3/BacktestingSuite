"""Orchestrates a full study: baseline + benchmark variants + regime split +
parameter sensitivity — Phases 13–15."""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List

import pandas as pd

from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.engine import run_portfolio_backtest
from portfolio_backtest.metrics import regime_breakdown, summarize

# Sensitivity grids (Phase 14). Each is varied while others stay at baseline.
SENSITIVITY_GRID = {
    "market_ma": [50, 90, 100, 150, 200],
    "breakout_window": [20, 30, 50, 60],
    "rs_lookback": [20, 40, 60, 90],
    "rs_threshold": [0.0, 0.03, 0.05, 0.08, 0.10],
    "volume_mult": [1.0, 1.25, 1.5, 2.0],
    "stop_atr_mult": [1.5, 2.0, 2.5, 3.0],
    "max_positions": [5, 10, 15, 20],
    "risk_per_trade": [0.0025, 0.005, 0.0075, 0.01],
}


def _run(cfg, data, spy):
    res = run_portfolio_backtest(cfg, data, spy)
    return res, summarize(res.daily, res.trades, cfg.initial_capital)


def _equal_weight_benchmark(data: Dict[str, pd.DataFrame], axis: pd.Index, capital: float) -> List[float]:
    norm = []
    for df in data.values():
        c = df["close"].reindex(axis).ffill()
        first = c.dropna().iloc[0] if c.notna().any() else None
        if first:
            norm.append(c / first)
    if not norm:
        return [capital] * len(axis)
    ew = pd.concat(norm, axis=1).mean(axis=1)
    return [float(capital * v) if pd.notna(v) else float(capital) for v in ew]


def run_study(
    cfg: PortfolioBacktestConfig,
    data: Dict[str, pd.DataFrame],
    spy: pd.DataFrame,
    sensitivity: bool = True,
) -> Dict[str, Any]:
    base_res, base_summary = _run(cfg, data, spy)
    daily = base_res.daily
    axis = daily.index

    # benchmark variants
    no_mkt, no_mkt_sum = _run(dataclasses.replace(cfg, use_market_filter=False), data, spy)
    no_rs, no_rs_sum = _run(dataclasses.replace(cfg, use_rs_filter=False), data, spy)
    ew = _equal_weight_benchmark(data, axis, cfg.initial_capital)

    comparison = {
        "strategy": base_summary,
        "spy_buy_hold_return": float(base_res.benchmark.reindex(axis).iloc[-1] / cfg.initial_capital - 1.0),
        "equal_weight_return": float(ew[-1] / cfg.initial_capital - 1.0) if ew else 0.0,
        "no_market_filter_return": no_mkt_sum["Total Return"],
        "no_rs_filter_return": no_rs_sum["Total Return"],
    }

    sens: Dict[str, List[Dict[str, Any]]] = {}
    if sensitivity:
        for param, values in SENSITIVITY_GRID.items():
            rows = []
            for v in values:
                try:
                    _, s = _run(dataclasses.replace(cfg, **{param: v}), data, spy)
                    rows.append({
                        "value": v, "total_return": s["Total Return"], "cagr": s["CAGR"],
                        "max_drawdown": s["Max Drawdown"], "sharpe": s["Sharpe Ratio"],
                        "trades": s["Total Trades"],
                    })
                except Exception as e:  # noqa: BLE001
                    rows.append({"value": v, "error": str(e)})
            sens[param] = rows

    return {
        "baseline": base_res,
        "summary": base_summary,
        "regime": regime_breakdown(daily, spy),
        "comparison": comparison,
        "sensitivity": sens,
        "equal_weight_curve": ew,
    }

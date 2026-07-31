"""Runs SPY market-timing strategies and returns them alongside a buy-and-hold
baseline for comparison."""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Dict, List

from desktop.backend.services import data_service, screener_service

from data.dataloader import DataLoader
from timing.engine import TimingConfig, run_timing

_FIELDS = {f.name for f in dataclasses.fields(TimingConfig)}


def _clean(x) -> float:
    import math
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return 0.0
    return float(x)


def _load(symbol: str, start: str, end: str, refresh: bool):
    symbol = (symbol or "SPY").upper()
    if symbol == "SPY":
        screener_service._ensure_reference(start, end, refresh)
        path = data_service.resolve_data_path("spy_daily_yfinance.parquet")
    else:
        path = data_service.resolve_data_path(f"{symbol}_1d.parquet")
        if refresh or not os.path.exists(path):
            data_service.fetch_ticker(symbol, start, end, "1d", merge=True, refresh=refresh)
    dl = DataLoader()
    df = dl.clean_data(dl.load_data(path))[["close"]].loc[start:end]
    if len(df) < 60:
        raise ValueError(f"Not enough price history for {symbol}.")
    return df


def _serialize(res) -> Dict[str, Any]:
    return {
        "label": res.label,
        "dates": res.dates,
        "value": [_clean(v) for v in res.value],
        "exposure": [_clean(v) for v in res.exposure],
        "summary": {k: (_clean(v) if isinstance(v, (int, float)) else v) for k, v in res.summary.items()},
        "log": res.log[-500:],
    }


def run(body: Dict[str, Any]) -> Dict[str, Any]:
    symbol = body.get("symbol", "SPY")
    start = body.get("start", "2004-01-01")
    end = body.get("end", "2026-12-31")
    refresh = bool(body.get("refresh", False))
    capital = float(body.get("start_capital", 10000.0))
    prices = _load(symbol, start, end, refresh)

    strategies = body.get("strategies") or []
    results: List[Dict[str, Any]] = []
    for s in strategies:
        kw = {k: v for k, v in s.items() if k in _FIELDS}
        kw["start_capital"] = capital
        try:
            results.append(_serialize(run_timing(TimingConfig(**kw), prices)))
        except Exception as e:  # noqa: BLE001
            results.append({"label": s.get("label", "?"), "error": str(e)})

    baseline = _serialize(run_timing(
        TimingConfig(label="Buy & Hold", strategy="buy_hold", start_capital=capital), prices))
    return {"symbol": symbol.upper(), "results": results, "baseline": baseline}

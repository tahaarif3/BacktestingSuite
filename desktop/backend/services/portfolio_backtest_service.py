"""Runs the automated multi-position portfolio backtester and serialises the
study (baseline + benchmarks + regime + sensitivity) to a JSON payload."""

from __future__ import annotations

import dataclasses
import os
from typing import Any, Dict, List

import pandas as pd

from desktop.backend.services import backtest_service, data_service, screener_service

from data.dataloader import DataLoader
from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.study import run_study

_COLS = ["open", "high", "low", "close", "volume"]


def _clean(path: str) -> pd.DataFrame:
    dl = DataLoader()
    return dl.clean_data(dl.load_data(path))[_COLS]


def _load(cfg: PortfolioBacktestConfig):
    interval = cfg.interval
    if interval == "1d":
        screener_service._ensure_reference(cfg.start, cfg.end, cfg.refresh)
        spy_file = "spy_daily_yfinance.parquet"
    else:
        spy_file = f"SPY_{interval}.parquet"
        if cfg.refresh or not os.path.exists(data_service.resolve_data_path(spy_file)):
            data_service.fetch_ticker("SPY", cfg.start, cfg.end, interval, merge=True, refresh=cfg.refresh)
    spy = _clean(data_service.resolve_data_path(spy_file)).loc[cfg.start:cfg.end]

    tickers = [t.strip().upper() for t in (cfg.tickers or screener_service.DEFAULT_WATCHLIST) if t.strip()]
    tickers = list(dict.fromkeys(tickers))
    data: Dict[str, pd.DataFrame] = {}
    warnings: List[str] = []
    min_bars = cfg.trend_slow_ma + 5
    for sym in tickers:
        try:
            path = data_service.resolve_data_path(f"{sym}_{interval}.parquet")
            if cfg.refresh or not os.path.exists(path):
                data_service.fetch_ticker(sym, cfg.start, cfg.end, interval, merge=True, refresh=cfg.refresh)
            df = _clean(path).loc[cfg.start:cfg.end]
            if len(df) < min_bars:
                warnings.append(f"{sym}: only {len(df)} bars — skipped")
                continue
            data[sym] = df
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{sym}: {e}")
    if not data:
        raise ValueError("No universe symbols could be loaded.")
    return data, spy, warnings


def _iso(index) -> List[str]:
    return [d.strftime("%Y-%m-%d") for d in index]


def run(config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = PortfolioBacktestConfig(**{k: v for k, v in config.items()
                                     if k in {f.name for f in dataclasses.fields(PortfolioBacktestConfig)}})
    data, spy, load_warnings = _load(cfg)
    study = run_study(cfg, data, spy, sensitivity=config.get("sensitivity", True))

    res = study["baseline"]
    daily = res.daily
    axis = daily.index
    cn = backtest_service._clean_num
    bench = res.benchmark.reindex(axis).ffill()

    return {
        "summary": {k: (cn(v) if isinstance(v, (int, float)) else v) for k, v in study["summary"].items()},
        "series": {
            "dates": _iso(axis),
            "equity": [cn(v) for v in daily["equity"].tolist()],
            "benchmark": [cn(v) for v in bench.tolist()],
            "equal_weight": [cn(v) for v in study["equal_weight_curve"]],
            "drawdown": [cn(v) for v in daily["drawdown"].tolist()],
            "open_positions": [int(v) for v in daily["open_positions"].tolist()],
            "exposure": [cn(v) for v in daily["gross_exposure"].tolist()],
        },
        "trades": [{k: (cn(v) if isinstance(v, (int, float)) else v) for k, v in t.items()}
                   for t in res.trades[-1000:]],
        "trade_count": len(res.trades),
        "open_positions": res.open_positions,
        "regime": study["regime"],
        "comparison": {k: (cn(v) if isinstance(v, (int, float)) else v) for k, v in study["comparison"].items()},
        "sensitivity": study["sensitivity"],
        "universe": list(data.keys()),
        "warnings": load_warnings + res.warnings,
    }

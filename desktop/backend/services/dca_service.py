"""Runs the SPY DCA / bankroll backtester for a set of user schemes and returns
them alongside reference curves (a $100/mo baseline and a lump-sum)."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from desktop.backend.services import data_service, screener_service

from data.dataloader import DataLoader
from dca.engine import DcaConfig, run_dca, annualized_irr, _max_drawdown

_FIELDS = {"label", "amount", "cadence", "buy_rule", "ma_type", "ma_period",
           "unused_cash", "cash_yield_annual", "sell_rule", "sell_fraction"}


def _clean_num(x) -> float:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return 0.0
    return float(x)


def _load_prices(symbol: str, start: str, end: str, refresh: bool) -> pd.DataFrame:
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
    if len(df) < 30:
        raise ValueError(f"Not enough price history for {symbol} in that range.")
    return df


def _serialize(res) -> Dict[str, Any]:
    return {
        "label": res.label,
        "dates": res.dates,
        "value": [_clean_num(v) for v in res.value],
        "contributed": [_clean_num(v) for v in res.contributed],
        "invested_frac": [_clean_num(v) for v in res.invested_frac],
        "summary": {k: (_clean_num(v) if isinstance(v, (int, float)) else v)
                    for k, v in res.summary.items()},
        "buys": res.buys,
        "sells": res.sells,
        "log": res.log,
    }


def _lump_sum(prices: pd.DataFrame, total: float) -> Dict[str, Any]:
    """Invest ``total`` at the first bar and hold — the 'perfect timing' reference."""
    close = prices["close"].astype(float)
    px = close.to_numpy()
    idx = pd.DatetimeIndex(close.index)
    shares = total / px[0] if px[0] > 0 else 0.0
    value = shares * px
    from datetime import date  # noqa
    irr = annualized_irr([(idx[0].date(), -total), (idx[-1].date(), float(value[-1]))])
    profit = float(value[-1]) - total
    return {
        "label": "Lump sum (all at start)",
        "dates": [d.strftime("%Y-%m-%d") for d in idx],
        "value": [_clean_num(v) for v in value],
        "contributed": [total] * len(idx),
        "invested_frac": [1.0] * len(idx),
        "summary": {
            "Final Value": _clean_num(value[-1]), "Total Contributed": total,
            "Profit": _clean_num(profit), "ROI on Contributions": _clean_num(profit / total) if total else 0.0,
            "Money-Weighted Return (IRR)": _clean_num(irr), "Max Drawdown": _max_drawdown(value),
            "Avg Time in Market": 1.0, "Shares Held": _clean_num(shares), "Buys": 1, "Sells": 0,
        },
        "buys": 1, "sells": 0,
        "log": [{"date": idx[0].strftime("%Y-%m-%d"), "action": "buy", "price": _clean_num(px[0]),
                 "cash": total, "shares": _clean_num(shares), "shares_after": _clean_num(shares),
                 "value": _clean_num(shares * px[0])}],
    }


def run(body: Dict[str, Any]) -> Dict[str, Any]:
    symbol = body.get("symbol", "SPY")
    start = body.get("start", "2010-01-01")
    end = body.get("end", "2025-12-31")
    refresh = bool(body.get("refresh", False))
    prices = _load_prices(symbol, start, end, refresh)

    schemes = body.get("schemes") or []
    results: List[Dict[str, Any]] = []
    for s in schemes:
        cfg = DcaConfig(**{k: v for k, v in s.items() if k in _FIELDS})
        try:
            results.append(_serialize(run_dca(cfg, prices)))
        except Exception as e:  # noqa: BLE001
            results.append({"label": cfg.label, "error": str(e)})

    baseline = _serialize(run_dca(
        DcaConfig(label="Baseline $100/mo", amount=100, cadence="monthly", buy_rule="always"),
        prices))
    lump = _lump_sum(prices, baseline["summary"]["Total Contributed"])

    return {"symbol": symbol.upper(), "results": results, "baseline": baseline, "lump_sum": lump}

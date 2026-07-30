"""Multi-symbol screener for the Relative-Strength Breakout setup.

Runs the RS-Breakout strategy across a basket, ranking which names have the
regime **armed now**, are **currently long**, or **fired recently**. Fetches
(and caches) each symbol's daily data on demand — a one-time bulk download — and
refreshes the canonical SPY reference so "armed now" reflects the latest bars.

The result rows carry the cached ``file`` name so the frontend can jump straight
into a backtest or replay of any hit.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from desktop.backend.services import data_service
from desktop.backend.services import backtest_service

from data.fetcher import DataFetcher
from data.dataloader import DataLoader
from strat.rs_breakout import RSBreakoutStrategy

# A default basket of liquid, SPY-correlated large-caps that can diverge.
DEFAULT_WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "XOM", "COST", "LLY", "V", "UNH", "HD", "CRM", "ORCL", "QCOM",
]

# Numeric constructor params the RS-Breakout strategy accepts from the form.
_ALLOWED_PARAMS = {
    "trend_ma", "slope_lookback", "rs_lookback", "rs_edge", "gap_edge",
    "breakout_window", "range_mult", "atr_window", "vol_mult", "vol_window",
    "entry_window_bars", "stop_pct", "take_pct", "max_hold_bars",
}


def _ensure_reference(start: str, end: str, refresh: bool) -> None:
    """Fetch SPY and merge into the canonical reference file so both the scan and
    any downstream replay/backtest compare against the same, current index."""
    path = data_service.resolve_data_path("spy_daily_yfinance.parquet")
    if os.path.exists(path) and not refresh:
        return
    fetcher = DataFetcher()
    loader = DataLoader()
    df = fetcher.fetch_yfinance("SPY", start, end, "1d")
    new_clean = loader.clean_data(df)
    if os.path.exists(path):
        try:
            existing = loader.clean_data(loader.load_data(path))
            combined = pd.concat([existing, new_clean])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        except Exception:
            combined = new_clean
    else:
        combined = new_clean
    fetcher.save_to_parquet(combined, path)


def _entry_indices(signal: List[float]) -> List[int]:
    """Bar indices where the signal transitions flat -> long (a fresh entry)."""
    out = []
    for i in range(1, len(signal)):
        if signal[i] >= 0.5 and signal[i - 1] < 0.5:
            out.append(i)
    return out


def _summarize(symbol: str, fname: str, bars, diag: Dict[str, Any], window: int) -> Dict[str, Any]:
    cn = backtest_service._clean_num
    n = len(bars)
    signal = diag["signal"]
    has_ref = diag.get("has_reference", False)
    regime = diag.get("regime_armed", [])
    rs = diag.get("rs", [])

    entries = _entry_indices(signal)
    last_entry = entries[-1] if entries else None
    entries_in_window = sum(1 for i in entries if i >= n - window)

    armed_now = bool(regime[-1]) if regime else False
    long_now = bool(signal[-1] >= 0.5) if signal else False
    fresh_entry = bool(long_now and (n < 2 or signal[-2] < 0.5))
    rs_now = float(rs[-1]) if rs else 0.0

    # Composite rank: armed + fresh entry weigh most; recency and RS break ties.
    score = 0.0
    if armed_now:
        score += 3.0
    if fresh_entry:
        score += 3.0
    if long_now:
        score += 2.0
    score += min(entries_in_window, 10) * 0.4
    score += max(rs_now, 0.0) * 5.0
    if last_entry is not None:
        score += max(0.0, 1.0 - (n - 1 - last_entry) / max(window, 1)) * 1.0

    last_close = float(bars[-1].close) if n else 0.0
    last_ts = bars[-1].timestamp if n else None

    return {
        "symbol": symbol,
        "file": fname,
        "bars": n,
        "has_reference": has_ref,
        "armed_now": armed_now,
        "long_now": long_now,
        "fresh_entry": fresh_entry,
        "entries_in_window": entries_in_window,
        "total_entries": len(entries),
        "last_entry_bars_ago": (n - 1 - last_entry) if last_entry is not None else None,
        "rs_now": cn(rs_now),
        "last_close": cn(last_close),
        "last_date": last_ts.strftime("%Y-%m-%d") if last_ts is not None else None,
        "score": cn(score),
        "warning": None if has_ref else "Could not align SPY reference — result not meaningful.",
    }


def scan(
    tickers: Optional[List[str]],
    start: str,
    end: str,
    interval: str = "1d",
    params: Optional[Dict[str, Any]] = None,
    window: int = 60,
    refresh: bool = True,
) -> Dict[str, Any]:
    symbols = [t.strip().upper() for t in (tickers or DEFAULT_WATCHLIST) if t.strip()]
    symbols = list(dict.fromkeys(symbols))  # dedupe, preserve order
    params = params or {}
    kwargs = {k: v for k, v in params.items() if k in _ALLOWED_PARAMS}

    _ensure_reference(start, end, refresh)

    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    for sym in symbols:
        try:
            meta = data_service.fetch_ticker(sym, start, end, interval, merge=True, refresh=refresh)
            fname = meta["name"]
            path = data_service.resolve_data_path(fname)
            bars = DataLoader().get_bars(path)
            if len(bars) < 100:
                errors.append({"symbol": sym, "error": f"only {len(bars)} bars — need a longer range"})
                continue
            strat = RSBreakoutStrategy(**kwargs)
            diag = strat.diagnostics(bars)
            rows.append(_summarize(sym, fname, bars, diag, window))
        except Exception as e:  # noqa: BLE001 — one bad ticker shouldn't kill the scan
            errors.append({"symbol": sym, "error": str(e)})

    rows.sort(key=lambda r: r["score"], reverse=True)
    return {
        "results": rows,
        "errors": errors,
        "scanned": len(symbols),
        "window": window,
        "as_of": end,
    }

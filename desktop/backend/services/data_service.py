"""Data listing and on-demand ticker fetching (yfinance), reusing the suite's
DataFetcher/DataLoader so cached files match the existing format.

Fetching merges into the existing cache file rather than clobbering it, so a
replay session that points at a cached file isn't silently invalidated when the
user later fetches a different date range for the same ticker/interval."""

import json
import os
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from desktop.backend.paths import DATA_DIR
from desktop.backend.services import market_meta

from data.fetcher import DataFetcher
from data.dataloader import DataLoader

_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_CATALOG = "_catalog.json"


def _safe_name(name: str) -> str:
    return _SAFE.sub("_", name)


def _catalog_path() -> str:
    return os.path.join(DATA_DIR, _CATALOG)


def _read_catalog() -> Dict[str, Any]:
    try:
        with open(_catalog_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_catalog_entry(fname: str, meta: Dict[str, Any]) -> None:
    cat = _read_catalog()
    cat[fname] = meta
    try:
        with open(_catalog_path(), "w", encoding="utf-8") as f:
            json.dump(cat, f)
    except OSError:
        pass


def resolve_data_path(file: Optional[str]) -> str:
    """Resolve a data filename to an absolute path inside DATA_DIR.

    Guards against path traversal — only files under DATA_DIR are allowed.
    """
    if not file:
        # Default to the suite's canonical SPY dataset.
        file = "spy_daily_yfinance.parquet"
    candidate = os.path.abspath(os.path.join(DATA_DIR, os.path.basename(file)))
    if os.path.commonpath([candidate, os.path.abspath(DATA_DIR)]) != os.path.abspath(DATA_DIR):
        raise ValueError("Invalid data path.")
    return candidate


def list_data_files() -> List[Dict[str, Any]]:
    """List cached parquet datasets with lightweight metadata (enriched from the
    catalog written at fetch time)."""
    if not os.path.isdir(DATA_DIR):
        return []

    catalog = _read_catalog()
    files: List[Dict[str, Any]] = []
    loader = DataLoader()
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".parquet"):
            continue
        path = os.path.join(DATA_DIR, fname)
        meta: Dict[str, Any] = {"name": fname, "rows": None, "start": None, "end": None}
        meta.update(catalog.get(fname, {}))
        meta["name"] = fname
        try:
            df = loader.clean_data(loader.load_data(path))
            if not df.empty:
                meta["rows"] = int(len(df))
                meta["start"] = df.index[0].strftime("%Y-%m-%d")
                meta["end"] = df.index[-1].strftime("%Y-%m-%d")
                meta["intraday"] = bool(len(pd.unique(df.index.date)) < len(df))
        except Exception:
            pass
        files.append(meta)
    return files


def fetch_ticker(
    ticker: str,
    start: str,
    end: str,
    interval: str = "1d",
    merge: bool = True,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch a ticker via yfinance and cache it under DATA_DIR.

    Validates the interval/date range up front (friendly errors), fetches
    intraday ranges in yfinance-sized windows, and merges into any existing
    cache file for the same ticker/interval rather than overwriting it."""
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Please enter a ticker symbol.")

    # Up-front, actionable validation instead of a raw empty-result error.
    market_meta.validate_range(interval, start, end)

    fetcher = DataFetcher()
    windows = market_meta.plan_fetch_windows(interval, start, end)
    frames = []
    for w_start, w_end in windows:
        try:
            frames.append(fetcher.fetch_yfinance(symbol, w_start, w_end, interval))
        except Exception as e:  # noqa: BLE001
            raise ValueError(market_meta.friendly_fetch_error(e, symbol, interval, start, end))
    if not frames:
        raise ValueError(market_meta.friendly_fetch_error(
            ValueError("no data"), symbol, interval, start, end))
    df = pd.concat(frames) if len(frames) > 1 else frames[0]

    fname = f"{_safe_name(symbol)}_{_safe_name(interval)}.parquet"
    path = os.path.join(DATA_DIR, fname)

    loader = DataLoader()
    new_clean = loader.clean_data(df)
    if merge and not refresh and os.path.exists(path):
        try:
            existing = loader.clean_data(loader.load_data(path))
            combined = pd.concat([existing, new_clean])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
        except Exception:
            combined = new_clean
    else:
        combined = new_clean

    fetcher.save_to_parquet(combined, path)

    cleaned = loader.clean_data(loader.load_data(path))
    meta = {
        "name": fname,
        "rows": int(len(cleaned)),
        "start": cleaned.index[0].strftime("%Y-%m-%d") if not cleaned.empty else None,
        "end": cleaned.index[-1].strftime("%Y-%m-%d") if not cleaned.empty else None,
        "ticker": symbol,
        "interval": interval,
        "intraday": bool(not cleaned.empty and len(pd.unique(cleaned.index.date)) < len(cleaned)),
    }
    _write_catalog_entry(fname, meta)
    return meta

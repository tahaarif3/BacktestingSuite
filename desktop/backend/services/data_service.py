"""Data listing and on-demand ticker fetching (yfinance), reusing the suite's
DataFetcher/DataLoader so cached files match the existing format."""

import os
import re
from typing import Any, Dict, List, Optional

from desktop.backend.paths import DATA_DIR

from data.fetcher import DataFetcher
from data.dataloader import DataLoader

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_name(name: str) -> str:
    return _SAFE.sub("_", name)


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
    """List cached parquet datasets with lightweight metadata."""
    if not os.path.isdir(DATA_DIR):
        return []

    files: List[Dict[str, Any]] = []
    loader = DataLoader()
    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".parquet"):
            continue
        path = os.path.join(DATA_DIR, fname)
        meta: Dict[str, Any] = {"name": fname, "rows": None, "start": None, "end": None}
        try:
            df = loader.clean_data(loader.load_data(path))
            if not df.empty:
                meta["rows"] = int(len(df))
                meta["start"] = df.index[0].strftime("%Y-%m-%d")
                meta["end"] = df.index[-1].strftime("%Y-%m-%d")
        except Exception:
            pass
        files.append(meta)
    return files


def fetch_ticker(ticker: str, start: str, end: str, interval: str = "1d") -> Dict[str, Any]:
    """Fetch a ticker via yfinance, cache to a parquet under DATA_DIR, and
    return metadata for the cached file."""
    fetcher = DataFetcher()
    df = fetcher.fetch_yfinance(ticker.upper(), start, end, interval)

    fname = f"{_safe_name(ticker.upper())}_{_safe_name(interval)}.parquet"
    path = os.path.join(DATA_DIR, fname)
    fetcher.save_to_parquet(df, path)

    loader = DataLoader()
    cleaned = loader.clean_data(loader.load_data(path))
    return {
        "name": fname,
        "rows": int(len(cleaned)),
        "start": cleaned.index[0].strftime("%Y-%m-%d") if not cleaned.empty else None,
        "end": cleaned.index[-1].strftime("%Y-%m-%d") if not cleaned.empty else None,
    }

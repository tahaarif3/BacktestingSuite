"""Market-data metadata: interval limits, range validation, ticker lookup.

The validation/planning half is **pure** (no network, injectable ``today``) so
it is unit-testable; the ``validate_ticker`` / ``search_tickers`` half talks to
yfinance. ``friendly_fetch_error`` turns raw yfinance failures into messages a
user can act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class IntervalLimits:
    id: str
    label: str
    intraday: bool
    # How far back yfinance serves this granularity (days); None = full history.
    max_lookback_days: Optional[int]
    # Max span per single request (days); None = unlimited.
    max_span_days: Optional[int]

    @property
    def note(self) -> str:
        if self.max_lookback_days is None:
            return "Full history available."
        if self.max_span_days is not None and self.max_span_days < self.max_lookback_days:
            return (
                f"Last {self.max_lookback_days} days only; "
                f"fetched {self.max_span_days} days at a time."
            )
        return f"Last {self.max_lookback_days} days only."


# yfinance's documented granularity limits.
INTERVALS: Dict[str, IntervalLimits] = {
    "1m": IntervalLimits("1m", "1 minute", True, 30, 7),
    "2m": IntervalLimits("2m", "2 minutes", True, 60, 60),
    "5m": IntervalLimits("5m", "5 minutes", True, 60, 60),
    "15m": IntervalLimits("15m", "15 minutes", True, 60, 60),
    "30m": IntervalLimits("30m", "30 minutes", True, 60, 60),
    "60m": IntervalLimits("60m", "60 minutes", True, 730, 730),
    "90m": IntervalLimits("90m", "90 minutes", True, 60, 60),
    "1h": IntervalLimits("1h", "1 hour", True, 730, 730),
    "1d": IntervalLimits("1d", "1 day", False, None, None),
    "5d": IntervalLimits("5d", "5 days", False, None, None),
    "1wk": IntervalLimits("1wk", "1 week", False, None, None),
    "1mo": IntervalLimits("1mo", "1 month", False, None, None),
    "3mo": IntervalLimits("3mo", "3 months", False, None, None),
}


def list_intervals() -> List[Dict[str, Any]]:
    return [
        {
            "id": i.id,
            "label": i.label,
            "intraday": i.intraday,
            "max_lookback_days": i.max_lookback_days,
            "max_span_days": i.max_span_days,
            "note": i.note,
        }
        for i in INTERVALS.values()
    ]


def _get(interval: str) -> IntervalLimits:
    spec = INTERVALS.get(interval)
    if spec is None:
        raise ValueError(
            f"'{interval}' is not a supported interval. "
            f"Choose one of: {', '.join(INTERVALS)}."
        )
    return spec


def _parse(d: str) -> date:
    return datetime.strptime(d[:10], "%Y-%m-%d").date()


def validate_range(
    interval: str, start: str, end: str, *, today: Optional[date] = None
) -> None:
    """Raise ValueError with an actionable message if the range is invalid for
    the interval. Pure — ``today`` is injectable so tests need no clock."""
    spec = _get(interval)
    today = today or date.today()
    s = _parse(start)
    e = _parse(end)
    if e < s:
        raise ValueError("The end date is before the start date.")

    if spec.max_lookback_days is not None:
        earliest = today - timedelta(days=spec.max_lookback_days)
        if s < earliest:
            raise ValueError(
                f"{spec.label} data is only available for the last "
                f"{spec.max_lookback_days} days. Try a start date on or after "
                f"{earliest.isoformat()}."
            )


def clamp_range(
    interval: str, start: str, end: str, *, today: Optional[date] = None
) -> Tuple[str, str]:
    """Return the nearest valid (start, end) for the interval."""
    spec = _get(interval)
    today = today or date.today()
    s = _parse(start)
    e = _parse(end)
    if e > today:
        e = today
    if spec.max_lookback_days is not None:
        earliest = today - timedelta(days=spec.max_lookback_days)
        if s < earliest:
            s = earliest
    if e < s:
        e = s
    return s.isoformat(), e.isoformat()


def plan_fetch_windows(interval: str, start: str, end: str) -> List[Tuple[str, str]]:
    """Split [start, end] into contiguous windows no larger than the interval's
    per-request span. Pure — the testable half of chunked intraday fetching."""
    spec = _get(interval)
    s = _parse(start)
    e = _parse(end)
    if e < s:
        return []
    if spec.max_span_days is None:
        return [(s.isoformat(), e.isoformat())]

    windows: List[Tuple[str, str]] = []
    cur = s
    span = timedelta(days=spec.max_span_days)
    while cur <= e:
        win_end = min(cur + span - timedelta(days=1), e)
        windows.append((cur.isoformat(), win_end.isoformat()))
        cur = win_end + timedelta(days=1)
    return windows


# --- network-backed lookups -------------------------------------------------


def validate_ticker(
    ticker: str,
    interval: str = "1d",
    start: Optional[str] = None,
    end: Optional[str] = None,
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Resolve instrument metadata via one yfinance metadata call. Raises
    LookupError if the symbol doesn't resolve."""
    import yfinance as yf

    symbol = ticker.strip().upper()
    if not symbol:
        raise LookupError("Please enter a ticker symbol.")

    meta: Dict[str, Any] = {}
    try:
        meta = yf.Ticker(symbol).get_history_metadata() or {}
    except Exception:
        meta = {}

    long_name = meta.get("longName")
    exchange = meta.get("fullExchangeName") or meta.get("exchangeName")
    currency = meta.get("currency")
    tz = meta.get("exchangeTimezoneName") or meta.get("timezone")
    itype = meta.get("instrumentType")
    first_ts = meta.get("firstTradeDate")

    if not (long_name or exchange or currency):
        # Fall back to fast_info before giving up.
        try:
            fi = yf.Ticker(symbol).fast_info
            currency = currency or fi.get("currency")
            exchange = exchange or fi.get("exchange")
        except Exception:
            fi = None
        if not (currency or exchange):
            raise LookupError(
                f"'{symbol}' didn't match any listed security. Check the symbol."
            )

    first_trade_date = None
    if first_ts:
        try:
            first_trade_date = datetime.utcfromtimestamp(int(first_ts)).date().isoformat()
        except (TypeError, ValueError, OSError):
            first_trade_date = None

    info: Dict[str, Any] = {
        "ticker": symbol,
        "valid": True,
        "long_name": long_name,
        "short_name": meta.get("shortName"),
        "exchange": exchange,
        "currency": currency,
        "timezone": tz,
        "instrument_type": itype,
        "first_trade_date": first_trade_date,
        "valid_intervals": list(INTERVALS.keys()),
        "range_ok": True,
        "range_message": None,
        "suggested_start": None,
        "suggested_end": None,
    }

    if start and end:
        try:
            validate_range(interval, start, end, today=today)
        except ValueError as exc:
            cs, ce = clamp_range(interval, start, end, today=today)
            info.update(
                range_ok=False,
                range_message=str(exc),
                suggested_start=cs,
                suggested_end=ce,
            )
    return info


def search_tickers(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Autocomplete via yfinance Search (falling back to Lookup)."""
    import yfinance as yf

    q = query.strip()
    if not q:
        return []

    hits: List[Dict[str, Any]] = []
    try:
        quotes = yf.Search(q, max_results=limit).quotes or []
        for row in quotes:
            hits.append(
                {
                    "symbol": row.get("symbol"),
                    "name": row.get("longname") or row.get("shortname"),
                    "exchange": row.get("exchDisp") or row.get("exchange"),
                    "quote_type": row.get("quoteType"),
                }
            )
    except Exception:
        try:
            df = yf.Lookup(q).get_all(count=limit)
            for sym, row in df.iterrows():
                hits.append(
                    {
                        "symbol": sym,
                        "name": row.get("shortName") or row.get("longName"),
                        "exchange": row.get("exchange"),
                        "quote_type": row.get("quoteType") or row.get("type"),
                    }
                )
        except Exception:
            return []
    return [h for h in hits if h.get("symbol")][:limit]


def friendly_fetch_error(
    exc: Exception, ticker: str, interval: str, start: str, end: str
) -> str:
    """Map a raw fetch failure to a message a user can act on."""
    symbol = ticker.strip().upper()
    raw = str(exc).lower()
    spec = INTERVALS.get(interval)

    if "no data" in raw or "no price data" in raw or "empty" in raw:
        if spec and spec.max_lookback_days is not None:
            return (
                f"No {spec.label} data for {symbol} between {start} and {end}. "
                f"{spec.label} data only goes back {spec.max_lookback_days} days, "
                "and weekends/holidays have no bars — try a wider or more recent range."
            )
        return (
            f"No data for {symbol} between {start} and {end}. "
            "Check the symbol and date range."
        )
    if "delisted" in raw or "not found" in raw or "404" in raw:
        return f"'{symbol}' didn't match any listed security. Check the symbol."
    if "timed out" in raw or "connection" in raw or "resolve" in raw or "network" in raw:
        return (
            "Couldn't reach Yahoo Finance. Check your connection — cached datasets "
            "still work, pick one under Dataset."
        )
    return f"Couldn't fetch {symbol}: {exc}"

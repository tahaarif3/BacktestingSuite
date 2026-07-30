"""Stateful multi-symbol options **portfolio replay** — the "market replay with a
live scanner" mode.

One shared clock (SPY's trading calendar) drives a watchlist of tradeable
symbols. At session build we align every symbol to the SPY date axis and
precompute each one's RS-Breakout diagnostics (causal), so the radar at any
cursor is just an index lookup. Trades are option structures opened/closed per
symbol against one shared cash account (``options.portfolio_ledger``), recomputed
from the order list on every read.

In-memory only (no disk persistence) — this is a heavier, exploratory session
type; the shipped single-instrument replay remains the persistent one.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from desktop.backend.services import backtest_service, data_service, screener_service

from data.dataloader import DataLoader
from domain.models import Bar
from backtest.execution import ExecutionModel
from strat.rs_breakout import RSBreakoutStrategy
from options.volatility import realized_vol_series, iv_for_bar
from options.pricing import bars_per_year
from options.portfolio import mark_structure
from options.portfolio_ledger import PortfolioOptionOrder, build_portfolio_options_ledger

MAX_SESSIONS = 3
MAX_SYMBOLS = 15
MAX_AXIS_BARS = 20_000

_LOCK = threading.RLock()
_SESSIONS: "OrderedDict[str, PortfolioSession]" = OrderedDict()

_ALLOWED_PARAMS = screener_service._ALLOWED_PARAMS


class SessionNotFound(KeyError):
    pass


class OrderRejected(ValueError):
    pass


@dataclass
class SymbolData:
    o: List[Optional[float]]
    h: List[Optional[float]]
    l: List[Optional[float]]
    c: List[Optional[float]]
    v: List[Optional[float]]
    iv: List[float]
    signal: List[float]
    regime: List[bool]
    rs: List[float]
    enter: List[bool]
    has_reference: bool


@dataclass
class PortfolioSession:
    id: str
    created_at: float
    capital: float
    timing: str
    risk_free_rate: float
    margin_policy: str
    interval: str
    annualization: float
    dates: List[datetime]
    start_index: int
    cursor: int
    high_water: int
    symbols: List[str]
    data: Dict[str, SymbolData]
    spy: SymbolData
    orders: List[PortfolioOptionOrder]
    warnings: List[str]
    last_touched_at: float = 0.0


# --- build helpers ----------------------------------------------------------


def _iv_from_closes(closes: List[Optional[float]], window: int, mult: float,
                    override: Optional[float], floor: float, cap: float,
                    annualization: float = 252.0) -> List[float]:
    # forward/back-fill for a continuous vol estimate; only used where a spot exists
    filled: List[float] = []
    last = None
    for x in closes:
        if x is not None:
            last = x
        filled.append(last if last is not None else 0.0)
    first = next((x for x in filled if x > 0), 1.0)
    filled = [x if x > 0 else first for x in filled]
    rv = realized_vol_series(filled, window=window, annualization=annualization)
    return [iv_for_bar(v, iv_multiplier=mult, iv_override=override, iv_floor=floor, iv_cap=cap)
            for v in rv]


def _align(sym_bars: List[Bar], axis_dates: List[datetime]):
    # Key by full timestamp so intraday bars (many per day) align correctly.
    by_ts = {b.timestamp: b for b in sym_bars}
    o, h, l, c, v = [], [], [], [], []
    for d in axis_dates:
        b = by_ts.get(d)
        o.append(b.open if b else None)
        h.append(b.high if b else None)
        l.append(b.low if b else None)
        c.append(b.close if b else None)
        v.append(b.volume if b else None)
    return o, h, l, c, v


def _align_diag(sym_bars: List[Bar], diag: Dict[str, Any], key, axis_dates, default):
    idx = {b.timestamp: i for i, b in enumerate(sym_bars)}
    arr = diag.get(key, [])
    return [arr[idx[d]] if d in idx and idx[d] < len(arr) else default for d in axis_dates]


def create_session(cfg: Dict[str, Any]) -> Dict[str, Any]:
    tickers = [t.strip().upper() for t in (cfg.get("tickers") or screener_service.DEFAULT_WATCHLIST)
               if t.strip()]
    tickers = list(dict.fromkeys(tickers))[:MAX_SYMBOLS]
    if not tickers:
        raise ValueError("Provide at least one watchlist symbol.")
    start, end = cfg["start"], cfg["end"]
    interval = cfg.get("interval", "1d")
    annualization = bars_per_year(interval)
    capital = float(cfg.get("capital", 100000.0))
    timing = cfg.get("timing", "next_close")
    warmup = int(cfg.get("warmup_bars", 120))
    refresh = bool(cfg.get("refresh", True))
    params = {k: v for k, v in (cfg.get("params") or {}).items() if k in _ALLOWED_PARAMS}
    vol = cfg.get("vol") or {}
    r = float(vol.get("risk_free_rate", 0.04))
    iv_window = int(vol.get("iv_window", 20))
    iv_mult = float(vol.get("iv_multiplier", 1.0))
    iv_override = vol.get("iv_override")
    iv_floor = float(vol.get("iv_floor", 0.05))
    iv_cap = float(vol.get("iv_cap", 3.0))
    margin_policy = vol.get("margin_policy", "defined_risk")

    warnings: List[str] = []

    # SPY drives the clock + is the strategy's reference — fetched at the chosen
    # interval so intraday sessions align to intraday SPY bars.
    if interval == "1d":
        screener_service._ensure_reference(start, end, refresh)
        spy_ref_file = "spy_daily_yfinance.parquet"
    else:
        spy_ref_file = f"SPY_{interval}.parquet"
        spy_ref_path = data_service.resolve_data_path(spy_ref_file)
        if refresh or not os.path.exists(spy_ref_path):
            data_service.fetch_ticker("SPY", start, end, interval, merge=True, refresh=refresh)
    spy_path = data_service.resolve_data_path(spy_ref_file)
    spy_all = DataLoader().get_bars(spy_path)
    sd, ed = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    spy_bars = [b for b in spy_all if sd <= b.timestamp.date() <= ed]
    if len(spy_bars) < 3:
        raise ValueError("Not enough SPY history for that range/interval.")
    if len(spy_bars) > MAX_AXIS_BARS:
        raise ValueError(f"Range too long ({len(spy_bars)} bars); shorten it.")
    axis_dates = [b.timestamp for b in spy_bars]

    spy_o, spy_h, spy_l, spy_c, spy_v = _align(spy_bars, axis_dates)
    spy_iv = _iv_from_closes(spy_c, iv_window, iv_mult, iv_override, iv_floor, iv_cap, annualization)
    spy_data = SymbolData(spy_o, spy_h, spy_l, spy_c, spy_v, spy_iv,
                          [0.0] * len(axis_dates), [False] * len(axis_dates),
                          [0.0] * len(axis_dates), [False] * len(axis_dates), True)

    min_bars = 100 if interval == "1d" else 60
    data: Dict[str, SymbolData] = {}
    kept: List[str] = []
    for sym in tickers:
        try:
            meta = data_service.fetch_ticker(sym, start, end, interval, merge=True, refresh=refresh)
            path = data_service.resolve_data_path(meta["name"])
            sym_bars = DataLoader().get_bars(path)
            if len(sym_bars) < min_bars:
                warnings.append(f"{sym}: only {len(sym_bars)} bars — skipped")
                continue
            diag = RSBreakoutStrategy(spy_file=spy_ref_file, **params).diagnostics(sym_bars)
            o, h, l, c, v = _align(sym_bars, axis_dates)
            iv = _iv_from_closes(c, iv_window, iv_mult, iv_override, iv_floor, iv_cap, annualization)
            data[sym] = SymbolData(
                o, h, l, c, v, iv,
                _align_diag(sym_bars, diag, "signal", axis_dates, 0.0),
                _align_diag(sym_bars, diag, "regime_armed", axis_dates, False),
                _align_diag(sym_bars, diag, "rs", axis_dates, 0.0),
                _align_diag(sym_bars, diag, "enter", axis_dates, False),
                bool(diag.get("has_reference", False)),
            )
            kept.append(sym)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{sym}: {e}")

    if not kept:
        raise ValueError("No watchlist symbols could be loaded.")

    start_index = max(0, min(warmup, len(axis_dates) - 2))
    sid = uuid.uuid4().hex[:12]
    s = PortfolioSession(
        id=sid, created_at=time.time(), capital=capital, timing=timing, risk_free_rate=r,
        margin_policy=margin_policy, interval=interval, annualization=annualization,
        dates=axis_dates, start_index=start_index,
        cursor=start_index, high_water=start_index, symbols=kept, data=data, spy=spy_data,
        orders=[], warnings=warnings,
    )
    with _LOCK:
        _SESSIONS[sid] = s
        _touch(s)
        while len(_SESSIONS) > MAX_SESSIONS:
            old, _ = next(iter(_SESSIONS.items()))
            _SESSIONS.pop(old, None)
        return _create_payload(s)


# --- session access ---------------------------------------------------------


def _touch(s: PortfolioSession) -> None:
    s.last_touched_at = time.time()
    _SESSIONS.move_to_end(s.id)


def _require(sid: str) -> PortfolioSession:
    s = _SESSIONS.get(sid)
    if s is None:
        raise SessionNotFound(f"Portfolio session not found: {sid}")
    _touch(s)
    return s


def _exec_model() -> ExecutionModel:
    return ExecutionModel(slippage_pct=0.0002, commission_pct=0.0005)


def _ledger(s: PortfolioSession, upto: int):
    closes = {sym: s.data[sym].c for sym in s.symbols}
    opens = {sym: s.data[sym].o for sym in s.symbols}
    iv = {sym: s.data[sym].iv for sym in s.symbols}
    return build_portfolio_options_ledger(
        dates=s.dates, closes=closes, opens=opens, iv=iv, orders=s.orders,
        upto_index=upto, capital=s.capital, exec_model=_exec_model(),
        timing=s.timing, risk_free_rate=s.risk_free_rate, margin_policy=s.margin_policy,
        annualization=s.annualization,
    )


# --- payloads ---------------------------------------------------------------


def _radar(s: PortfolioSession, cursor: int) -> List[Dict[str, Any]]:
    cn = backtest_service._clean_num
    rows = []
    for sym in s.symbols:
        d = s.data[sym]
        available = d.c[cursor] is not None
        sig = d.signal[cursor]
        prev = d.signal[cursor - 1] if cursor > 0 else 0.0
        rows.append({
            "symbol": sym,
            "available": available,
            "armed": bool(d.regime[cursor]),
            "long": bool(sig >= 0.5),
            "fresh_entry": bool(sig >= 0.5 and prev < 0.5),
            "rs": cn(d.rs[cursor]),
            "close": cn(d.c[cursor]) if available else None,
            "has_reference": d.has_reference,
        })
    rows.sort(key=lambda r: (r["fresh_entry"], r["armed"], r["long"], r["rs"]), reverse=True)
    return rows


def _account(s: PortfolioSession, led, cursor: int) -> Dict[str, Any]:
    cn = backtest_service._clean_num
    positions = []
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for sym, structs in led.open_by_symbol.items():
        spot = s.data[sym].c[cursor]
        if spot is None:
            continue
        sigma = s.data[sym].iv[cursor]
        for st in structs:
            marked = mark_structure(st, spot, cursor, s.risk_free_rate, sigma, s.annualization)
            for k in net:
                net[k] += marked["greeks"][k]
            ml = st.max_loss
            positions.append({
                "symbol": sym,
                "id": st.id,
                "structure_type": st.structure_type,
                "contracts": st.contracts,
                "dte_bars": max(st.expiry_index - cursor, 0),
                "value": cn(marked["value"]),
                "max_risk": cn(abs(ml)) if ml != float("-inf") else None,
                "breakevens": [cn(b) for b in st.breakevens],
                "greeks": {k: cn(val) for k, val in marked["greeks"].items()},
                "legs": [{"kind": lm["kind"], "strike": cn(lm["strike"]), "quantity": lm["quantity"],
                          "mark": cn(lm["mark"]), "delta": cn(lm["delta"]), "theta": cn(lm["theta"])}
                         for lm in marked["legs"]],
            })
    return {
        "cash": cn(led.final_cash),
        "equity": cn(led.final_equity),
        "net_liq": cn(led.final_equity),
        "realized_pnl": cn(led.realized_pnl),
        "unrealized_pnl": cn(led.unrealized_pnl),
        "total_return": cn(led.final_equity / s.capital - 1.0),
        "max_risk": cn(led.max_risk),
        "buying_power_used": cn(led.max_risk),
        "net_delta": cn(net["delta"]),
        "net_theta": cn(net["theta"]),
        "net_vega": cn(net["vega"]),
        "positions": positions,
    }


def _fill_dict(f) -> Dict[str, Any]:
    cn = backtest_service._clean_num
    return {"symbol": f.symbol, "structure_id": f.structure_id, "fill_index": f.fill_index,
            "action": f.action, "structure_type": f.structure_type, "spot": cn(f.spot),
            "net_cash": cn(f.net_cash), "realized_pnl": cn(f.realized_pnl)}


def _state_payload(s: PortfolioSession) -> Dict[str, Any]:
    cursor = max(s.start_index, min(s.cursor, len(s.dates) - 1))
    led = _ledger(s, cursor)
    tail = [backtest_service._clean_num(v) for v in led.equity_curve[-500:]]
    return {
        "session_id": s.id,
        "cursor": cursor,
        "high_water": s.high_water,
        "start_index": s.start_index,
        "total_bars": len(s.dates),
        "at_end": cursor >= len(s.dates) - 1,
        "radar": _radar(s, cursor),
        "account": _account(s, led, cursor),
        "fills": [_fill_dict(f) for f in led.fills],
        "equity_tail": tail,
        "warnings": s.warnings,
    }


def _iso(dates) -> List[str]:
    return [d.strftime("%Y-%m-%d") for d in dates]


def _signal_bars(s: PortfolioSession) -> List[int]:
    """Axis indices where ANY watched symbol has a fresh entry — the bars the
    playback pauses on ('a name just fired')."""
    hits = set()
    for sym in s.symbols:
        enter = s.data[sym].enter
        for i in range(max(1, s.start_index), len(enter)):
            if enter[i]:
                hits.add(i)
    return sorted(hits)


def _create_payload(s: PortfolioSession) -> Dict[str, Any]:
    cn = backtest_service._clean_num
    return {
        "session_id": s.id,
        "total_bars": len(s.dates),
        "start_index": s.start_index,
        "cursor": s.cursor,
        "capital": s.capital,
        "symbols": s.symbols,
        "signal_bars": _signal_bars(s),
        "dates": _iso(s.dates),
        "spy": {
            "o": [cn(x) if x is not None else None for x in s.spy.o],
            "h": [cn(x) if x is not None else None for x in s.spy.h],
            "l": [cn(x) if x is not None else None for x in s.spy.l],
            "c": [cn(x) if x is not None else None for x in s.spy.c],
            "v": [cn(x) if x is not None else None for x in s.spy.v],
        },
        "warnings": s.warnings,
        "state": _state_payload(s),
    }


def get_state(sid: str) -> Dict[str, Any]:
    with _LOCK:
        return _state_payload(_require(sid))


def symbol_bars(sid: str, symbol: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        symbol = symbol.upper()
        if symbol not in s.data:
            raise SessionNotFound(f"Symbol not in session: {symbol}")
        d = s.data[symbol]
        cn = backtest_service._clean_num
        na = lambda arr: [cn(x) if x is not None else None for x in arr]
        return {
            "symbol": symbol,
            "dates": _iso(s.dates),
            "o": na(d.o), "h": na(d.h), "l": na(d.l), "c": na(d.c), "v": na(d.v),
            "signal": [cn(x) for x in d.signal],
            "regime": [1.0 if x else 0.0 for x in d.regime],
        }


# --- mutations ---------------------------------------------------------------


def _recompute_high_water(s: PortfolioSession) -> None:
    s.high_water = max([o.bar_index + 1 for o in s.orders], default=s.start_index)


def submit_order(sid: str, req: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        bar = int(req["bar_index"])
        symbol = str(req["symbol"]).upper()
        action = req.get("action", "open")
        if symbol not in s.data:
            raise OrderRejected(f"{symbol} is not in this session.")
        if bar < s.start_index:
            raise OrderRejected(f"Trading starts at bar {s.start_index}.")
        if bar < s.high_water:
            raise OrderRejected(f"Already decided at/after bar {s.high_water}; rewind to change.")
        if bar + 1 >= len(s.dates):
            raise OrderRejected("No bar after this one to fill against.")
        if s.data[symbol].c[bar + 1] is None:
            raise OrderRejected(f"{symbol} has no price at the fill bar.")

        struct = req.get("structure") or {}
        if action == "open":
            oid = f"p{len(s.orders) + 1}_{symbol}_{bar}"
            order = PortfolioOptionOrder(
                id=oid, symbol=symbol, bar_index=bar, action="open",
                structure_type=struct.get("structure_type", "bull_put_spread"),
                selection=struct.get("selection", "delta"),
                short_delta=float(struct.get("short_delta", 0.3)),
                pct_otm=float(struct.get("pct_otm", 0.05)),
                width=float(struct.get("width", 5.0)),
                strikes=struct.get("strikes"),
                dte_bars=int(struct.get("dte_bars", 30)),
                contracts=int(struct.get("contracts", 1)),
                grid_spacing=float(struct.get("grid_spacing", 5.0)),
                note=req.get("note", ""),
            )
        else:
            oid = f"pc{len(s.orders) + 1}_{symbol}_{bar}"
            order = PortfolioOptionOrder(
                id=oid, symbol=symbol, bar_index=bar, action="close",
                target_structure_id=req.get("target_structure_id"), note=req.get("note", ""),
            )

        candidate = list(s.orders) + [order]
        led = build_portfolio_options_ledger(
            dates=s.dates, closes={k: s.data[k].c for k in s.symbols},
            opens={k: s.data[k].o for k in s.symbols}, iv={k: s.data[k].iv for k in s.symbols},
            orders=candidate, upto_index=bar + 1, capital=s.capital, exec_model=_exec_model(),
            timing=s.timing, risk_free_rate=s.risk_free_rate, margin_policy=s.margin_policy,
            annualization=s.annualization,
        )
        if action == "open" and led.max_risk > s.capital + 1e-6 and s.margin_policy == "defined_risk":
            raise OrderRejected(
                f"Not enough buying power: portfolio risk ${led.max_risk:,.0f} vs ${s.capital:,.0f}.")

        s.orders.append(order)
        _recompute_high_water(s)
        s.cursor = max(s.cursor, bar + 1)
        return {"accepted": True, "state": _state_payload(s)}


def seek(sid: str, to_index: int) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        s.cursor = max(s.start_index, min(to_index, len(s.dates) - 1))
        return _state_payload(s)


def rewind(sid: str, to_index: int) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        to_index = max(s.start_index, to_index)
        s.orders = [o for o in s.orders if o.bar_index < to_index]
        _recompute_high_water(s)
        s.cursor = max(s.start_index, min(to_index, len(s.dates) - 1))
        return _state_payload(s)


def reset(sid: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        s.orders = []
        s.high_water = s.start_index
        s.cursor = s.start_index
        return _state_payload(s)


def undo(sid: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        if not s.orders:
            raise OrderRejected("No orders to undo.")
        s.orders.pop()
        _recompute_high_water(s)
        return _state_payload(s)


def delete_session(sid: str) -> None:
    with _LOCK:
        _SESSIONS.pop(sid, None)


def score(sid: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        cursor = max(s.start_index, min(s.cursor, len(s.dates) - 1))
        led = _ledger(s, cursor)
        cn = backtest_service._clean_num
        # user equity curve vs SPY buy & hold (rebased to capital at the start).
        eq = led.equity_curve
        spy_c = s.spy.c
        base = next((spy_c[i] for i in range(s.start_index, cursor + 1) if spy_c[i]), None)
        bench = []
        for i in range(len(eq)):
            px = spy_c[i] if i < len(spy_c) else None
            bench.append(cn(s.capital * (px / base)) if (px and base) else cn(s.capital))
        trades = [{
            "symbol": c.symbol, "structure": c.structure_type, "contracts": c.contracts,
            "open_index": c.open_index, "close_index": c.close_index,
            "pnl_usd": cn(c.pnl_usd), "max_risk": cn(c.max_risk), "reason": c.reason,
            "pnl_pct": cn(c.pnl_usd / c.max_risk) if c.max_risk > 1e-9 else 0.0,
        } for c in led.closed_trades]
        wins = [t for t in trades if t["pnl_usd"] > 0]
        return {
            "cursor": cursor,
            "dates": _iso(s.dates[: cursor + 1]),
            "equity": [cn(v) for v in eq[: cursor + 1]],
            "benchmark": bench[: cursor + 1],
            "final_equity": cn(led.final_equity),
            "total_return": cn(led.final_equity / s.capital - 1.0),
            "realized_pnl": cn(led.realized_pnl),
            "unrealized_pnl": cn(led.unrealized_pnl),
            "trades": trades,
            "win_rate": cn(len(wins) / len(trades)) if trades else 0.0,
            "total_trades": len(trades),
            "warnings": s.warnings + [
                "Options priced with a Black-Scholes synthetic model (realized-vol IV, no vol risk "
                "premium); short-premium P&L is understated vs. a real market."
            ],
        }

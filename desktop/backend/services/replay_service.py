"""Stateful session layer for the replay / manual-trading feature.

Sessions are the authoritative ledger: every user order is stored, and account
state is recomputed from the order list on each read (build_ledger is ~7 ms, so
this is free and makes undo/rewind/reset trivial and drift-proof). The frontend
owns the smooth playback cursor; the backend only needs to know the furthest
decision bar (``high_water``) to keep the ledger forward-only, and it persists a
few hundred bytes per session so a replay survives an app restart / auto-update.

Concurrency: FastAPI runs ``def`` handlers in a threadpool, so a module-level
RLock guards every public mutation.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from desktop.backend import paths
from desktop.backend.schemas import (
    CreateReplaySessionRequest,
    ReplayOrderRequest,
    ReplaySessionConfig,
)
from desktop.backend.services import backtest_service
from desktop.backend.services import data_service

from data.dataloader import DataLoader
from domain.models import Bar
from backtest.execution import ExecutionModel
from strategy_registry import STRATEGIES, USER_STRATEGIES_DIR, build_sizer, build_strategy

from analytics.metrics import PerformanceMetrics, extract_trades
from desktop.backend.services.replay_ledger import (
    CASH_EPS,
    TRADE_EPS,
    LedgerResult,
    ReplayOrder,
    audit_causality,
    build_ledger,
    derive_signal_events,
    is_intraday,
    iso_index,
)
from options.ledger import OptionOrder, OptionsLedgerResult, build_iv_series, build_options_ledger
from options.portfolio import mark_structure, reconstruct_option_trades
from options.structures import StructureSpec
from backtest.options_engine import OptionsEventDrivenEngine

# --- limits -----------------------------------------------------------------

MAX_SESSIONS = 6
MAX_SESSION_BARS = 50_000
SESSION_TTL_SECONDS = 6 * 3600
DEFAULT_BAR_CHUNK = 5_000
MAX_BAR_CHUNK = 20_000
PERSIST_VERSION = 1

_LOCK = threading.RLock()
_SESSIONS: "OrderedDict[str, ReplaySession]" = OrderedDict()


# --- exceptions -------------------------------------------------------------


class SessionNotFound(KeyError):
    pass


class OrderRejected(ValueError):
    pass


class SessionTooLarge(ValueError):
    pass


class SessionStale(RuntimeError):
    pass


# --- session ----------------------------------------------------------------


@dataclass
class ReplaySession:
    # persisted
    id: str
    created_at: float
    config: ReplaySessionConfig
    start_index: int
    cursor: int
    high_water: int
    orders: List[ReplayOrder]
    option_orders: List[OptionOrder]
    data_fingerprint: str
    strategy_fingerprint: str
    # derived (never persisted)
    bars: List[Bar] = field(default_factory=list)
    masked: List[float] = field(default_factory=list)
    algo_target_positions: List[float] = field(default_factory=list)
    algo_min_cash: float = 0.0
    signal_events: List = field(default_factory=list)
    causality: Dict[str, Any] = field(default_factory=dict)
    strategy_name: str = ""
    resolved_params: Dict[str, Any] = field(default_factory=dict)
    symbol: str = ""
    interval: str = "1d"
    intraday: bool = False
    tz_name: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    stale: bool = False
    last_touched_at: float = 0.0
    _ledger_cache: Optional[LedgerResult] = None
    _ledger_upto: int = -1
    _opt_ledger_cache: Optional[OptionsLedgerResult] = None
    _opt_ledger_upto: int = -1

    @property
    def is_options(self) -> bool:
        return self.config.mode == "options"


# --- helpers ----------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exec_model(cfg: ReplaySessionConfig) -> ExecutionModel:
    return ExecutionModel(
        slippage_pct=cfg.slippage_pct,
        commission_pct=cfg.commission_pct,
        commission_per_share=cfg.commission_per_share,
    )


def _sizer_factory(cfg: ReplaySessionConfig):
    return lambda: build_sizer(cfg.sizer, cfg.sizer_value, cfg.capital)


def _touch(s: ReplaySession) -> None:
    s.last_touched_at = time.time()
    _SESSIONS.move_to_end(s.id)


def _invalidate(s: ReplaySession) -> None:
    s._ledger_cache = None
    s._ledger_upto = -1
    s._opt_ledger_cache = None
    s._opt_ledger_upto = -1


def _opt_vol_kwargs(cfg: ReplaySessionConfig) -> Dict[str, Any]:
    v = cfg.vol
    if v is None:
        return {}
    return {
        "risk_free_rate": v.risk_free_rate,
        "iv_window": v.iv_window,
        "iv_multiplier": v.iv_multiplier,
        "iv_override": v.iv_override,
        "iv_floor": v.iv_floor,
        "iv_cap": v.iv_cap,
        "margin_policy": v.margin_policy,
    }


def _structure_spec_from_cfg(cfg_opt) -> StructureSpec:
    if cfg_opt is None:
        return StructureSpec()
    return StructureSpec(
        structure_type=cfg_opt.structure_type,
        selection=cfg_opt.selection,
        short_delta=cfg_opt.short_delta,
        pct_otm=cfg_opt.pct_otm,
        width=cfg_opt.width,
        strikes=list(cfg_opt.strikes) if cfg_opt.strikes else None,
        dte_bars=cfg_opt.dte_bars,
        contracts=cfg_opt.contracts,
        grid_spacing=cfg_opt.grid_spacing,
    )


def _options_ledger(s: ReplaySession, upto: Optional[int] = None) -> OptionsLedgerResult:
    target = s.cursor if upto is None else upto
    target = max(0, min(target, len(s.bars) - 1))
    if s._opt_ledger_cache is not None and s._opt_ledger_upto == target:
        return s._opt_ledger_cache
    res = build_options_ledger(
        s.bars,
        s.option_orders,
        upto_index=target,
        capital=s.config.capital,
        exec_model=_exec_model(s.config),
        timing=s.config.timing,
        **_opt_vol_kwargs(s.config),
    )
    s._opt_ledger_cache = res
    s._opt_ledger_upto = target
    return res


def _recompute_high_water(s: ReplaySession) -> None:
    bar_indices = [o.bar_index + 1 for o in s.orders] + [o.bar_index + 1 for o in s.option_orders]
    s.high_water = max(bar_indices, default=s.start_index)


def _ledger(s: ReplaySession, upto: Optional[int] = None) -> LedgerResult:
    target = s.cursor if upto is None else upto
    target = max(0, min(target, len(s.bars) - 1))
    if s._ledger_cache is not None and s._ledger_upto == target:
        return s._ledger_cache
    res = build_ledger(
        s.bars,
        s.masked,
        s.orders,
        upto_index=target,
        capital=s.config.capital,
        exec_model=_exec_model(s.config),
        timing=s.config.timing,
        min_trade_shares=s.config.min_trade_shares,
        algo_target_positions=s.algo_target_positions,
        sizer_factory=_sizer_factory(s.config),
        whole_shares=s.config.whole_shares,
    )
    s._ledger_cache = res
    s._ledger_upto = target
    return res


def _require(sid: str) -> ReplaySession:
    s = _SESSIONS.get(sid)
    if s is None:
        raise SessionNotFound(f"Replay session not found: {sid}")
    if s.stale:
        raise SessionStale(
            "This session's data or strategy changed since it was saved. "
            "Start a new session."
        )
    _touch(s)
    return s


def _evict() -> None:
    now = time.time()
    for sid in [k for k, v in _SESSIONS.items() if now - v.last_touched_at > SESSION_TTL_SECONDS]:
        _drop(sid)
    while len(_SESSIONS) > MAX_SESSIONS:
        old_sid, _ = next(iter(_SESSIONS.items()))
        _drop(old_sid)


def _drop(sid: str) -> None:
    _SESSIONS.pop(sid, None)
    try:
        p = _session_path(sid)
        if os.path.exists(p):
            os.remove(p)
    except OSError:
        pass


# --- fingerprints -----------------------------------------------------------


def _data_fingerprint(filename: str, bars: List[Bar]) -> str:
    h = hashlib.sha256()
    first = bars[0].timestamp.isoformat() if bars else ""
    last = bars[-1].timestamp.isoformat() if bars else ""
    last_close = f"{bars[-1].close:.6f}" if bars else ""
    h.update(f"{filename}|{len(bars)}|{first}|{last}|{last_close}".encode())
    return h.hexdigest()


def _strategy_fingerprint(cfg: ReplaySessionConfig, resolved_params: Dict[str, Any]) -> str:
    h = hashlib.sha256()
    src = ""
    spec = STRATEGIES.get(cfg.strategy)
    if spec is not None and getattr(spec, "is_user", False):
        stem = cfg.strategy[len("user_"):] if cfg.strategy.startswith("user_") else cfg.strategy
        path = os.path.join(USER_STRATEGIES_DIR, stem + ".py")
        try:
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
        except OSError:
            src = ""
    h.update((cfg.strategy + repr(sorted(resolved_params.items())) + src).encode())
    return h.hexdigest()


# --- build the session ------------------------------------------------------


def _load_session_bars(cfg: ReplaySessionConfig) -> List[Bar]:
    path = data_service.resolve_data_path(cfg.data.file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {os.path.basename(path)}")
    return DataLoader().get_bars(path)


def _prepare(s: ReplaySession) -> None:
    """(Re)compute all derived state from bars + config. Used by create and
    rehydrate."""
    cfg = s.config
    bars = s.bars
    n = len(bars)

    strategy, resolved_params = build_strategy(cfg.strategy, cfg.params, allow_short=cfg.short)
    raw = strategy.generate_signals(bars)
    if len(raw) != n:
        raise ValueError("Strategy signals length does not match the data length.")

    warnings: List[str] = []
    # NaN -> flat, warm-up masked flat so user and algo start aligned.
    start_index = max(0, min(s.start_index, n - 2))
    masked: List[float] = []
    nan_seen = False
    for i, v in enumerate(raw):
        try:
            fv = float(v)
        except (TypeError, ValueError):
            fv = 0.0
        if fv != fv:  # NaN
            fv = 0.0
            nan_seen = True
        masked.append(0.0 if i < start_index else fv)
    if nan_seen:
        warnings.append("Strategy produced NaN signals; treated as flat.")

    if cfg.mode == "options":
        # Options account has no share-based algo target; the algo baseline is
        # computed at score time via OptionsEventDrivenEngine.
        algo_targets: List[float] = []
        algo_min_cash = 0.0
        events = derive_signal_events(bars, masked, None, start_index=start_index)
    else:
        bcfg = cfg.to_backtest_config()
        algo_portfolio, _, resolved_params2, _ = backtest_service.run_engine(bcfg, bars, signals=masked)
        algo_targets = algo_portfolio.data["target_position"].tolist()
        algo_min_cash = float(algo_portfolio.data["cash"].min())
        events = derive_signal_events(bars, masked, algo_targets, start_index=start_index)
    causality = audit_causality(strategy, bars)
    if not causality.get("causal", True):
        idx = causality.get("first_divergence_index")
        warnings.append(
            f"Strategy '{cfg.strategy}' appears to use future data "
            f"(first divergence at bar {idx}). Its signals may not be realistic."
        )

    spec = STRATEGIES.get(cfg.strategy)
    s.strategy_name = spec.name if spec else cfg.strategy
    s.resolved_params = resolved_params
    s.masked = masked
    s.algo_target_positions = algo_targets
    s.algo_min_cash = algo_min_cash
    s.signal_events = events
    s.causality = causality
    s.start_index = start_index
    s.intraday = is_intraday([b.timestamp for b in bars])
    s.tz_name = str(bars[0].timestamp.tzinfo) if bars and bars[0].timestamp.tzinfo else None
    s.warnings = warnings

    # Derive a display symbol from the config or the filename.
    sym = cfg.data.ticker
    if not sym and cfg.data.file:
        base = os.path.basename(cfg.data.file).replace(".parquet", "")
        sym = base.split("_")[0].upper()
    s.symbol = (sym or "SPY").upper()
    s.interval = cfg.data.interval or "1d"


def create_session(req: CreateReplaySessionRequest) -> Dict[str, Any]:
    cfg = req.config
    bars = _load_session_bars(cfg)
    if len(bars) > MAX_SESSION_BARS:
        raise SessionTooLarge(
            f"This dataset has {len(bars):,} bars; the replay limit is "
            f"{MAX_SESSION_BARS:,}. Use a shorter date range or a larger interval."
        )
    if len(bars) < 3:
        raise ValueError("Need at least 3 bars to replay.")

    sid = uuid.uuid4().hex[:12]
    start_index = max(0, min(cfg.warmup_bars, len(bars) - 2))
    s = ReplaySession(
        id=sid,
        created_at=time.time(),
        config=cfg,
        start_index=start_index,
        cursor=start_index,
        high_water=start_index,
        orders=[],
        option_orders=[],
        data_fingerprint="",
        strategy_fingerprint="",
        bars=bars,
    )
    _prepare(s)
    s.data_fingerprint = _data_fingerprint(cfg.data.file or "spy_daily_yfinance.parquet", bars)
    s.strategy_fingerprint = _strategy_fingerprint(cfg, s.resolved_params)

    with _LOCK:
        _SESSIONS[sid] = s
        _touch(s)
        _persist(s)
        _evict()  # after insert so the new (newest) session survives the cap
        return _create_payload(s)


# --- payloads ---------------------------------------------------------------


def _order_dict(o: ReplayOrder) -> Dict[str, Any]:
    return {
        "id": o.id,
        "bar_index": o.bar_index,
        "side": o.side,
        "qty_mode": o.qty_mode,
        "qty_value": o.qty_value,
        "note": o.note,
        "placed_at": o.placed_at,
    }


def _event_dict(e, intraday: bool) -> Dict[str, Any]:
    t = int(e.timestamp.timestamp()) if intraday else e.timestamp.strftime("%Y-%m-%d")
    return {
        "index": e.index,
        "fill_index": e.fill_index,
        "t": t,
        "from_signal": e.from_signal,
        "to_signal": e.to_signal,
        "kind": e.kind,
        "close": e.close,
        "algo_target_shares": e.algo_target_shares,
    }


def _fill_dict(f, intraday: bool) -> Dict[str, Any]:
    t = int(f.timestamp.timestamp()) if intraday else f.timestamp.strftime("%Y-%m-%d")
    return {
        "order_id": f.order_id,
        "decision_index": f.decision_index,
        "fill_index": f.fill_index,
        "t": t,
        "trade_shares": backtest_service._clean_num(f.trade_shares),
        "exec_price": backtest_service._clean_num(f.exec_price),
        "slippage": backtest_service._clean_num(f.slippage),
        "commission": backtest_service._clean_num(f.commission),
        "position_after": backtest_service._clean_num(f.position_after),
        "cash_after": backtest_service._clean_num(f.cash_after),
        "equity_after": backtest_service._clean_num(f.equity_after),
        "no_op": f.no_op,
    }


def _account_dict(s: ReplaySession, led: LedgerResult, cursor: int) -> Dict[str, Any]:
    close = s.bars[cursor].close
    position = led.final_position
    cash = led.final_cash
    # Avg cost / realized pnl from the fills up to the cursor.
    pos = 0.0
    avg = 0.0
    realized = 0.0
    total_slip = 0.0
    total_comm = 0.0
    entry_t = None
    for f in led.fills:
        total_slip += f.slippage
        total_comm += f.commission
        q = f.trade_shares
        if abs(q) < TRADE_EPS:
            continue
        if pos == 0.0:
            pos, avg, entry_t = q, f.exec_price, f.timestamp
        elif (q > 0) == (pos > 0):
            new = pos + q
            avg = (pos * avg + q * f.exec_price) / new
            pos = new
        else:
            closed = min(abs(q), abs(pos)) * (1.0 if pos > 0 else -1.0)
            realized += abs(closed) * ((f.exec_price - avg) if pos > 0 else (avg - f.exec_price))
            pos -= closed
            rem = q + closed
            if abs(pos) < TRADE_EPS:
                pos, avg, entry_t = 0.0, 0.0, None
                if abs(rem) > TRADE_EPS:
                    pos, avg, entry_t = rem, f.exec_price, f.timestamp

    unrealized = position * (close - avg) if abs(position) > TRADE_EPS else 0.0
    equity = led.final_equity
    open_trade = None
    if abs(position) > TRADE_EPS:
        open_trade = {
            "direction": "Long" if position > 0 else "Short",
            "size": abs(position),
            "avg_entry_price": avg,
            "entry_t": (int(entry_t.timestamp()) if s.intraday else entry_t.strftime("%Y-%m-%d"))
            if entry_t else None,
        }
    cn = backtest_service._clean_num
    return {
        "cash": cn(cash),
        "position": cn(position),
        "avg_price": cn(avg),
        "holdings": cn(position * close),
        "equity": cn(equity),
        "unrealized_pnl": cn(unrealized),
        "realized_pnl": cn(realized),
        "total_return": cn(equity / s.config.capital - 1.0),
        "total_slippage": cn(total_slip),
        "total_commission": cn(total_comm),
        "open_trade": open_trade,
    }


def _option_order_dict(o: OptionOrder) -> Dict[str, Any]:
    return {
        "id": o.id,
        "bar_index": o.bar_index,
        "action": o.action,
        "structure_type": o.structure_type,
        "selection": o.selection,
        "short_delta": o.short_delta,
        "pct_otm": o.pct_otm,
        "width": o.width,
        "strikes": list(o.strikes) if o.strikes else None,
        "dte_bars": o.dte_bars,
        "contracts": o.contracts,
        "grid_spacing": o.grid_spacing,
        "target_structure_id": o.target_structure_id,
        "note": o.note,
        "placed_at": o.placed_at,
    }


def _option_fill_dict(f, intraday: bool) -> Dict[str, Any]:
    t = int(f.timestamp.timestamp()) if intraday else f.timestamp.strftime("%Y-%m-%d")
    cn = backtest_service._clean_num
    return {
        "order_id": f.order_id,
        "structure_id": f.structure_id,
        "decision_index": f.decision_index,
        "fill_index": f.fill_index,
        "t": t,
        "action": f.action,
        "structure_type": f.structure_type,
        "spot": cn(f.spot),
        "net_cash": cn(f.net_cash),
        "costs": cn(f.costs),
        "cash_after": cn(f.cash_after),
        "realized_pnl": cn(f.realized_pnl),
    }


def _options_account_dict(s: ReplaySession, led: OptionsLedgerResult, cursor: int) -> Dict[str, Any]:
    cn = backtest_service._clean_num
    close = s.bars[cursor].close
    iv_series = build_iv_series(s.bars, **{k: v for k, v in _opt_vol_kwargs(s.config).items()
                                           if k != "margin_policy" and k != "risk_free_rate"})
    r = s.config.vol.risk_free_rate if s.config.vol else 0.04
    sigma = iv_series[cursor] if cursor < len(iv_series) else 0.2

    positions = []
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    max_risk = 0.0
    for st in led.open_structures:
        marked = mark_structure(st, close, cursor, r, sigma)
        for k in net:
            net[k] += marked["greeks"][k]
        ml = st.max_loss
        risk = abs(ml) if ml != float("-inf") else float("inf")
        if risk != float("inf"):
            max_risk += risk
        positions.append({
            "id": st.id,
            "structure_type": st.structure_type,
            "contracts": st.contracts,
            "open_index": st.open_index,
            "expiry_index": st.expiry_index,
            "dte_bars": max(st.expiry_index - cursor, 0),
            "value": cn(marked["value"]),
            "max_risk": cn(risk) if risk != float("inf") else None,
            "breakevens": [cn(b) for b in st.breakevens],
            "greeks": {k: cn(v) for k, v in marked["greeks"].items()},
            "legs": [{
                "kind": lm["kind"], "strike": cn(lm["strike"]), "quantity": lm["quantity"],
                "dte_bars": lm["dte_bars"], "mark": cn(lm["mark"]), "value": cn(lm["value"]),
                "delta": cn(lm["delta"]), "theta": cn(lm["theta"]), "vega": cn(lm["vega"]),
            } for lm in marked["legs"]],
        })

    equity = led.final_equity
    return {
        "mode": "options",
        "cash": cn(led.final_cash),
        "equity": cn(equity),
        "net_liq": cn(equity),
        "unrealized_pnl": cn(led.unrealized_pnl),
        "realized_pnl": cn(led.realized_pnl),
        "total_return": cn(equity / s.config.capital - 1.0),
        "max_risk": cn(max_risk),
        "buying_power_used": cn(max_risk),
        "net_delta": cn(net["delta"]),
        "net_gamma": cn(net["gamma"]),
        "net_theta": cn(net["theta"]),
        "net_vega": cn(net["vega"]),
        "positions": positions,
    }


def _next_event(s: ReplaySession, cursor: int) -> Optional[Dict[str, Any]]:
    for e in s.signal_events:
        if e.index > cursor:
            return _event_dict(e, s.intraday)
    return None


def _state_payload(s: ReplaySession) -> Dict[str, Any]:
    cursor = max(s.start_index, min(s.cursor, len(s.bars) - 1))
    if s.is_options:
        led = _options_ledger(s, upto=cursor)
        equity = led.portfolio.equity_curve
        tail = [backtest_service._clean_num(v) for v in equity.tolist()[-500:]]
        return {
            "session_id": s.id,
            "mode": "options",
            "cursor": cursor,
            "high_water": s.high_water,
            "start_index": s.start_index,
            "total_bars": len(s.bars),
            "at_end": cursor >= len(s.bars) - 1,
            "current_signal": backtest_service._clean_num(s.masked[cursor]),
            "next_signal_event": _next_event(s, cursor),
            "options_account": _options_account_dict(s, led, cursor),
            "option_orders": [_option_order_dict(o) for o in s.option_orders],
            "option_fills": [_option_fill_dict(f, s.intraday) for f in led.fills],
            "equity_tail": tail,
            "stale": s.stale,
            "warnings": s.warnings,
        }
    led = _ledger(s, upto=cursor)
    equity = led.portfolio.equity_curve
    tail = [backtest_service._clean_num(v) for v in equity.tolist()[-500:]]
    return {
        "session_id": s.id,
        "mode": "equity",
        "cursor": cursor,
        "high_water": s.high_water,
        "start_index": s.start_index,
        "total_bars": len(s.bars),
        "at_end": cursor >= len(s.bars) - 1,
        "current_signal": backtest_service._clean_num(s.masked[cursor]),
        "algo_target_shares": backtest_service._clean_num(
            s.algo_target_positions[cursor] if cursor < len(s.algo_target_positions) else 0.0
        ),
        "next_signal_event": _next_event(s, cursor),
        "account": _account_dict(s, led, cursor),
        "orders": [_order_dict(o) for o in s.orders],
        "fills": [_fill_dict(f, s.intraday) for f in led.fills],
        "equity_tail": tail,
        "stale": s.stale,
        "warnings": s.warnings,
    }


def _bars_payload(s: ReplaySession, start: int, count: int) -> Dict[str, Any]:
    total = len(s.bars)
    start = max(0, start)
    end = min(start + count, total)
    chunk = s.bars[start:end]
    idx = [b.timestamp for b in chunk]
    return {
        "start": start,
        "count": end - start,
        "total": total,
        "t": iso_index(idx, intraday=s.intraday),
        "o": [b.open for b in chunk],
        "h": [b.high for b in chunk],
        "l": [b.low for b in chunk],
        "c": [b.close for b in chunk],
        "v": [b.volume for b in chunk],
        "signal": [backtest_service._clean_num(s.masked[i]) for i in range(start, end)],
    }


def _create_payload(s: ReplaySession) -> Dict[str, Any]:
    total = len(s.bars)
    payload = {
        "session_id": s.id,
        "mode": s.config.mode,
        "total_bars": total,
        "start_index": s.start_index,
        "cursor": s.cursor,
        "instrument": {
            "symbol": s.symbol,
            "interval": s.interval,
            "intraday": s.intraday,
            "timezone": s.tz_name,
            "long_name": None,
            "exchange": None,
            "currency": None,
        },
        "strategy_name": s.strategy_name,
        "params": s.resolved_params,
        "options_config": s.config.options.model_dump() if s.config.options else None,
        "signal_events": [_event_dict(e, s.intraday) for e in s.signal_events],
        "causality": s.causality,
        "warnings": s.warnings,
        "chunk_size": DEFAULT_BAR_CHUNK,
        "bars": _bars_payload(s, 0, total) if total <= DEFAULT_BAR_CHUNK else None,
    }
    if s.is_options:
        payload["options_account"] = _options_account_dict(s, _options_ledger(s, upto=s.cursor), s.cursor)
    else:
        payload["account"] = _account_dict(s, _ledger(s, upto=s.cursor), s.cursor)
    return payload


# --- public read/mutation API ----------------------------------------------


def list_sessions() -> List[Dict[str, Any]]:
    with _LOCK:
        _evict()
        out = []
        for s in _SESSIONS.values():
            led = _ledger(s, upto=s.cursor)
            out.append({
                "session_id": s.id,
                "label": s.config.label,
                "symbol": s.symbol,
                "interval": s.interval,
                "strategy": s.config.strategy,
                "strategy_name": s.strategy_name,
                "created_at": s.created_at,
                "cursor": s.cursor,
                "total_bars": len(s.bars),
                "equity": backtest_service._clean_num(led.final_equity),
                "orders": len(s.orders),
                "stale": s.stale,
            })
        return out


def get_state(sid: str) -> Dict[str, Any]:
    with _LOCK:
        return _state_payload(_require(sid))


def get_bars(sid: str, start: int = 0, count: int = DEFAULT_BAR_CHUNK) -> Dict[str, Any]:
    if count > MAX_BAR_CHUNK:
        raise ValueError(f"count must be <= {MAX_BAR_CHUNK}.")
    with _LOCK:
        s = _require(sid)
        if start >= len(s.bars):
            raise IndexError("start is beyond the end of the data.")
        return _bars_payload(s, start, count)


def submit_order(sid: str, req: ReplayOrderRequest) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        if s.is_options:
            raise OrderRejected("This is an options session; use option orders instead.")
        bar = req.bar_index
        if bar < s.start_index:
            raise OrderRejected(f"Trading starts at bar {s.start_index}.")
        if bar < s.high_water:
            raise OrderRejected(
                f"You've already made decisions at or past bar {s.high_water}. "
                "Use rewind to change an earlier trade."
            )
        if bar + 1 >= len(s.bars):
            raise OrderRejected("No bar after this one to fill against — this is the end of the data.")
        if req.side != "close" and req.qty_mode in ("shares", "fraction") and req.qty_value <= 0:
            raise OrderRejected("Quantity must be positive.")

        oid = f"o{len(s.orders) + 1}_{bar}"
        order = ReplayOrder(
            id=oid, bar_index=bar, side=req.side, qty_mode=req.qty_mode,
            qty_value=req.qty_value, note=req.note, placed_at=_now_iso(),
        )
        candidate = list(s.orders) + [order]
        try:
            led = build_ledger(
                s.bars, s.masked, candidate,
                upto_index=bar + 1, capital=s.config.capital,
                exec_model=_exec_model(s.config), timing=s.config.timing,
                min_trade_shares=s.config.min_trade_shares,
                algo_target_positions=s.algo_target_positions,
                sizer_factory=_sizer_factory(s.config), whole_shares=s.config.whole_shares,
            )
        except ValueError as e:
            raise OrderRejected(str(e))

        if not s.config.short and led.final_position < -TRADE_EPS:
            raise OrderRejected(
                "Shorting is disabled for this session. Enable 'Allow shorting' when creating it."
            )
        if s.config.margin_policy == "cash_only" and led.final_cash < -CASH_EPS:
            raise OrderRejected(
                f"Not enough cash: this order would leave a negative balance "
                f"(${led.final_cash:,.2f}). Trade a smaller size."
            )

        s.orders.append(order)
        _recompute_high_water(s)
        s.cursor = max(s.cursor, bar + 1)
        _invalidate(s)
        _persist(s)
        state = _state_payload(s)
        fill = next((f for f in led.fills if f.order_id == oid), None)
        return {
            "accepted": True,
            "fill": _fill_dict(fill, s.intraday) if fill else None,
            "state": state,
        }


def _require_options(s: ReplaySession) -> None:
    if not s.is_options:
        raise OrderRejected("This is an equity session; use share orders instead.")


def submit_option_order(sid: str, req) -> Dict[str, Any]:
    """Open or close an option structure at ``req.bar_index`` (fills at +1)."""
    with _LOCK:
        s = _require(sid)
        _require_options(s)
        bar = req.bar_index
        if bar < s.start_index:
            raise OrderRejected(f"Trading starts at bar {s.start_index}.")
        if bar < s.high_water:
            raise OrderRejected(
                f"You've already made decisions at or past bar {s.high_water}. "
                "Use rewind to change an earlier trade."
            )
        if bar + 1 >= len(s.bars):
            raise OrderRejected("No bar after this one to fill against — this is the end of the data.")

        if req.action == "open":
            if req.structure is None:
                raise OrderRejected("An 'open' order needs a structure template.")
            spec = _structure_spec_from_cfg(req.structure)
            if spec.contracts < 1:
                raise OrderRejected("Contracts must be at least 1.")
            oid = f"opt{len(s.option_orders) + 1}_{bar}"
            order = OptionOrder(
                id=oid, bar_index=bar, action="open",
                structure_type=spec.structure_type, selection=spec.selection,
                short_delta=spec.short_delta, pct_otm=spec.pct_otm, width=spec.width,
                strikes=spec.strikes, dte_bars=spec.dte_bars, contracts=spec.contracts,
                grid_spacing=spec.grid_spacing, note=req.note, placed_at=_now_iso(),
            )
        else:  # close
            if not req.target_structure_id:
                raise OrderRejected("A 'close' order needs target_structure_id.")
            oid = f"optc{len(s.option_orders) + 1}_{bar}"
            order = OptionOrder(
                id=oid, bar_index=bar, action="close",
                target_structure_id=req.target_structure_id,
                note=req.note, placed_at=_now_iso(),
            )

        candidate = list(s.option_orders) + [order]
        try:
            led = build_options_ledger(
                s.bars, candidate, upto_index=bar + 1, capital=s.config.capital,
                exec_model=_exec_model(s.config), timing=s.config.timing,
                **_opt_vol_kwargs(s.config),
            )
        except ValueError as e:
            raise OrderRejected(str(e))

        # Buying-power / defined-risk enforcement on open.
        if req.action == "open":
            policy = s.config.vol.margin_policy if s.config.vol else "defined_risk"
            new_struct = next((st for st in led.open_structures if st.id == order.id), None)
            if new_struct is not None:
                ml = new_struct.max_loss
                if ml == float("-inf") and policy != "reg_t":
                    raise OrderRejected(
                        "This is an undefined-risk (naked short) structure. Enable Reg-T "
                        "margin, or trade a defined-risk spread instead."
                    )
            if led.max_risk > s.config.capital + CASH_EPS and policy == "defined_risk":
                raise OrderRejected(
                    f"Not enough buying power: this position risks "
                    f"${led.max_risk:,.0f} vs ${s.config.capital:,.0f} capital."
                )

        s.option_orders.append(order)
        _recompute_high_water(s)
        s.cursor = max(s.cursor, bar + 1)
        _invalidate(s)
        _persist(s)
        state = _state_payload(s)
        fill = next((f for f in led.fills if f.order_id == oid), None)
        return {
            "accepted": True,
            "fill": _option_fill_dict(fill, s.intraday) if fill else None,
            "state": state,
        }


def preview_option(sid: str, req) -> Dict[str, Any]:
    """Dry-run: price a structure template against a session bar (no order)."""
    with _LOCK:
        s = _require(sid)
        _require_options(s)
        bar = max(s.start_index, min(req.bar_index, len(s.bars) - 1))
        spec = _structure_spec_from_cfg(req.structure)
        from options.structures import build_structure
        r = s.config.vol.risk_free_rate if s.config.vol else 0.04
        iv_series = build_iv_series(s.bars, **{k: v for k, v in _opt_vol_kwargs(s.config).items()
                                               if k not in ("margin_policy", "risk_free_rate")})
        spot = s.bars[bar].close
        sigma = iv_series[bar] if bar < len(iv_series) else 0.2
        structure = build_structure(spec, S=spot, sigma=sigma, r=r, open_index=bar, structure_id="preview")
        marked = mark_structure(structure, spot, bar, r, sigma)
        cn = backtest_service._clean_num
        ml = structure.max_loss
        mp = structure.max_profit
        # payoff curve across a spot range
        lo = spot * 0.8
        hi = spot * 1.2
        payoff = []
        for i in range(41):
            sp = lo + (hi - lo) * i / 40.0
            payoff.append({"s": cn(sp), "pnl": cn(structure._payoff_at(sp))})
        return {
            "structure": spec.structure_type,
            "spot": cn(spot),
            "iv": cn(sigma),
            "dte": spec.dte_bars,
            "net_price": cn(structure.net_premium_per_share),
            "net_is_credit": structure.net_premium_per_share < 0,
            "contracts": structure.contracts,
            "multiplier": 100,
            "max_profit": cn(mp) if mp != float("inf") else None,
            "max_loss": cn(ml) if ml != float("-inf") else None,
            "breakevens": [cn(b) for b in structure.breakevens],
            "greeks": {k: cn(v) for k, v in marked["greeks"].items()},
            "legs": [{
                "kind": lm["kind"], "action": "buy" if lm["quantity"] > 0 else "sell",
                "strike": cn(lm["strike"]), "quantity": lm["quantity"], "dte": lm["dte_bars"],
                "mark": cn(lm["mark"]), "iv": cn(sigma),
                "greeks": {"delta": cn(lm["delta"]), "gamma": cn(lm["gamma"]) if "gamma" in lm else 0.0,
                           "theta": cn(lm["theta"]), "vega": cn(lm["vega"])},
            } for lm in marked["legs"]],
            "payoff": payoff,
            "warnings": [],
        }


def undo_last_order(sid: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        if s.is_options:
            if not s.option_orders:
                raise OrderRejected("No orders to undo.")
            s.option_orders.pop()
            _recompute_high_water(s)
            s.cursor = min(s.cursor, len(s.bars) - 1)
            _invalidate(s)
            _persist(s)
            return _state_payload(s)
        if not s.orders:
            raise OrderRejected("No orders to undo.")
        s.orders.pop()
        _recompute_high_water(s)
        s.cursor = min(s.cursor, len(s.bars) - 1)
        _invalidate(s)
        _persist(s)
        return _state_payload(s)


def delete_order(sid: str, order_id: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        before = len(s.orders)
        s.orders = [o for o in s.orders if o.id != order_id]
        if len(s.orders) == before:
            raise SessionNotFound(f"Order not found: {order_id}")
        _recompute_high_water(s)
        _invalidate(s)
        _persist(s)
        return _state_payload(s)


def seek(sid: str, to_index: int) -> Dict[str, Any]:
    """Move the view cursor (for review / resume). Does not change decisions."""
    with _LOCK:
        s = _require(sid)
        s.cursor = max(s.start_index, min(to_index, len(s.bars) - 1))
        _invalidate(s)
        _persist(s)
        return _state_payload(s)


def rewind(sid: str, to_index: int, confirm_discard_orders: bool = False) -> Dict[str, Any]:
    """Destructive: discard every order decided at or after ``to_index`` so the
    user can re-try a decision."""
    with _LOCK:
        s = _require(sid)
        if to_index < s.start_index:
            raise OrderRejected(f"Cannot rewind before the start bar ({s.start_index}).")
        dropped = ([o for o in s.orders if o.bar_index >= to_index]
                   + [o for o in s.option_orders if o.bar_index >= to_index])
        if dropped and not confirm_discard_orders:
            raise OrderRejected(
                f"Rewinding to bar {to_index} would discard {len(dropped)} order(s). "
                "Confirm to proceed."
            )
        s.orders = [o for o in s.orders if o.bar_index < to_index]
        s.option_orders = [o for o in s.option_orders if o.bar_index < to_index]
        _recompute_high_water(s)
        s.cursor = max(s.start_index, min(to_index, len(s.bars) - 1))
        _invalidate(s)
        _persist(s)
        return _state_payload(s)


def reset(sid: str) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        s.orders = []
        s.option_orders = []
        s.high_water = s.start_index
        s.cursor = s.start_index
        _invalidate(s)
        _persist(s)
        return _state_payload(s)


def delete_session(sid: str) -> None:
    with _LOCK:
        if sid not in _SESSIONS and not os.path.exists(_session_path(sid)):
            raise SessionNotFound(f"Replay session not found: {sid}")
        _drop(sid)


# --- scoring & journal ------------------------------------------------------


def _track_from_df(df, timing: str, intraday: bool, capital: float) -> Dict[str, Any]:
    trades = extract_trades(df, timing)
    summary = PerformanceMetrics.get_advanced_summary(df, trades)
    equity = df["equity"]
    close = df["close"]
    benchmark = PerformanceMetrics.get_benchmark_equity(close, capital)
    cn = backtest_service._clean_num
    return {
        "summary": backtest_service._summary_payload(summary),
        "series": {
            "dates": iso_index(equity.index, intraday=intraday),
            "equity": [cn(v) for v in equity.tolist()],
            "benchmark": [cn(v) for v in benchmark.tolist()],
        },
        "trades": backtest_service._trades_payload(trades),
    }


def _options_track_from_led(led: OptionsLedgerResult, intraday: bool, capital: float) -> Dict[str, Any]:
    """A scoreboard track for an options ledger result (user or algo)."""
    df = led.portfolio.data
    trades = reconstruct_option_trades(led.closed_trades)
    summary = PerformanceMetrics.get_advanced_summary(df, trades)
    equity = df["equity"]
    close = df["close"]
    benchmark = PerformanceMetrics.get_benchmark_equity(close, capital)
    cn = backtest_service._clean_num
    return {
        "summary": backtest_service._summary_payload(summary),
        "series": {
            "dates": iso_index(equity.index, intraday=intraday),
            "equity": [cn(v) for v in equity.tolist()],
            "benchmark": [cn(v) for v in benchmark.tolist()],
        },
        "option_trades": backtest_service._option_trades_payload(trades),
        "realized_pnl": cn(led.realized_pnl),
        "unrealized_pnl": cn(led.unrealized_pnl),
    }


def _score_options(s: ReplaySession, cursor: int) -> Dict[str, Any]:
    cap = s.config.capital
    intraday = s.intraday

    # USER — the options ledger up to the cursor.
    user_led = _options_ledger(s, upto=cursor)
    user = _options_track_from_led(user_led, intraday, cap)

    # ALGO — the configured strategy traded as the same structure template.
    from backtest.execution import ExecutionModel as _EM
    strategy, _ = build_strategy(s.config.strategy, s.config.params, allow_short=s.config.short)
    engine = OptionsEventDrivenEngine(
        strategy=strategy,
        structure=_structure_spec_from_cfg(s.config.options),
        execution_model=_exec_model(s.config),
        initial_capital=cap,
        execution_timing=s.config.timing,
        **_opt_vol_kwargs(s.config),
    )
    algo_led = engine.run(s.bars[: cursor + 1], signals=s.masked[: cursor + 1])
    algo = _options_track_from_led(algo_led, intraday, cap)

    # BUY & HOLD — underlying shares (different instrument, labelled as such).
    bh_order = [ReplayOrder(id="bh", bar_index=s.start_index, side="buy",
                            qty_mode="fraction", qty_value=1.0)]
    bh_led = build_ledger(
        s.bars, s.masked, bh_order, upto_index=cursor, capital=cap,
        exec_model=_exec_model(s.config), timing=s.config.timing,
        min_trade_shares=s.config.min_trade_shares,
    )
    buy_hold = _track_from_df(bh_led.portfolio.data, s.config.timing, intraday, cap)

    def _delta(a, b):
        return {k: backtest_service._clean_num(a["summary"].get(k, 0) - b["summary"].get(k, 0))
                for k in ("Total Return", "Sharpe Ratio", "Max Drawdown")}

    return {
        "cursor": cursor,
        "mode": "options",
        "bars_elapsed": cursor - s.start_index,
        "start_index": s.start_index,
        "user": user,
        "algo": algo,
        "buy_hold": buy_hold,
        "delta": {"vs_algo": _delta(user, algo), "vs_buy_hold": _delta(user, buy_hold)},
        "behaviour": _behaviour(s, cursor),
        "fairness": {
            "note": "Buy & Hold is the underlying stock, a different instrument than the "
                    "options positions — compare directionally, not one-for-one.",
        },
        "warnings": s.warnings + [
            "Options are priced with a Black-Scholes synthetic model (realized-vol IV, "
            "no vol risk premium), so short-premium P&L is understated vs. a real market."
        ],
    }


def _behaviour(s: ReplaySession, cursor: int) -> Dict[str, Any]:
    order_bars = {o.bar_index for o in s.orders}
    shown = followed = faded = ignored = 0
    for e in s.signal_events:
        if e.fill_index > cursor:
            continue
        shown += 1
        if e.index in order_bars:
            # did the user trade in the signal's direction?
            user_orders = [o for o in s.orders if o.bar_index == e.index]
            wants_long = e.to_signal > 0
            wants_short = e.to_signal < 0
            wants_flat = abs(e.to_signal) <= 1e-9
            agreed = False
            for o in user_orders:
                if wants_long and o.side == "buy":
                    agreed = True
                elif wants_short and o.side == "sell":
                    agreed = True
                elif wants_flat and o.side == "close":
                    agreed = True
            followed += 1 if agreed else 0
            faded += 0 if agreed else 1
        else:
            ignored += 1
    event_bars = {e.index for e in s.signal_events}
    unprompted = len([o for o in s.orders if o.bar_index not in event_bars])
    return {
        "signals_shown": shown,
        "signals_followed": followed,
        "signals_faded": faded,
        "signals_ignored": ignored,
        "unprompted_orders": unprompted,
        "follow_rate": (followed / shown) if shown else 0.0,
    }


def score(sid: str, upto: Optional[int] = None) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        cursor = s.cursor if upto is None else max(s.start_index, min(upto, len(s.bars) - 1))
        if s.is_options:
            return _score_options(s, cursor)
        cap = s.config.capital
        timing = s.config.timing
        intraday = s.intraday

        # USER
        user_led = _ledger(s, upto=cursor)
        user = _track_from_df(user_led.portfolio.data, timing, intraday, cap)

        # ALGO — rerun the engine on the same prefix.
        bcfg = s.config.to_backtest_config()
        algo_portfolio, algo_trades, _, _ = backtest_service.run_engine(
            bcfg, s.bars[: cursor + 1], signals=s.masked[: cursor + 1]
        )
        algo = _track_from_df(algo_portfolio.data, timing, intraday, cap)

        # BUY & HOLD — a single full-size order through the same cost model.
        bh_order = [ReplayOrder(id="bh", bar_index=s.start_index, side="buy",
                                qty_mode="fraction", qty_value=1.0)]
        bh_led = build_ledger(
            s.bars, s.masked, bh_order, upto_index=cursor, capital=cap,
            exec_model=_exec_model(s.config), timing=timing,
            min_trade_shares=s.config.min_trade_shares,
        )
        buy_hold = _track_from_df(bh_led.portfolio.data, timing, intraday, cap)

        def _delta(a, b):
            return {k: backtest_service._clean_num(a["summary"].get(k, 0) - b["summary"].get(k, 0))
                    for k in ("Total Return", "Sharpe Ratio", "Max Drawdown")}

        fairness = {
            "algo_min_cash": backtest_service._clean_num(algo_portfolio.data["cash"].min()),
            "algo_used_leverage": bool(algo_portfolio.data["cash"].min() < -CASH_EPS),
            "user_margin_policy": s.config.margin_policy,
            "note": None,
        }
        if fairness["algo_used_leverage"] and s.config.margin_policy == "cash_only":
            fairness["note"] = (
                f"The algorithm's baseline borrowed up to "
                f"${abs(fairness['algo_min_cash']):,.0f} at its peak. Your run was "
                "cash-constrained, so the comparison is not strictly like-for-like."
            )

        return {
            "cursor": cursor,
            "bars_elapsed": cursor - s.start_index,
            "start_index": s.start_index,
            "user": user,
            "algo": algo,
            "buy_hold": buy_hold,
            "delta": {"vs_algo": _delta(user, algo), "vs_buy_hold": _delta(user, buy_hold)},
            "behaviour": _behaviour(s, cursor),
            "fairness": fairness,
            "warnings": s.warnings,
        }


def journal(sid: str, upto: Optional[int] = None) -> Dict[str, Any]:
    with _LOCK:
        s = _require(sid)
        cursor = s.cursor if upto is None else max(s.start_index, min(upto, len(s.bars) - 1))
        led = _ledger(s, upto=cursor)
        fills_by_decision: Dict[int, Any] = {f.decision_index: f for f in led.fills}
        events_by_index = {e.index: e for e in s.signal_events}
        orders_by_bar: Dict[int, List[ReplayOrder]] = {}
        for o in s.orders:
            orders_by_bar.setdefault(o.bar_index, []).append(o)

        decision_bars = sorted(
            {e.index for e in s.signal_events if e.fill_index <= cursor}
            | {b for b in orders_by_bar if b <= cursor}
        )
        entries = []
        for b in decision_bars:
            e = events_by_index.get(b)
            orders = orders_by_bar.get(b, [])
            fill = fills_by_decision.get(b)
            if orders and e:
                verdict = "followed" if any(
                    (e.to_signal > 0 and o.side == "buy")
                    or (e.to_signal < 0 and o.side == "sell")
                    or (abs(e.to_signal) <= 1e-9 and o.side == "close")
                    for o in orders
                ) else "faded"
            elif orders and not e:
                verdict = "unprompted"
            else:
                verdict = "ignored"
            t = (int(s.bars[b].timestamp.timestamp()) if s.intraday
                 else s.bars[b].timestamp.strftime("%Y-%m-%d"))
            cn = backtest_service._clean_num
            entries.append({
                "bar_index": b,
                "t": t,
                "close": cn(s.bars[b].close),
                "signal_from": e.from_signal if e else None,
                "signal_to": e.to_signal if e else None,
                "event_kind": e.kind if e else None,
                "algo_target_shares": cn(e.algo_target_shares) if e else None,
                "user_action": ([{
                    "side": o.side, "qty_mode": o.qty_mode, "qty_value": o.qty_value, "note": o.note,
                } for o in orders] or None),
                "fill": _fill_dict(fill, s.intraday) if fill else None,
                "verdict": verdict,
            })
        return {"entries": entries}


# --- persistence ------------------------------------------------------------


def _session_path(sid: str) -> str:
    return os.path.join(paths.SESSIONS_DIR, f"{sid}.json")


def _persist(s: ReplaySession) -> None:
    data = {
        "version": PERSIST_VERSION,
        "id": s.id,
        "created_at": s.created_at,
        "config": s.config.model_dump(),
        "start_index": s.start_index,
        "cursor": s.cursor,
        "high_water": s.high_water,
        "orders": [_order_dict(o) for o in s.orders],
        "option_orders": [_option_order_dict(o) for o in s.option_orders],
        "data_fingerprint": s.data_fingerprint,
        "strategy_fingerprint": s.strategy_fingerprint,
    }
    try:
        os.makedirs(paths.SESSIONS_DIR, exist_ok=True)
        tmp = _session_path(s.id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, _session_path(s.id))
    except OSError:
        pass  # persistence is best-effort; never break a live session


def rehydrate_all() -> List[str]:
    """Reload persisted sessions once at import. Recomputes bars/signals/baseline
    and marks a session stale if its data or strategy changed. Never raises."""
    recovered: List[str] = []
    if not os.path.isdir(paths.SESSIONS_DIR):
        return recovered
    for fname in sorted(os.listdir(paths.SESSIONS_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(paths.SESSIONS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            cfg = ReplaySessionConfig(**data["config"])
            bars = _load_session_bars(cfg)
            s = ReplaySession(
                id=data["id"],
                created_at=data.get("created_at", time.time()),
                config=cfg,
                start_index=data["start_index"],
                cursor=data["cursor"],
                high_water=data["high_water"],
                orders=[ReplayOrder(**o) for o in data.get("orders", [])],
                option_orders=[OptionOrder(**o) for o in data.get("option_orders", [])],
                data_fingerprint=data.get("data_fingerprint", ""),
                strategy_fingerprint=data.get("strategy_fingerprint", ""),
                bars=bars,
            )
            _prepare(s)
            new_data_fp = _data_fingerprint(cfg.data.file or "spy_daily_yfinance.parquet", bars)
            new_strat_fp = _strategy_fingerprint(cfg, s.resolved_params)
            if new_data_fp != s.data_fingerprint or new_strat_fp != s.strategy_fingerprint:
                s.stale = True
                s.warnings.append("Underlying data or strategy changed since this session was saved.")
            s.last_touched_at = time.time()
            _SESSIONS[s.id] = s
            recovered.append(s.id)
        except Exception as e:  # noqa: BLE001 - never crash startup
            print(f"[replay] Dropping unrecoverable session {fname}: {e}")
            try:
                os.remove(path)
            except OSError:
                pass
    # honour the cap even across a restart
    while len(_SESSIONS) > MAX_SESSIONS:
        old_sid, _ = next(iter(_SESSIONS.items()))
        _drop(old_sid)
    return recovered


# Rehydrate at import (main.py imports this module at startup).
try:
    rehydrate_all()
except Exception as _e:  # noqa: BLE001
    print(f"[replay] rehydrate_all failed: {_e}")

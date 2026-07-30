"""The event-driven portfolio engine — one trading date at a time.

Daily sequence (order matters, prevents same-day close->open leakage):
  1. pending exits fill at today's open
  2. protective stops (gap-aware) using today's OHLC
  3. pending entries fill at today's open (ranked, capped, sector-limited, sized)
  4. mark to market at today's close (+ reconcile)
  5. schedule new exits (close < SMA(exit_ma))
  6. schedule new entries (today's signals) for the next open
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.execution import commission, entry_fill, exit_fill, stop_exit_price
from portfolio_backtest.portfolio import Portfolio, Position
from portfolio_backtest.ranking import rank_candidates
from portfolio_backtest.risk import size_position
from portfolio_backtest.sectors import sector_of
from portfolio_backtest.signals import build_signals


@dataclass
class PortfolioBacktestResult:
    daily: pd.DataFrame                    # equity/cash/exposure/... per date
    trades: List[Dict[str, Any]]           # closed trades
    open_positions: List[Dict[str, Any]]
    benchmark: pd.Series                   # SPY buy & hold, rebased to capital
    warnings: List[str] = field(default_factory=list)


def _col(frame: pd.DataFrame, axis: pd.Index, name: str, ffill: bool = False) -> np.ndarray:
    s = frame[name].reindex(axis)
    if ffill:
        s = s.ffill()
    return s.to_numpy()


def run_portfolio_backtest(
    cfg: PortfolioBacktestConfig,
    ohlcv_by_symbol: Dict[str, pd.DataFrame],
    spy: pd.DataFrame,
) -> PortfolioBacktestResult:
    warnings: List[str] = []
    _, sig_by_symbol = build_signals(cfg, ohlcv_by_symbol, spy)

    axis = spy.index
    n = len(axis)
    if n < cfg.trend_slow_ma + 5:
        raise ValueError("Not enough benchmark history for the configured filters.")

    # Per-symbol arrays aligned to the axis; prices ffilled so marking never NaNs.
    A: Dict[str, Dict[str, np.ndarray]] = {}
    for sym, f in sig_by_symbol.items():
        A[sym] = {
            "open": _col(f, axis, "open", ffill=True),
            "high": _col(f, axis, "high", ffill=True),
            "low": _col(f, axis, "low", ffill=True),
            "close": _col(f, axis, "close", ffill=True),
            "raw_close": _col(f, axis, "close"),      # NaN where truly absent
            "atr": _col(f, axis, "atr"),
            "sma_exit": _col(f, axis, "sma_exit"),
            "signal": _col(f, axis, "signal"),
            "rs": _col(f, axis, "rs"),
            "volume_ratio": _col(f, axis, "volume_ratio"),
            "breakout_pct": _col(f, axis, "breakout_pct"),
            "dollar_vol": _col(f, axis, "dollar_vol"),
        }
    symbols = list(A.keys())

    pf = Portfolio(cfg.initial_capital)
    pending_entries: List[Dict[str, Any]] = []
    pending_exits: set = set()

    def available(sym: str, i: int) -> bool:
        return not np.isnan(A[sym]["raw_close"][i])

    def price_map(i: int, field_name: str) -> Dict[str, float]:
        return {t: A[t][field_name][i] for t in pf.positions if not np.isnan(A[t][field_name][i])}

    dates: List[Any] = []
    rows: List[Dict[str, Any]] = []
    peak_equity = cfg.initial_capital

    for i in range(n):
        date = axis[i]

        # 1) pending exits at today's open
        for t in list(pending_exits):
            if t in pf.positions and available(t, i):
                px = exit_fill(A[t]["open"][i], cfg)
                sh = pf.positions[t].shares
                comm = commission(sh, cfg)
                slip = sh * (A[t]["open"][i] - px)
                pf.close(t, date, px, comm, "sma_exit", pf.positions[t].__dict__.get("signal_date"), slip)
            pending_exits.discard(t)

        # 2) protective stops (gap-aware)
        for t in list(pf.positions.keys()):
            pos = pf.positions[t]
            sp = stop_exit_price(A[t]["open"][i], A[t]["low"][i], pos.current_stop, cfg)
            if sp is not None:
                sh = pos.shares
                comm = commission(sh, cfg)
                raw = pos.current_stop if A[t]["open"][i] >= pos.current_stop else A[t]["open"][i]
                slip = sh * (raw - sp)
                pf.close(t, date, sp, comm, "stop", getattr(pos, "signal_date", None), slip)

        # 3) pending entries at today's open (ranked, capped, sector-limited, sized)
        if pending_entries:
            ranked = rank_candidates(pending_entries, cfg)
            eq_ref = pf.equity(price_map(i, "open")) if pf.positions else pf.cash
            for c in ranked:
                if len(pf.positions) >= cfg.max_positions:
                    break
                t = c["ticker"]
                if t in pf.positions or not available(t, i):
                    continue
                if pf.sector_count(c["sector"]) >= cfg.max_per_sector:
                    continue
                open_today = A[t]["open"][i]
                if cfg.gap_reject_pct is not None and open_today > c["signal_close"] * (1 + cfg.gap_reject_pct):
                    continue
                fill = entry_fill(open_today, cfg)
                stop = c["proposed_stop"]
                if fill - stop <= 0:
                    continue
                shares = size_position(eq_ref, pf.cash, fill, stop, cfg)
                comm = commission(shares, cfg)
                while shares > 0 and shares * fill + comm > pf.cash:
                    shares -= 1
                    comm = commission(shares, cfg)
                if shares <= 0:
                    continue
                slip = shares * (fill - open_today)
                pos = Position(
                    ticker=t, sector=c["sector"], entry_date=date, entry_price=fill, shares=shares,
                    initial_stop=stop, current_stop=stop, score=c.get("score", 0.0), entry_commission=comm,
                )
                setattr(pos, "signal_date", c["signal_date"])
                pf.open(pos)
            pending_entries = []

        # 4) mark to market at close (+ reconcile)
        prices_close = price_map(i, "close")
        for t, pos in pf.positions.items():
            pos.update_excursion(A[t]["high"][i], A[t]["low"][i])
        equity = pf.equity(prices_close)
        pf.reconcile(prices_close)
        peak_equity = max(peak_equity, equity)
        gross_exposure = pf.holdings_value(prices_close)
        rows.append({
            "cash": pf.cash, "market_value": gross_exposure, "equity": equity,
            "open_positions": len(pf.positions),
            "gross_exposure": gross_exposure / equity if equity else 0.0,
            "realized": pf.realized_gross - pf.cum_costs, "unrealized": pf.unrealized_gross(prices_close),
            "drawdown": (equity - peak_equity) / peak_equity if peak_equity else 0.0,
        })
        dates.append(date)

        # 5) schedule new exits
        for t, pos in pf.positions.items():
            sx = A[t]["sma_exit"][i]
            if not np.isnan(sx) and A[t]["close"][i] < sx:
                pending_exits.add(t)

        # 6) schedule new entries for next open
        if i < n - 1:
            for sym in symbols:
                if A[sym]["signal"][i] and not np.isnan(A[sym]["atr"][i]) and A[sym]["atr"][i] > 0:
                    sc = A[sym]["close"][i]
                    pending_entries.append({
                        "ticker": sym, "sector": sector_of(sym), "signal_date": date,
                        "signal_close": sc, "atr": A[sym]["atr"][i],
                        "proposed_stop": sc - cfg.stop_atr_mult * A[sym]["atr"][i],
                        "rs": float(A[sym]["rs"][i]) if not np.isnan(A[sym]["rs"][i]) else 0.0,
                        "volume_ratio": float(A[sym]["volume_ratio"][i]) if not np.isnan(A[sym]["volume_ratio"][i]) else 0.0,
                        "breakout_pct": float(A[sym]["breakout_pct"][i]) if not np.isnan(A[sym]["breakout_pct"][i]) else 0.0,
                        "dollar_vol": float(A[sym]["dollar_vol"][i]) if not np.isnan(A[sym]["dollar_vol"][i]) else 0.0,
                    })

    daily = pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="date"))
    benchmark = _benchmark(spy, cfg.initial_capital)

    trades = [_trade_dict(t) for t in pf.closed]
    open_positions = [{
        "ticker": p.ticker, "sector": p.sector, "shares": p.shares,
        "entry_price": p.entry_price, "entry_date": p.entry_date.strftime("%Y-%m-%d"),
        "current_stop": p.current_stop,
    } for p in pf.positions.values()]
    return PortfolioBacktestResult(daily=daily, trades=trades, open_positions=open_positions,
                                   benchmark=benchmark, warnings=warnings)


def _benchmark(spy: pd.DataFrame, capital: float) -> pd.Series:
    ret = spy["close"].pct_change().fillna(0.0)
    return capital * (1.0 + ret).cumprod()


def _trade_dict(t) -> Dict[str, Any]:
    return {
        "ticker": t.ticker, "sector": t.sector,
        "signal_date": t.signal_date.strftime("%Y-%m-%d") if t.signal_date is not None else None,
        "entry_date": t.entry_date.strftime("%Y-%m-%d"), "entry_price": t.entry_price,
        "exit_date": t.exit_date.strftime("%Y-%m-%d"), "exit_price": t.exit_price,
        "shares": t.shares, "initial_stop": t.initial_stop, "exit_reason": t.exit_reason,
        "gross_pnl": t.gross_pnl, "commission": t.commission, "net_pnl": t.net_pnl,
        "return_pct": t.return_pct, "r_multiple": t.r_multiple, "holding_days": t.holding_days,
        "mfe": t.mfe, "mae": t.mae,
    }

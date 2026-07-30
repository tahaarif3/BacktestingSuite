"""Relative-Strength Breakout — a best-effort automation of a discretionary
intraday options-breakout playbook.

The discretionary rules (from the source): find a stock that is STRONG while SPY
is WEAK (relative strength), that was more bullish than SPY in pre-market, and
that breaks a prior "psychological" resistance level on a momentum candle at the
open. This encodes each fuzzy rule with a concrete, causal computation on OHLCV
bars.

Fidelity (be honest with yourself):
  * FAITHFUL: SPY-weak/stock-strong via 90-MA + slope; relative strength;
    momentum candle (range vs ATR / volume spike); long-only bullish bias.
  * PROXY: "more bullish in pre-market than SPY" -> the overnight gap
    (today's open vs yesterday's close), because yfinance data here has no
    pre-market bars. "First 5-min candle after the open" -> a session-open
    window (a no-op on daily data). "Level rejected multiple times" ->
    a rolling N-bar high (no multi-touch count).

Signals are long-only (1.0 long / 0.0 flat). SPY is loaded from the suite's data
directory and aligned to the stock by timestamp; if it can't be aligned the
strategy degrades to all-flat rather than guessing.
"""

from __future__ import annotations

import os
from typing import List

import numpy as np
import pandas as pd

from domain.models import Bar
from strat.base import BaseStrategy


class RSBreakoutStrategy(BaseStrategy):
    def __init__(
        self,
        trend_ma: int = 90,
        slope_lookback: int = 10,
        rs_lookback: int = 20,
        rs_edge: float = 0.0,
        gap_edge: float = 0.0,
        breakout_window: int = 20,
        range_mult: float = 1.2,
        atr_window: int = 14,
        vol_mult: float = 1.5,
        vol_window: int = 20,
        entry_window_bars: int = 3,
        stop_pct: float = 0.02,
        take_pct: float = 0.06,
        max_hold_bars: int = 0,
        spy_file: str = "spy_daily_yfinance.parquet",
        long_only: bool = True,
    ):
        self.trend_ma = int(trend_ma)
        self.slope_lookback = int(slope_lookback)
        self.rs_lookback = int(rs_lookback)
        self.rs_edge = float(rs_edge)
        self.gap_edge = float(gap_edge)
        self.breakout_window = int(breakout_window)
        self.range_mult = float(range_mult)
        self.atr_window = int(atr_window)
        self.vol_mult = float(vol_mult)
        self.vol_window = int(vol_window)
        self.entry_window_bars = int(entry_window_bars)
        self.stop_pct = float(stop_pct)
        self.take_pct = float(take_pct)
        self.max_hold_bars = int(max_hold_bars)
        self.spy_file = spy_file
        self.long_only = True  # this setup is bullish-only by construction

    # --- SPY reference loading ------------------------------------------------

    def _resolve_spy_path(self) -> str | None:
        """Best-effort path to the SPY parquet, without importing the desktop layer
        at module scope. Prefers the app's writable DATA_DIR when available."""
        candidates: List[str] = []
        try:  # packaged app / running backend
            from desktop.backend.paths import DATA_DIR  # type: ignore
            candidates.append(os.path.join(DATA_DIR, os.path.basename(self.spy_file)))
        except Exception:
            pass
        here = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here, "..", "data", os.path.basename(self.spy_file)))
        candidates.append(os.path.join(os.getcwd(), "data", os.path.basename(self.spy_file)))
        for c in candidates:
            if c and os.path.exists(c):
                return os.path.abspath(c)
        return None

    def _load_spy(self, index: pd.Index) -> pd.DataFrame | None:
        """Return a DataFrame of SPY open/close aligned to ``index`` (the stock's
        timestamps), or None if it can't be aligned to enough bars."""
        path = self._resolve_spy_path()
        if not path:
            return None
        try:
            from data.dataloader import DataLoader
            spy_bars = DataLoader().get_bars(path)
        except Exception:
            return None
        if not spy_bars:
            return None
        spy = pd.DataFrame(
            {"spy_open": [b.open for b in spy_bars], "spy_close": [b.close for b in spy_bars]},
            index=pd.Index([b.timestamp for b in spy_bars]),
        )
        spy = spy[~spy.index.duplicated(keep="last")].sort_index()

        # 1) exact timestamp alignment
        aligned = spy.reindex(index)
        coverage = aligned["spy_close"].notna().mean()
        if coverage < 0.5:
            # 2) fall back to date-based alignment (daily bars at different times)
            by_date = spy.copy()
            by_date.index = pd.DatetimeIndex(by_date.index).normalize()
            by_date = by_date[~by_date.index.duplicated(keep="last")]
            key = pd.DatetimeIndex(index).normalize()
            aligned = by_date.reindex(key)
            aligned.index = index
            coverage = aligned["spy_close"].notna().mean()
        if coverage < 0.5:
            return None
        return aligned.ffill().bfill()

    # --- signal generation ----------------------------------------------------

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        return self._compute(bars)["signal"]

    def diagnostics(self, bars: List[Bar]) -> dict:
        """Per-bar internals behind the signal — regime legs, relative strength,
        breakout/momentum flags — so a scanner can rank names and the UI can
        explain *why* a signal fired. Single source of truth with the signal."""
        return self._compute(bars)

    def _compute(self, bars: List[Bar]) -> dict:
        n = len(bars)
        if n == 0:
            return {"signal": [], "has_reference": False, "regime_armed": [], "rs": [],
                    "stock_up": [], "spy_down": [], "broke_out": [], "momentum_ok": [], "enter": []}
        idx = pd.Index([b.timestamp for b in bars])
        C = pd.Series([b.close for b in bars], index=idx, dtype=float)
        O = pd.Series([b.open for b in bars], index=idx, dtype=float)
        H = pd.Series([b.high for b in bars], index=idx, dtype=float)
        L = pd.Series([b.low for b in bars], index=idx, dtype=float)
        V = pd.Series([b.volume for b in bars], index=idx, dtype=float)

        spy = self._load_spy(idx)
        if spy is None:
            # Can't judge relative strength -> stay flat, honestly.
            zeros = [0.0] * n
            falses = [False] * n
            return {"signal": zeros, "has_reference": False, "regime_armed": falses,
                    "rs": zeros, "stock_up": falses, "spy_down": falses,
                    "broke_out": falses, "momentum_ok": falses, "enter": falses}
        Sc = spy["spy_close"].astype(float)
        So = spy["spy_open"].astype(float)

        # 1) regime: stock above rising MA, SPY below falling MA
        stock_ma = C.rolling(self.trend_ma).mean()
        spy_ma = Sc.rolling(self.trend_ma).mean()
        stock_up = (C > stock_ma) & (stock_ma - stock_ma.shift(self.slope_lookback) > 0)
        spy_down = (Sc < spy_ma) & (spy_ma - spy_ma.shift(self.slope_lookback) < 0)

        # 2) relative strength over the lookback
        rs = (C / C.shift(self.rs_lookback) - 1.0) - (Sc / Sc.shift(self.rs_lookback) - 1.0)
        rs_ok = rs > self.rs_edge

        # 3) premarket proxy: overnight gap of stock beats SPY's
        gap_stock = O / C.shift(1) - 1.0
        gap_spy = So / Sc.shift(1) - 1.0
        premarket_ok = (gap_stock - gap_spy) > self.gap_edge

        # 4) level breakout + momentum candle
        level = H.rolling(self.breakout_window).max().shift(1)
        broke_out = C > level
        prev_close = C.shift(1)
        tr = pd.concat([H - L, (H - prev_close).abs(), (L - prev_close).abs()], axis=1).max(axis=1)
        atr = tr.rolling(self.atr_window).mean()
        big_candle = (H - L) > self.range_mult * atr
        vol_spike = V > self.vol_mult * V.rolling(self.vol_window).mean()
        momentum_ok = (C > O) & (big_candle | vol_spike)

        # 5) session-open window (no-op on daily; first N bars after a new day)
        dates = pd.DatetimeIndex(idx).normalize()
        new_session = pd.Series(dates != np.roll(dates, 1), index=idx)
        new_session.iloc[0] = True
        bars_into_session = new_session.groupby((new_session).cumsum()).cumcount()
        in_window = bars_into_session < self.entry_window_bars

        regime = (stock_up & spy_down & rs_ok).fillna(False)
        enter = (regime & premarket_ok & broke_out & momentum_ok & in_window).fillna(False)
        enter_arr = enter.to_numpy()
        level_arr = level.to_numpy()
        close_arr = C.to_numpy()
        ma_arr = stock_ma.to_numpy()

        warm = max(self.trend_ma, self.breakout_window, self.rs_lookback + 1)
        signals = [0.0] * n
        in_pos = False
        entry_price = 0.0
        entry_level = 0.0
        bars_held = 0

        for i in range(n):
            if i < warm:
                continue
            if in_pos:
                px = close_arr[i]
                bars_held += 1
                exit_now = False
                if not np.isnan(entry_level) and px < entry_level:
                    exit_now = True                                  # resistance-as-support broke
                elif not np.isnan(ma_arr[i]) and px < ma_arr[i]:
                    exit_now = True                                  # regime broke
                elif self.stop_pct > 0 and px <= entry_price * (1 - self.stop_pct):
                    exit_now = True
                elif self.take_pct > 0 and px >= entry_price * (1 + self.take_pct):
                    exit_now = True
                elif self.max_hold_bars > 0 and bars_held >= self.max_hold_bars:
                    exit_now = True
                if exit_now:
                    in_pos = False
                    signals[i] = 0.0
                else:
                    signals[i] = 1.0
            else:
                if enter_arr[i]:
                    in_pos = True
                    entry_price = close_arr[i]
                    entry_level = level_arr[i]
                    bars_held = 0
                    signals[i] = 1.0
                else:
                    signals[i] = 0.0

        return {
            "signal": signals,
            "has_reference": True,
            "regime_armed": regime.to_numpy().tolist(),
            "rs": rs.fillna(0.0).to_numpy().tolist(),
            "stock_up": stock_up.fillna(False).to_numpy().tolist(),
            "spy_down": spy_down.fillna(False).to_numpy().tolist(),
            "broke_out": broke_out.fillna(False).to_numpy().tolist(),
            "momentum_ok": momentum_ok.fillna(False).to_numpy().tolist(),
            "enter": enter_arr.tolist(),
        }

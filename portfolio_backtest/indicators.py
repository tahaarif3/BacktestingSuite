"""Per-symbol indicator layer. All indicators are causal (no today-inclusive
breakout high) so signals never peek at the future."""

from __future__ import annotations

import numpy as np
import pandas as pd

from portfolio_backtest.config import PortfolioBacktestConfig


def add_indicators(df: pd.DataFrame, cfg: PortfolioBacktestConfig) -> pd.DataFrame:
    """Augment an OHLCV frame (columns open/high/low/close/volume, DatetimeIndex)
    with the indicators the signal + engine need."""
    d = df.copy()
    close, high, low, vol = d["close"], d["high"], d["low"], d["volume"]

    d["sma_fast"] = close.rolling(cfg.trend_fast_ma).mean()
    d["sma_slow"] = close.rolling(cfg.trend_slow_ma).mean()
    d["sma_exit"] = close.rolling(cfg.exit_ma).mean()

    # ATR(14): mean of true range.
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    d["atr"] = tr.rolling(cfg.atr_window).mean()

    d["avg_vol"] = vol.rolling(cfg.volume_window).mean()
    d["dollar_vol"] = (close * vol).rolling(cfg.volume_window).mean()

    # Prior N-day high EXCLUDING today (t-window .. t-1).
    d["prior_high"] = high.rolling(cfg.breakout_window).max().shift(1)

    d["ret_rs"] = close / close.shift(cfg.rs_lookback) - 1.0

    rng = (high - low).replace(0, np.nan)
    d["candle_loc"] = ((close - low) / rng).fillna(0.5).clip(0.0, 1.0)

    d["volume_ratio"] = vol / d["avg_vol"]
    d["breakout_pct"] = close / d["prior_high"] - 1.0
    return d

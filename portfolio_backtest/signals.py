"""Daily candidate-signal generation.

Signals are computed from data available at each bar's close; entry executes at
the NEXT bar's open (the engine enforces the +1 fill). The market filter and
relative strength are evaluated against the benchmark, aligned by date.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

from portfolio_backtest.config import PortfolioBacktestConfig
from portfolio_backtest.indicators import add_indicators


def market_filter(spy: pd.DataFrame, cfg: PortfolioBacktestConfig) -> pd.Series:
    """Benchmark regime gate: SPY above a rising SMA(market_ma)."""
    ma = spy["close"].rolling(cfg.market_ma).mean()
    rising = ma - ma.shift(cfg.market_slope_lookback) > 0
    ok = (spy["close"] > ma) & rising
    if not cfg.use_market_filter:
        return pd.Series(True, index=spy.index)
    return ok.fillna(False)


def build_signals(
    cfg: PortfolioBacktestConfig,
    ohlcv_by_symbol: Dict[str, pd.DataFrame],
    spy: pd.DataFrame,
):
    """Returns (market_ok Series, {symbol: signal DataFrame}).

    Each per-symbol frame is indexed by that symbol's dates and carries the
    columns the engine consumes: open/high/low/close, atr, sma_exit, signal
    (bool), rs, volume_ratio, breakout_pct, dollar_vol.
    """
    mkt = market_filter(spy, cfg)
    spy_ret = (spy["close"] / spy["close"].shift(cfg.rs_lookback) - 1.0)

    out: Dict[str, pd.DataFrame] = {}
    for sym, raw in ohlcv_by_symbol.items():
        d = add_indicators(raw, cfg)

        # relative strength vs SPY, aligned by date
        spy_ret_aligned = spy_ret.reindex(d.index)
        rs = d["ret_rs"] - spy_ret_aligned

        qualified = (d["close"] > d["sma_fast"]) & (d["close"] > d["sma_slow"]) & (d["sma_fast"] > d["sma_slow"])
        if cfg.use_rs_filter:
            qualified = qualified & (rs > cfg.rs_threshold)

        entry = (
            (d["close"] > d["prior_high"])
            & (d["volume_ratio"] > cfg.volume_mult)
            & (d["candle_loc"] >= cfg.close_location_min)
        )

        mkt_aligned = mkt.reindex(d.index).fillna(False)
        signal = (mkt_aligned & qualified & entry).fillna(False)

        frame = pd.DataFrame({
            "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"],
            "atr": d["atr"], "sma_exit": d["sma_exit"], "signal": signal,
            "rs": rs, "volume_ratio": d["volume_ratio"], "breakout_pct": d["breakout_pct"],
            "dollar_vol": d["dollar_vol"],
        }, index=d.index)
        out[sym] = frame
    return mkt, out

"""Backtest specification — every rule is a parameter, nothing hard-coded."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PortfolioBacktestConfig:
    # --- universe / period ---
    tickers: List[str] = field(default_factory=list)   # empty -> default watchlist
    start: str = "2016-01-01"
    end: str = "2025-12-31"
    benchmark: str = "SPY"

    # --- market filter (regime gate on the benchmark) ---
    market_ma: int = 90                 # SPY close must be above its SMA(market_ma)
    market_slope_lookback: int = 20     # ...and that SMA rising over this lookback
    use_market_filter: bool = True

    # --- stock qualification ---
    trend_fast_ma: int = 90             # Close > SMA(90)
    trend_slow_ma: int = 200            # Close > SMA(200), SMA(90) > SMA(200)
    rs_lookback: int = 60               # 60-day stock return - SPY return
    rs_threshold: float = 0.05          # ...must exceed +5%
    use_rs_filter: bool = True

    # --- entry trigger ---
    breakout_window: int = 20           # Close > highest high of prior N days (excl. today)
    volume_window: int = 20
    volume_mult: float = 1.25           # Volume > 1.25x avg(volume_window)
    close_location_min: float = 0.75    # (Close-Low)/(High-Low) >= this

    # --- ranking of competing signals ---
    rank_mode: str = "rs"               # "rs" | "composite"
    w_rs: float = 0.60
    w_volume: float = 0.25
    w_breakout: float = 0.15

    # --- risk / portfolio limits ---
    initial_capital: float = 100000.0
    risk_per_trade: float = 0.005       # 0.5% of equity risked per trade
    max_positions: int = 10
    max_position_pct: float = 0.15      # position value cap, fraction of equity
    max_per_sector: int = 2
    atr_window: int = 14
    stop_atr_mult: float = 2.0          # initial stop = entry - mult*ATR
    exit_ma: int = 20                   # exit when close < SMA(exit_ma)

    # --- execution ---
    slippage_pct: float = 0.0005        # adverse slippage each side
    commission_per_share: float = 0.0
    commission_per_order: float = 0.0
    min_commission: float = 0.0
    gap_reject_pct: Optional[float] = None  # skip entry if next_open > signal_close*(1+this)
    whole_shares: bool = True

    # --- options mapping (optional, synthetic BS) ---
    trade_mode: str = "equity"          # "equity" | "options"
    option_structure: str = "bull_put_spread"
    option_selection: str = "delta"
    option_short_delta: float = 0.30
    option_pct_otm: float = 0.05
    option_width: float = 5.0
    option_dte_bars: int = 30
    option_grid_spacing: float = 5.0
    iv_multiplier: float = 1.2
    risk_free_rate: float = 0.04

    # --- data refresh ---
    refresh: bool = False               # re-fetch data through `end`

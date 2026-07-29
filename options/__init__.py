"""Options trading layer for BacktestingSuite.

A dependency-free, Black-Scholes *synthetic* options layer: since there is no
free source of historical option prices, every leg's premium is priced from the
underlying bar's price, an implied volatility (derived from the underlying's own
realized volatility), a risk-free rate, and time-to-expiry.

The package is consumed by both the automated backtester (``backtest``) and the
interactive replay mode (``desktop.backend.services``). It never touches the
existing share-based equity path — options are a parallel instrument model.

Public surface:
    pricing      Black-Scholes price + greeks (stdlib math only, no scipy).
    volatility   realized-volatility implied-vol model.
    instruments  OptionLeg / OptionStructure, contract multiplier, margin.
    structures   spread factories (bear_call_spread, verticals, condor, ...).
    strikes      StrikeGrid + strike selection by delta / %OTM / absolute.
    portfolio    OptionsPortfolio marking loop + trade reconstruction.
    ledger       build_options_ledger — the replay ledger for options.
"""

from options.pricing import bs_price, bs_greeks, d1_d2, CONTRACT_MULTIPLIER
from options.volatility import realized_vol_series, iv_for_bar
from options.instruments import OptionLeg, OptionStructure
from options.strikes import StrikeGrid, strike_for_delta, strike_for_pct_otm, nearest_strike
from options import structures

__all__ = [
    "bs_price",
    "bs_greeks",
    "d1_d2",
    "CONTRACT_MULTIPLIER",
    "realized_vol_series",
    "iv_for_bar",
    "OptionLeg",
    "OptionStructure",
    "StrikeGrid",
    "strike_for_delta",
    "strike_for_pct_otm",
    "nearest_strike",
    "structures",
]

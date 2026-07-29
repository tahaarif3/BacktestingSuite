"""Runs backtests by importing the existing engine directly (no CLI shelling).

Returns JSON-friendly results: summary metrics plus equity / benchmark /
drawdown / rolling-return series and the reconstructed trade log.
"""

import os
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from desktop.backend.paths import OUTPUT_DIR
from desktop.backend.schemas import BacktestConfig
from desktop.backend.services.data_service import resolve_data_path

from data.dataloader import DataLoader
from domain.models import Bar
from backtest.event_driven import EventDrivenEngine
from backtest.execution import ExecutionModel
from backtest.portfolio import Portfolio
from backtest.options_engine import OptionsEventDrivenEngine
from analytics.metrics import PerformanceMetrics, extract_trades
from analytics.reports import generate_html_report
from options.structures import StructureSpec
from options.portfolio import reconstruct_option_trades
from strategy_registry import build_strategy, build_sizer, STRATEGIES

ROLLING_WINDOW = 21  # ~1 trading month for rolling returns


def load_bars(config: BacktestConfig) -> List[Bar]:
    path = resolve_data_path(config.data.file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {os.path.basename(path)}")
    return DataLoader().get_bars(path)


def run_engine(
    config: BacktestConfig, bars: List[Bar], signals: List[float] = None
) -> Tuple[Portfolio, pd.DataFrame, Dict[str, Any], type]:
    """Build components from the config and run the engine. Returns
    (portfolio, trades_df, resolved_strategy_params, strategy_class).

    ``signals`` lets callers (e.g. the replay layer) supply a precomputed signal
    series so the engine runs the exact same signals rather than regenerating
    them. When ``None`` the strategy generates them, preserving existing callers.
    """
    strategy, strategy_params = build_strategy(
        config.strategy, config.params, allow_short=config.short
    )
    sizer = build_sizer(config.sizer, config.sizer_value, config.capital)
    exec_model = ExecutionModel(
        slippage_pct=config.slippage_pct,
        commission_pct=config.commission_pct,
        commission_per_share=config.commission_per_share,
    )
    engine = EventDrivenEngine(
        strategy=strategy,
        position_sizer=sizer,
        execution_model=exec_model,
        initial_capital=config.capital,
        execution_timing=config.timing,
        min_trade_shares=config.min_trade_shares,
    )
    portfolio = engine.run(bars, signals=signals)
    trades_df = extract_trades(portfolio.data, config.timing)
    return portfolio, trades_df, strategy_params, type(strategy)


def structure_spec_from_config(config: BacktestConfig) -> StructureSpec:
    """Build an options StructureSpec from a config's ``options`` block
    (falling back to a default bear call spread)."""
    o = config.options
    if o is None:
        return StructureSpec()
    return StructureSpec(
        structure_type=o.structure_type,
        selection=o.selection,
        short_delta=o.short_delta,
        pct_otm=o.pct_otm,
        width=o.width,
        strikes=list(o.strikes) if o.strikes else None,
        dte_bars=o.dte_bars,
        contracts=o.contracts,
        grid_spacing=o.grid_spacing,
    )


def _vol_kwargs(config: BacktestConfig) -> Dict[str, Any]:
    v = config.vol
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


def run_options_engine(config: BacktestConfig, bars: List[Bar], signals: List[float] = None):
    """Run the options-mode backtest. Returns (ledger_result, trades_df, params)."""
    strategy, strategy_params = build_strategy(
        config.strategy, config.params, allow_short=config.short
    )
    exec_model = ExecutionModel(
        slippage_pct=config.slippage_pct,
        commission_pct=config.commission_pct,
        commission_per_share=config.commission_per_share,
    )
    engine = OptionsEventDrivenEngine(
        strategy=strategy,
        structure=structure_spec_from_config(config),
        execution_model=exec_model,
        initial_capital=config.capital,
        execution_timing=config.timing,
        **_vol_kwargs(config),
    )
    result = engine.run(bars, signals=signals)
    trades_df = reconstruct_option_trades(result.closed_trades)
    return result, trades_df, strategy_params


def _iso(index) -> List[str]:
    return [ts.strftime("%Y-%m-%d") for ts in index]


def _clean_num(x: float) -> float:
    """Make a float safe for JSON (no NaN/inf)."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return 0.0
    return float(x)


def _series_payload(portfolio: Portfolio) -> Dict[str, Any]:
    equity = portfolio.equity_curve
    close = portfolio.data["close"]
    initial = float(equity.iloc[0]) if not equity.empty else 0.0

    benchmark = PerformanceMetrics.get_benchmark_equity(close, initial)

    peaks = equity.cummax()
    drawdown = (equity - peaks) / peaks

    daily_ret = equity.pct_change().fillna(0.0)
    rolling = daily_ret.rolling(ROLLING_WINDOW).mean() * 252  # annualised rolling return

    dates = _iso(equity.index)
    return {
        "dates": dates,
        "equity": [_clean_num(v) for v in equity.tolist()],
        "benchmark": [_clean_num(v) for v in benchmark.tolist()],
        "drawdown": [_clean_num(v) for v in drawdown.tolist()],
        "rolling_returns": [_clean_num(v) for v in rolling.fillna(0.0).tolist()],
        "close": [_clean_num(v) for v in close.tolist()],
    }


def _trades_payload(trades_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if trades_df.empty:
        return []
    rows = []
    for _, r in trades_df.iterrows():
        rows.append(
            {
                "entry_time": r["entry_time"].strftime("%Y-%m-%d %H:%M")
                if hasattr(r["entry_time"], "strftime") else str(r["entry_time"]),
                "exit_time": r["exit_time"].strftime("%Y-%m-%d %H:%M")
                if hasattr(r["exit_time"], "strftime") else str(r["exit_time"]),
                "direction": r["direction"],
                "size": _clean_num(r["size"]),
                "entry_price": _clean_num(r["entry_price"]),
                "exit_price": _clean_num(r["exit_price"]),
                "pnl_usd": _clean_num(r["pnl_usd"]),
                "pnl_pct": _clean_num(r["pnl_pct"]),
                "duration_days": int(r["duration_days"]),
            }
        )
    return rows


def _summary_payload(summary: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _clean_num(v) if isinstance(v, (int, float)) else v for k, v in summary.items()}


def _options_series_payload(portfolio) -> Dict[str, Any]:
    """Series payload for the options equity curve. ``benchmark`` is the
    underlying buy-&-hold (a different instrument — labelled as such in the UI)."""
    equity = portfolio.equity_curve
    close = portfolio.data["close"]
    initial = float(equity.iloc[0]) if not equity.empty else 0.0
    benchmark = PerformanceMetrics.get_benchmark_equity(close, initial)
    peaks = equity.cummax()
    drawdown = (equity - peaks) / peaks
    daily_ret = equity.pct_change().fillna(0.0)
    rolling = daily_ret.rolling(ROLLING_WINDOW).mean() * 252
    return {
        "dates": _iso(equity.index),
        "equity": [_clean_num(v) for v in equity.tolist()],
        "benchmark": [_clean_num(v) for v in benchmark.tolist()],
        "drawdown": [_clean_num(v) for v in drawdown.tolist()],
        "rolling_returns": [_clean_num(v) for v in rolling.fillna(0.0).tolist()],
        "close": [_clean_num(v) for v in close.tolist()],
    }


def _option_trades_payload(trades_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if trades_df.empty:
        return []
    rows = []
    for _, r in trades_df.iterrows():
        rows.append({
            "entry_time": r["entry_time"].strftime("%Y-%m-%d %H:%M")
            if hasattr(r["entry_time"], "strftime") else str(r["entry_time"]),
            "exit_time": r["exit_time"].strftime("%Y-%m-%d %H:%M")
            if hasattr(r["exit_time"], "strftime") else str(r["exit_time"]),
            "structure": r["structure"],
            "contracts": int(r["contracts"]),
            "entry_cash": _clean_num(r["entry_cash"]),
            "exit_cash": _clean_num(r["exit_cash"]),
            "pnl_usd": _clean_num(r["pnl_usd"]),
            "pnl_pct": _clean_num(r["pnl_pct"]),
            "max_risk": _clean_num(r["max_risk"]),
            "reason": r["reason"],
        })
    return rows


def run_options_backtest(config: BacktestConfig) -> Dict[str, Any]:
    bars = load_bars(config)
    result, trades_df, strategy_params = run_options_engine(config, bars)
    portfolio = result.portfolio
    summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)
    spec = STRATEGIES.get(config.strategy)
    return {
        "strategy": config.strategy,
        "strategy_name": spec.name if spec else config.strategy,
        "mode": "options",
        "params": strategy_params,
        "options_config": config.options.model_dump() if config.options else None,
        "summary": _summary_payload(summary),
        "series": _options_series_payload(portfolio),
        "option_trades": _option_trades_payload(trades_df),
        "realized_pnl": _clean_num(result.realized_pnl),
        "unrealized_pnl": _clean_num(result.unrealized_pnl),
        "max_risk": _clean_num(result.max_risk),
        "initial_equity": _clean_num(portfolio.equity_curve.iloc[0]),
        "final_equity": _clean_num(portfolio.equity_curve.iloc[-1]),
    }


def run_backtest(config: BacktestConfig) -> Dict[str, Any]:
    if config.mode == "options":
        return run_options_backtest(config)
    bars = load_bars(config)
    portfolio, trades_df, strategy_params, _ = run_engine(config, bars)
    summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)

    spec = STRATEGIES.get(config.strategy)
    return {
        "strategy": config.strategy,
        "strategy_name": spec.name if spec else config.strategy,
        "mode": "equity",
        "params": strategy_params,
        "summary": _summary_payload(summary),
        "series": _series_payload(portfolio),
        "trades": _trades_payload(trades_df),
        "initial_equity": _clean_num(portfolio.equity_curve.iloc[0]),
        "final_equity": _clean_num(portfolio.equity_curve.iloc[-1]),
    }


def generate_report(config: BacktestConfig) -> str:
    """Generate the self-contained HTML report and return its markup."""
    bars = load_bars(config)
    portfolio, trades_df, strategy_params, _ = run_engine(config, bars)

    spec = STRATEGIES.get(config.strategy)
    name = spec.name if spec else config.strategy.upper()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    report_path = os.path.join(OUTPUT_DIR, "report.html")
    generate_html_report(
        portfolio_df=portfolio.data,
        trades_df=trades_df,
        strategy_name=name,
        strategy_params=strategy_params,
        output_path=report_path,
    )
    with open(report_path, "r", encoding="utf-8") as f:
        return f.read()

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
from analytics.metrics import PerformanceMetrics, extract_trades
from analytics.reports import generate_html_report
from strategy_registry import build_strategy, build_sizer, STRATEGIES

ROLLING_WINDOW = 21  # ~1 trading month for rolling returns


def load_bars(config: BacktestConfig) -> List[Bar]:
    path = resolve_data_path(config.data.file)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Data file not found: {os.path.basename(path)}")
    return DataLoader().get_bars(path)


def run_engine(config: BacktestConfig, bars: List[Bar]) -> Tuple[Portfolio, pd.DataFrame, Dict[str, Any], type]:
    """Build components from the config and run the engine. Returns
    (portfolio, trades_df, resolved_strategy_params, strategy_class)."""
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
    portfolio = engine.run(bars)
    trades_df = extract_trades(portfolio.data, config.timing)
    return portfolio, trades_df, strategy_params, type(strategy)


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


def run_backtest(config: BacktestConfig) -> Dict[str, Any]:
    bars = load_bars(config)
    portfolio, trades_df, strategy_params, _ = run_engine(config, bars)
    summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)

    spec = STRATEGIES.get(config.strategy)
    return {
        "strategy": config.strategy,
        "strategy_name": spec.name if spec else config.strategy,
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

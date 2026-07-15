"""Wraps the validation/ suite (train-test, walk-forward, Monte Carlo, cost
sensitivity) and returns structured data for interactive charting instead of
printing to a terminal or saving PNGs."""

from typing import Any, Dict, List

import numpy as np

from desktop.backend.paths import OUTPUT_DIR
from desktop.backend.schemas import BacktestConfig, CompareRequest, RobustnessRequest
from desktop.backend.services.backtest_service import (
    load_bars,
    run_engine,
    _series_payload,
    _summary_payload,
    _clean_num,
)

from analytics.metrics import PerformanceMetrics, extract_trades
from strategy_registry import STRATEGIES
from validation.optimization import train_test_split, GridSearchOptimizer, WalkForwardAnalyzer
from validation.monte_carlo import MonteCarloSimulator
from validation.sensitivity import CostSensitivityAnalyzer

COMMISSION_GRID = [0.0, 0.0002, 0.0005, 0.0010]
SLIPPAGE_GRID = [0.0, 0.0001, 0.0003, 0.0005]


def _sizer_fraction(config: BacktestConfig) -> float:
    return config.sizer_value if config.sizer == "fixed_fractional" else 0.5


def run_robustness(req: RobustnessRequest) -> Dict[str, Any]:
    config = req.config
    bars = load_bars(config)

    # Base run establishes the strategy class + resolved params + a trade log.
    portfolio, trades_df, strategy_params, strategy_class = run_engine(config, bars)
    sizer_fraction = _sizer_fraction(config)

    result: Dict[str, Any] = {
        "strategy": config.strategy,
        "train_test": None,
        "walk_forward": None,
        "monte_carlo": None,
        "cost_sensitivity": None,
    }

    # 1. Train-Test split (70/30) — compare in-sample vs out-of-sample Sharpe.
    if "train_test" in req.tests:
        train_bars, test_bars = train_test_split(bars, train_ratio=0.7)
        grid = {k: [v] for k, v in strategy_params.items()}

        def _sharpe(sample_bars):
            opt = GridSearchOptimizer(
                strategy_class=strategy_class, param_grid=grid,
                initial_capital=config.capital, sizer_fraction=sizer_fraction,
                slippage_pct=config.slippage_pct, commission_pct=config.commission_pct,
            )
            return opt.optimize(sample_bars)["best_metric_value"]

        is_sharpe = _sharpe(train_bars)
        oos_sharpe = _sharpe(test_bars)
        decay = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0
        result["train_test"] = {
            "is_sharpe": _clean_num(is_sharpe),
            "oos_sharpe": _clean_num(oos_sharpe),
            "decay": _clean_num(decay),
            "warning": bool(decay < 0.4),
        }

    # 2. Walk-forward analysis (skipped for strategies without a param grid).
    if "walk_forward" in req.tests:
        spec = STRATEGIES.get(config.strategy)
        wfa_grid = spec.wfa_grid if spec else {}
        if wfa_grid and len(bars) >= 180:
            wfa = WalkForwardAnalyzer(
                strategy_class=strategy_class, param_grid=wfa_grid,
                train_span_bars=140, test_span_bars=40,
                initial_capital=config.capital, sizer_fraction=sizer_fraction,
                slippage_pct=config.slippage_pct, commission_pct=config.commission_pct,
            )
            wfa_res = wfa.run_walk_forward(bars)
            result["walk_forward"] = {
                "wfe": _clean_num(wfa_res["wfe"]),
                "avg_is_sharpe": _clean_num(wfa_res["avg_is_sharpe"]),
                "oos_sharpe": _clean_num(wfa_res["oos_summary"].get("Sharpe Ratio", 0.0)),
                "warning": bool(wfa_res["overfitting_warning"]),
                "warning_message": wfa_res.get("warning_message", ""),
                "windows": [
                    {
                        "window": w["window"],
                        "train_dates": w["train_dates"],
                        "test_dates": w["test_dates"],
                        "train_sharpe": _clean_num(w["train_sharpe"]),
                        "test_sharpe": _clean_num(w["test_sharpe"]),
                        "best_params": w["best_params"],
                    }
                    for w in wfa_res["windows_report"]
                ],
            }
        else:
            result["walk_forward"] = {"skipped": True, "reason": "No parameter grid or insufficient bars."}

    # 3. Monte Carlo trade-sequence shuffling.
    if "monte_carlo" in req.tests:
        if len(trades_df) >= 3:
            mc = MonteCarloSimulator.simulate_trade_shuffling(
                trades_df=trades_df, initial_capital=config.capital,
                iterations=req.mc_iterations, ruin_threshold_pct=0.5, output_dir=OUTPUT_DIR,
            )
            mc.pop("plot_path", None)
            result["monte_carlo"] = {k: _clean_num(v) if isinstance(v, (int, float)) else v for k, v in mc.items()}
        else:
            result["monte_carlo"] = {"skipped": True, "reason": "Requires at least 3 trades."}

    # 4. Cost sensitivity grid.
    if "cost_sensitivity" in req.tests:
        analyzer = CostSensitivityAnalyzer(
            strategy_class=strategy_class, strategy_params=strategy_params,
            initial_capital=config.capital, sizer_fraction=sizer_fraction,
        )
        df = analyzer.run_sensitivity_analysis(
            bars=bars, commission_grid=COMMISSION_GRID, slippage_grid=SLIPPAGE_GRID, output_dir=OUTPUT_DIR,
        )
        # Build a commission x slippage Sharpe matrix for a heatmap.
        matrix = [[0.0 for _ in SLIPPAGE_GRID] for _ in COMMISSION_GRID]
        for _, row in df.iterrows():
            i = COMMISSION_GRID.index(row["commission_pct"])
            j = SLIPPAGE_GRID.index(row["slippage_pct"])
            matrix[i][j] = _clean_num(row["sharpe_ratio"])
        result["cost_sensitivity"] = {
            "commission_grid": COMMISSION_GRID,
            "slippage_grid": SLIPPAGE_GRID,
            "sharpe_matrix": matrix,
        }

    return result


def compare(req: CompareRequest) -> Dict[str, Any]:
    """Run several configs and return aligned metrics + equity curves."""
    runs: List[Dict[str, Any]] = []
    for i, config in enumerate(req.runs):
        label = req.labels[i] if req.labels and i < len(req.labels) else None
        bars = load_bars(config)
        portfolio, trades_df, strategy_params, _ = run_engine(config, bars)
        summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)
        spec = STRATEGIES.get(config.strategy)
        series = _series_payload(portfolio)
        runs.append(
            {
                "label": label or (spec.name if spec else config.strategy),
                "strategy": config.strategy,
                "params": strategy_params,
                "summary": _summary_payload(summary),
                "dates": series["dates"],
                "equity": series["equity"],
            }
        )
    return {"runs": runs}

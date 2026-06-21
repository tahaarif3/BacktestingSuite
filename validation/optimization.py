import itertools
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Tuple, Type
from domain.models import Bar
from backtest.event_driven import EventDrivenEngine
from backtest.position_sizing import FixedFractionalSizer
from backtest.execution import ExecutionModel
from backtest.portfolio import Portfolio
from analytics.metrics import PerformanceMetrics, extract_trades

def train_test_split(bars: List[Bar], train_ratio: float = 0.7) -> Tuple[List[Bar], List[Bar]]:
    """
    Splits chronological list of bars into In-Sample (IS) training
    and Out-of-Sample (OOS) testing sets.
    """
    if not bars:
        return [], []
    split_idx = int(len(bars) * train_ratio)
    return bars[:split_idx], bars[split_idx:]


class GridSearchOptimizer:
    """
    Optimizes strategy parameters by running grid search backtests on historical bars.
    Includes overfitting checks.
    """

    def __init__(
        self,
        strategy_class: Type,
        param_grid: Dict[str, List[Any]],
        initial_capital: float = 100000.0,
        sizer_fraction: float = 0.5,
        slippage_pct: float = 0.0002,
        commission_pct: float = 0.0005
    ):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.initial_capital = initial_capital
        self.sizer_fraction = sizer_fraction
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct

    def optimize(self, bars: List[Bar], metric: str = "Sharpe Ratio") -> Dict[str, Any]:
        """
        Runs backtests for all combinations in the parameter grid.
        Returns the best parameters, all results, and overfitting flags.
        """
        if not bars:
            raise ValueError("Bars list cannot be empty for optimization.")

        # Generate all parameter combinations
        keys, values = zip(*self.param_grid.items())
        permutations = [dict(zip(keys, v)) for v in itertools.product(*values)]
        
        results = []
        best_params = None
        best_metric_val = -float('inf')
        best_portfolio = None
        best_trades_df = None

        for params in permutations:
            # Instantiate strategy & engine components
            strat = self.strategy_class(**params)
            sizer = FixedFractionalSizer(fraction=self.sizer_fraction, initial_capital=self.initial_capital)
            exec_model = ExecutionModel(slippage_pct=self.slippage_pct, commission_pct=self.commission_pct)
            
            engine = EventDrivenEngine(
                strategy=strat,
                position_sizer=sizer,
                execution_model=exec_model,
                initial_capital=self.initial_capital
            )

            try:
                portfolio = engine.run(bars)
                trades_df = extract_trades(portfolio.data)
                summary = PerformanceMetrics.get_advanced_summary(portfolio.data, trades_df)
                
                # Fetch metric value (handle default to Sharpe Ratio)
                metric_val = summary.get(metric, 0.0)
                if np.isnan(metric_val) or np.isinf(metric_val):
                    metric_val = -100.0
                
                res_entry = {
                    "params": params,
                    "metrics": summary,
                    "trades_count": len(trades_df)
                }
                results.append(res_entry)

                if metric_val > best_metric_val:
                    best_metric_val = metric_val
                    best_params = params
                    best_portfolio = portfolio
                    best_trades_df = trades_df

            except Exception as e:
                # Log error and skip this parameter set
                print(f"Skipping parameter combo {params} due to error: {e}")
                continue

        if not results:
            raise RuntimeError("No backtest runs completed successfully during grid search.")

        # Overfitting Analysis
        overfitting_warning = False
        warning_messages = []

        if best_metric_val > 3.0 and metric == "Sharpe Ratio":
            overfitting_warning = True
            warning_messages.append(
                f"Extremely high In-Sample Sharpe Ratio ({best_metric_val:.2f} > 3.0) "
                "suggests possible lookahead bias, selection bias, or overfitting."
            )

        num_combos = len(permutations)
        best_trades_count = len(best_trades_df) if best_trades_df is not None else 0
        if best_trades_count > 0 and num_combos > 0.5 * best_trades_count:
            overfitting_warning = True
            warning_messages.append(
                f"High parameter-to-trade ratio: searched {num_combos} combinations for only "
                f"{best_trades_count} trades. Risk of parameter fitting is high."
            )

        return {
            "best_params": best_params,
            "best_metric_value": best_metric_val,
            "best_portfolio": best_portfolio,
            "best_trades": best_trades_df,
            "all_results": results,
            "overfitting_warning": overfitting_warning,
            "warning_messages": warning_messages
        }


class WalkForwardAnalyzer:
    """
    Performs Walk-Forward Analysis (WFA) by optimization over rolling or anchored windows
    and assembling out-of-sample (OOS) testing intervals into a continuous equity curve.
    """

    def __init__(
        self,
        strategy_class: Type,
        param_grid: Dict[str, List[Any]],
        train_span_bars: int,
        test_span_bars: int,
        initial_capital: float = 100000.0,
        sizer_fraction: float = 0.5,
        slippage_pct: float = 0.0002,
        commission_pct: float = 0.0005
    ):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.train_span_bars = train_span_bars
        self.test_span_bars = test_span_bars
        self.initial_capital = initial_capital
        self.sizer_fraction = sizer_fraction
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct

    def run_walk_forward(self, bars: List[Bar], anchored: bool = False) -> Dict[str, Any]:
        """
        Runs Walk-Forward Analysis.
        anchored: If True, train start index remains 0 (anchored training window).
                  If False, train start index rolls forward.
        """
        n_bars = len(bars)
        if n_bars < self.train_span_bars + self.test_span_bars:
            raise ValueError("Total bars count is smaller than train + test spans.")

        oos_segments = []
        windows_report = []
        is_sharpe_list = []

        start = 0
        # Walk forward through the dataset
        while start + self.train_span_bars + self.test_span_bars <= n_bars:
            # 1. Define Train and Test segments
            train_start = 0 if anchored else start
            train_end = start + self.train_span_bars
            test_start = train_end
            test_end = test_start + self.test_span_bars

            train_bars = bars[train_start:train_end]
            test_bars = bars[test_start:test_end]

            # 2. Run Grid Search Optimizer on training window
            optimizer = GridSearchOptimizer(
                strategy_class=self.strategy_class,
                param_grid=self.param_grid,
                initial_capital=self.initial_capital,
                sizer_fraction=self.sizer_fraction,
                slippage_pct=self.slippage_pct,
                commission_pct=self.commission_pct
            )
            opt_res = optimizer.optimize(train_bars, metric="Sharpe Ratio")
            best_params = opt_res["best_params"]
            is_sharpe = opt_res["best_metric_value"]
            is_sharpe_list.append(is_sharpe)

            # 3. Test optimized parameters on the adjacent OOS testing window
            strat_test = self.strategy_class(**best_params)
            sizer_test = FixedFractionalSizer(fraction=self.sizer_fraction, initial_capital=self.initial_capital)
            exec_test = ExecutionModel(slippage_pct=self.slippage_pct, commission_pct=self.commission_pct)
            
            engine_test = EventDrivenEngine(
                strategy=strat_test,
                position_sizer=sizer_test,
                execution_model=exec_test,
                initial_capital=self.initial_capital
            )
            
            portfolio_test = engine_test.run(test_bars)
            trades_test_df = extract_trades(portfolio_test.data)
            test_summary = PerformanceMetrics.get_advanced_summary(portfolio_test.data, trades_test_df)
            oos_sharpe = test_summary.get("Sharpe Ratio", 0.0)

            oos_segments.append(portfolio_test.data)

            windows_report.append({
                "window": len(windows_report) + 1,
                "train_dates": f"{train_bars[0].timestamp.strftime('%Y-%m-%d')} to {train_bars[-1].timestamp.strftime('%Y-%m-%d')}",
                "test_dates": f"{test_bars[0].timestamp.strftime('%Y-%m-%d')} to {test_bars[-1].timestamp.strftime('%Y-%m-%d')}",
                "best_params": best_params,
                "train_sharpe": is_sharpe,
                "test_sharpe": oos_sharpe
            })

            start += self.test_span_bars

        # 4. Chain OOS portfolio segments to form a continuous equity curve
        oos_df = self._chain_portfolios(oos_segments)
        
        # 5. Calculate out-of-sample metrics
        oos_trades_df = extract_trades(oos_df)
        oos_summary = PerformanceMetrics.get_advanced_summary(oos_df, oos_trades_df)
        oos_sharpe_total = oos_summary.get("Sharpe Ratio", 0.0)

        # Walk-Forward Efficiency (WFE)
        avg_is_sharpe = np.mean(is_sharpe_list) if is_sharpe_list else 0.0
        wfe = oos_sharpe_total / avg_is_sharpe if avg_is_sharpe > 0 else 0.0

        # Overfitting flag for walk-forward efficiency
        overfitting_warning = wfe < 0.4
        warning_message = ""
        if overfitting_warning:
            warning_message = (
                f"Low Walk-Forward Efficiency (WFE = {wfe:.2f} < 0.40). "
                "The strategy shows severe out-of-sample performance decay, indicating parameter instability/overfitting."
            )

        return {
            "oos_portfolio_df": oos_df,
            "oos_summary": oos_summary,
            "oos_trades": oos_trades_df,
            "wfe": wfe,
            "avg_is_sharpe": avg_is_sharpe,
            "windows_report": windows_report,
            "overfitting_warning": overfitting_warning,
            "warning_message": warning_message
        }

    def _chain_portfolios(self, portfolios: List[pd.DataFrame]) -> pd.DataFrame:
        """
        Chains multiple out-of-sample portfolio DataFrames into a single continuous DataFrame,
        adjusting cash, equity, positions, and trades to maintain capital continuity.
        """
        if not portfolios:
            return pd.DataFrame()
            
        chained_dfs = []
        current_multiplier = 1.0
        
        for i, df in enumerate(portfolios):
            if df.empty:
                continue
                
            df_copy = df.copy()
            
            if i > 0:
                # Get final equity of previous segment
                prev_final_equity = chained_dfs[-1]["equity"].iloc[-1]
                # Get initial equity of current segment (before scaling)
                curr_initial_equity = df_copy["equity"].iloc[0]
                
                # Update multiplier
                if curr_initial_equity > 0:
                    current_multiplier = prev_final_equity / curr_initial_equity
                else:
                    current_multiplier = 1.0
                    
            # Scale capital-dependent columns
            scale_cols = ["cash", "equity", "slippage_cost", "commission_cost", "target_position", "active_position", "trades"]
            for col in scale_cols:
                if col in df_copy.columns:
                    df_copy[col] = df_copy[col] * current_multiplier
                    
            chained_dfs.append(df_copy)
            
        if not chained_dfs:
            return pd.DataFrame()
            
        combined_df = pd.concat(chained_dfs)
        # Remove duplicate index timestamps (keeping last to preserve contiguous boundaries)
        combined_df = combined_df[~combined_df.index.duplicated(keep='last')]
        return combined_df

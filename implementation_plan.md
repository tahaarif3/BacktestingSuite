# Implementation Plan: Phase 4 Performance Analytics & Plotting

This document outlines the design and step-by-step checklist to implement Phase 4 Performance Analytics, including a comprehensive statistical metrics module, a trade log extractor, and visual plotting utilities.

---

## Proposed Changes

### Component 1: Performance Metrics (`analytics/metrics.py`)
We will create a new module [metrics.py](file:///C:/Users/bigbo/Spy_Backtest/analytics/metrics.py) to calculate the following metrics:
- **CAGR**: Compound Annual Growth Rate.
- **Sharpe Ratio**: Risk-adjusted return assuming a 0% risk-free rate.
- **Sortino Ratio**: Risk-adjusted return using downside deviation (only negative daily returns) instead of standard deviation.
- **Max Drawdown**: Maximum peak-to-trough drawdown.
- **Win Rate**: Percentage of winning trades (P&L > 0) from the trade log.
- **Profit Factor**: Gross Profit divided by Gross Loss.
- **Exposure Time**: Percentage of bars with an active position.

### Component 2: Trade Log Extractor (`analytics/metrics.py`)
We will implement a state machine that parses the event-driven trades series and reconstructs discrete round-trip trades. It will support:
- **Entry & Exit Timestamps**
- **Trade Direction** (Long vs. Short)
- **Trade Size** (number of shares)
- **Execution Prices** (Entry vs. Exit)
- **Trade P&L** (in dollars and percentage)
- **Trade Duration** (as timedelta or number of bars)
- **Scaling In/Out** (blending average cost for entries, realizing partial profits/losses for exits)

### Component 3: Plotting & Charting (`analytics/plots.py`)
We will create a plotting module [plots.py](file:///C:/Users/bigbo/Spy_Backtest/analytics/plots.py) using `matplotlib` to generate and save charts to disk:
1. **Equity Curve vs. Benchmark**: Plots the strategy's equity curve compared to a buy-and-hold benchmark of SPY (reinvesting initial capital on Day 1 Close).
2. **Drawdown Chart**: Area plot showing the peak-to-trough drawdown curve over time.
3. **Rolling Returns**: Plots rolling returns over a user-defined window (e.g., 20 days or 60 days) to visualize strategy consistency.

### Component 4: Runner & Composition Root Updates
We will update `scratch/backtest_run.py` to call these new modules, print the advanced metrics summary, generate a trade log CSV, and save the charts as images.

---

## Proposed Directory Layout

```
C:\Users\bigbo\Spy_Backtest
├── analytics
│   ├── __init__.py
│   ├── metrics.py        <-- [NEW] Calculate CAGR, Sharpe, Sortino, Win Rate, Profit Factor, Exposure
│   └── plots.py          <-- [NEW] Generate PNG charts (Equity vs. Benchmark, Drawdowns, Rolling Returns)
├── presentation
│   └── presenter.py      <-- [MODIFY] Add formatting for advanced metrics and trade log
```

---

## Detailed Step-by-Step Checklist

### Phase 1: Metrics & Trade Log Extraction
- [ ] **1.1. Create `analytics/metrics.py`**
  - Implement `PerformanceMetrics` class.
  - Implement `extract_trades(portfolio_df: pd.DataFrame) -> pd.DataFrame` using a state machine that handles FIFO/weighted average entry costs, position flips, and partial scaling.
  - Implement calculations for `win_rate`, `profit_factor`, `exposure_time`, and `sortino_ratio`.
  - Implement a method `get_benchmark_equity(prices: pd.Series, initial_capital: float) -> pd.Series` to generate a buy-and-hold comparison curve.

### Phase 2: Chart Generation Layer
- [ ] **2.1. Create `analytics/plots.py`**
  - Implement `generate_backtest_report_plots(portfolio_df: pd.DataFrame, benchmark_curve: pd.Series, output_dir: str) -> dict`
  - Chart 1: **Equity Curve vs. Benchmark** (Line chart, log/linear scale, labeled axis, legend).
  - Chart 2: **Drawdown Curve** (Area fill plot, colored red, showing depth over time).
  - Chart 3: **Rolling Returns** (Line chart of rolling performance, comparing strategy vs benchmark).
  - Save all figures as high-resolution PNGs in an `output/` directory in the workspace.

### Phase 3: Presenter & Console Output Refinement
- [ ] **3.1. Modify `presentation/presenter.py`**
  - Add formatting helper for the advanced summary table (incorporating Sortino, Win Rate, Profit Factor, Exposure).
  - Implement `format_trade_log(trades_df: pd.DataFrame, limit: int = 10) -> str` to print a clean terminal table of recent trades.

### Phase 4: Integration & Validation
- [ ] **4.1. Refactor `scratch/backtest_run.py`**
  - Integrate metrics extraction and plotting.
  - Add logic to export the trade log to `output/trade_log.csv`.
  - Save the charts as `output/equity_comparison.png`, `output/drawdown_chart.png`, and `output/rolling_returns.png`.
- [ ] **4.2. Create Unit Tests**
  - Add tests in `test/test_analytics.py` verifying metrics calculation and trade parsing logic (e.g. validating profit factor is correct on mock trades, win rate matches expected value, Sortino ratio handles downside deviation correctly).

---

## Verification Plan

### Automated Tests
Run unit tests verifying the correctness of the calculations:
```bash
.\venv\Scripts\pytest test/test_analytics.py
```

### Manual Verification
Run the updated verification script:
```bash
.\venv\Scripts\python scratch/backtest_run.py
```
And verify that:
1. The advanced performance table is printed correctly.
2. The trade log is exported to `output/trade_log.csv`.
3. The PNG charts are saved inside the `output/` directory.

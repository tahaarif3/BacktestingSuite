# SPY Event-Driven Backtesting Suite

A production-grade, event-driven backtesting system in Python utilizing Pandas and NumPy to simulate realistic trading dynamics on daily SPY historical data. 

The suite is engineered around Clean Architecture principles to separate core trading logic (Strategies, Sizers, Execution Models) from presentation layers (CLI, Presenters, HTML Reports) and validation engines (Monte Carlo, Walk-Forward Analysis).

---

## 🛠️ Features

* **Event-Driven Execution Loop**: Simulates realistic bar-by-bar price feed processing, eliminating lookahead bias and enforcing trade execution on the next bar's Open or Close.
* **Modular Infrastructure**:
  * **Strategies**: Supports Buy & Hold, SMA Crossover, EMA Crossover, RSI Mean Reversion, Bollinger Bands Breakout, and MACD Trend Following. Supports both `long_only` and long-short regimes.
  * **Position Sizing**: Dynamically sizes positions based on Fixed Shares, Fixed Fractional (capital percentage), or Volatility-Adjusted (ATR-based dollar risk) models.
  * **Execution Cost Model**: Accounts for multi-tiered commission costs (flat fee, basis points, or per-share) and linear/absolute slippage.
* **Robustness & Validation Layer**:
  * **Train-Test Partitioning**: Evaluates parameter decay ratios out-of-sample.
  * **Grid Search Optimizer**: Optimizes parameters with overfitting check warnings.
  * **Walk-Forward Analysis (WFA)**: Validates parameter stability over rolling or anchored windows, calculating Walk-Forward Efficiency (WFE).
  * **Monte Carlo Simulations**: permutates trade sequence order to model Probability of Ruin and Drawdown Value-at-Risk (VaR).
  * **Cost Sensitivity Grid**: Maps performance decay across varying slippage and commission rates.
* **Automated HTML Reporting**: Exports self-contained, beautifully styled slaty-modern dashboard HTML files embedding base64 encoded diagnostic charts (Equity, Drawdown, Rolling Returns) and trade logs.

---

## 📂 Project Directory Structure

```
c:\Users\bigbo\Spy_Backtest
├── analytics
│   ├── metrics.py        # CAGR, Sharpe, Sortino, Win Rate, Profit Factor, FIFO Trade log extractor
│   ├── plots.py          # Matplotlib chart generators (Equity, Drawdown, Rolling Returns)
│   └── reports.py        # Self-contained HTML report compiler (Base64 inline plots)
├── backtest
│   ├── event_driven.py   # Event-driven backtesting simulation engine
│   ├── execution.py      # Execution cost model (slippage, commissions)
│   ├── portfolio.py      # Tracks equity curve, daily returns, drawdowns
│   └── position_sizing.py# Position sizers (Fixed Shares, Fractional, ATR Volatility)
├── data
│   └── dataloader.py     # Data loaders using Repository pattern (Parquet support)
├── domain
│   ├── interfaces.py     # Strategy, Sizer, and Execution model interfaces
│   └── models.py         # Domain models (Bar object)
├── presentation
│   └── presenter.py      # Terminal presentation tables for metrics and trades
├── validation
│   ├── optimization.py    # Grid Search, Train-Test split, Walk-Forward Analysis (WFA)
│   ├── monte_carlo.py     # Trade shuffling sequence risk and ruin simulator
│   └── sensitivity.py     # Transaction cost sensitivity grid and heatmap
├── test
│   ├── test_data.py      # Data validation unit tests
│   ├── test_strategies.py# Trading strategy signal unit tests
│   ├── test_backtest.py  # Simulation engine and lookahead unit tests
│   ├── test_engine.py    # Position sizers and execution cost unit tests
│   ├── test_analytics.py # Performance metrics and Trade FIFO extractor unit tests
│   ├── test_robustness.py# Walk-forward and Monte Carlo validation unit tests
│   └── test_reports.py   # HTML report generator unit tests
├── cli.py                # Command-line entry point to run backtests and validation
└── README.md             # Project documentation and CLI usage guide
```

---

## 🚀 Getting Started

### 1. Prerequisites
Ensure you have Python 3.10+ installed.

### 2. Environment Setup & Installation
Set up a Python virtual environment and install dependencies:
```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment
.\venv\Scripts\activate

# Install required dependencies
pip install -r requirements.txt
```

### 3. Fetch Historical SPY Parquet Data
Execute the sample run script to download historical SPY daily data via yfinance and cache it locally:
```powershell
python scratch/sample_run.py
```

---

## 🖥️ Command-Line Interface (CLI) Usage

The unified entry point [cli.py](file:///c:/Users/bigbo/Spy_Backtest/cli.py) allows running backtests, configuring sizers, and conducting robustness tests.

### 1. Help Command
View all configurable CLI options and defaults:
```powershell
python cli.py --help
```

### 2. Basic Crossover Backtest
Run an SMA Crossover (10/50 window) backtest using the default fixed fractional sizer:
```powershell
python cli.py --strategy sma --fast-window 10 --slow-window 50
```

### 3. Enable Shorting and Custom Sizing
Run an RSI Mean Reversion strategy allowing short signals, using an ATR Volatility position sizer risking $500 per trade:
```powershell
python cli.py --strategy rsi --short --sizer volatility --sizer-val 500
```

### 4. Generate Automated HTML Report
Run a MACD backtest and export a self-contained HTML report with embedded base64 diagnostic charts and trade logs:
```powershell
python cli.py --strategy macd --report
```
*The HTML report is saved to `output/report.html`.*

### 5. Run Full Robustness & Validation Suite
Run the SMA strategy and execute Walk-Forward Analysis, Monte Carlo trade sequence shufflers, and Cost Sensitivity heatmaps:
```powershell
python cli.py --strategy sma --robustness
```
*Outputs are saved to `output/monte_carlo_paths.png` and `output/cost_sensitivity.png`.*

---

## 🧪 Running Unit Tests

Run the complete suite of 46 automated unit tests verifying data loaders, strategies, engine mechanics, cost models, sizers, analytics, validation metrics, and reporting:

```powershell
pytest
```

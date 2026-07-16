# BacktestingSuite

A Windows desktop app for backtesting trading strategies on real market data — no
Python setup, no command line. Download, install, and run your first backtest in
under a minute.

Built on a production-grade, event-driven backtesting engine (bar-by-bar execution,
no lookahead bias, realistic commission and slippage modeling), with a full
robustness suite and an in-app code editor for writing your own strategies.

---

## 📥 Download & Install

**[Download the latest installer](https://github.com/tahaarif3/BacktestingSuite/releases/latest)** —
`BacktestingSuite-Setup-<version>.exe`

- Installs per-user — **no admin rights needed**. Creates Start-menu and desktop shortcuts.
- The installer is unsigned, so Windows SmartScreen may warn on first run: click
  **More info → Run anyway**.
- Ships with six built-in strategies and a bundled SPY daily dataset (2015–2024), so
  you can run a backtest immediately. Fetch more data by ticker in-app via Yahoo Finance.

### Your data stays yours

Everything you create — datasets, backtest outputs, and any strategies you write in
the in-app Editor — is stored locally in `%LOCALAPPDATA%\BacktestingSuite`. Your
strategies are never bundled into the app or shared, and they survive updates and
uninstalls.

---

## ✨ What you can do

- **Configure & run backtests**: pick a strategy, tune its parameters, choose a
  position sizer (fixed shares, fixed fractional, or ATR volatility-adjusted), set
  capital, commission, slippage, execution timing, and long/short mode.
- **Explore results interactively**: metric cards (CAGR, Sharpe, Sortino, max
  drawdown, win rate, profit factor), equity vs. benchmark, drawdown and rolling
  return charts, and a full trade log.
- **Stress-test for robustness**: train/test splits with parameter-decay checks,
  walk-forward analysis, Monte Carlo trade-sequence simulations (probability of
  ruin, drawdown VaR), and cost-sensitivity heatmaps.
- **Compare runs**: overlay equity curves and metrics from multiple backtests
  side by side.
- **Write your own strategies**: a built-in Monaco code editor (works offline).
  Subclass `BaseStrategy`, hit *Save & Register*, and your strategy is validated,
  registered, and immediately available for backtesting — numeric parameters become
  editable form fields automatically.
- **Bring your own data**: load local Parquet files or fetch any ticker by symbol.

### Built-in strategies

Buy & Hold · SMA Crossover · EMA Crossover · RSI Mean Reversion · Bollinger Bands
Breakout · MACD Trend Following — all supporting long-only or long/short regimes.

---

## 🏗️ Under the hood

The app is an Electron + React frontend over a Python FastAPI backend that Electron
spawns as a local sidecar (everything runs on your machine; nothing is sent
anywhere). The backend imports the backtesting engine directly:

- **Event-driven execution loop** — bar-by-bar processing that eliminates lookahead
  bias and executes trades on the next bar's open or close.
- **Clean architecture** — strategies, sizers, and execution-cost models are
  swappable modules behind interfaces (`domain/`), with the engine (`backtest/`),
  analytics (`analytics/`), and validation suite (`validation/`) fully decoupled.
- **Single strategy registry** — `strategy_registry.py` is the one source of truth
  for strategies, parameters, and robustness grids across the whole app.

---

## 🔧 Building from source

For contributors, or to build the installer yourself.

**Prerequisites**: Python 3.10+, Node.js 18+.

```powershell
# Engine + backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Run the app in development
cd desktop\frontend
npm install
npm run dev
```

**Build the Windows installer** (from the repo root; requires Windows Developer Mode
for electron-builder's symlink handling):

```powershell
powershell -File desktop\build-installer.ps1
```

Produces `desktop/frontend/release/BacktestingSuite-Setup-<version>.exe`. See
[desktop/README.md](desktop/README.md) for architecture and packaging details.

**Run the test suite**:

```powershell
pytest
```

> **Strategy privacy by design:** only the allowlisted public built-in strategies
> (see `PUBLIC_STRAT_MODULES` in `desktop/backend/BacktestApiServer.spec` and the
> `.gitignore` allowlist) are committed to git or bundled into the installer. Any
> other file dropped into `strat/`, and everything in `user_strategies/`, stays on
> your machine — the build fails hard if private modules or data files leak into
> the bundle.

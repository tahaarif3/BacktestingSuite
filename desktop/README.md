# BacktestingSuite Desktop App

An interactive Electron + React desktop app over the existing event-driven
backtesting engine. A Python **FastAPI** backend imports the suite directly and
is spawned by Electron as a local sidecar.

```
desktop/
  backend/    FastAPI service (imports data/ backtest/ analytics/ validation/ + strategy_registry)
  frontend/   Electron + React + Vite + TypeScript UI (Plotly charts)
```

## Prerequisites

- Python 3.10+ virtualenv at the repo root (`.venv`) with `requirements.txt` installed.
- Node.js 18+ / npm.

## Develop

From `desktop/frontend`:

```bash
npm install
npm run dev
```

`npm run dev` starts Vite (renderer) and Electron together. Electron finds a free
port, launches the backend with the repo's `.venv` Python, waits for `/health`,
then opens the window.

To run the backend on its own (useful for API testing or a browser-based UI):

```bash
# from the repo root
.venv/Scripts/python -m desktop.backend.main --port 8765
```

The renderer falls back to `http://127.0.0.1:8765` when not launched by Electron.

## Features

- **Configure** (sidebar): data source (local Parquet *or* yfinance ticker fetch),
  strategy + dynamic parameters, sizer, capital, costs, timing, long/short.
- **Results**: metric cards, equity vs. benchmark, drawdown, rolling returns, trade log.
- **Robustness**: train/test split, walk-forward, Monte Carlo, cost-sensitivity heatmap.
- **Compare**: overlaid equity curves + side-by-side metrics for multiple runs.
- **Editor**: in-app Monaco code editor (bundled locally, works offline) for authoring
  custom strategies. Code is validated on synthetic bars before saving (must compile,
  contain a concrete `IStrategy` subclass constructible with defaults, and return
  bar-aligned signals), then written to `user_strategies/` and hot-registered through
  the shared `strategy_registry` — it appears in the Configure dropdown immediately.
  Numeric `__init__` defaults become editable fields; a `long_only` parameter enables
  the shorting toggle. In the packaged app, user strategies live in
  `%LOCALAPPDATA%/BacktestingSuite/user_strategies`.

## Package

See `desktop/backend/BacktestApiServer.spec` (PyInstaller) and the `build` block in
`frontend/package.json` (electron-builder):

```bash
# 1) build the backend binary (from repo root)
.venv/Scripts/pyinstaller desktop/backend/BacktestApiServer.spec
# 2) build + package the app (from desktop/frontend)
npm run dist
```

# PyInstaller spec for the BacktestingSuite FastAPI backend (onedir).
# Build from the repo root:
#     .venv/Scripts/pyinstaller desktop/backend/BacktestApiServer.spec
#
# Produces desktop/backend/dist/BacktestApiServer/ which electron-builder ships
# under resources/backend (see frontend/package.json).

import os
from PyInstaller.utils.hooks import collect_submodules, collect_all

REPO_ROOT = os.path.abspath(os.getcwd())

hiddenimports = []
for pkg in ["data", "backtest", "analytics", "validation", "domain", "strat", "presentation"]:
    hiddenimports += collect_submodules(pkg)
hiddenimports += ["strategy_registry", "uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
                   "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
                   "uvicorn.lifespan.on"]

datas = []
binaries = []
for pkg in ["yfinance", "pyarrow"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Ship the default SPY dataset so a fresh install can run immediately.
_default_data = os.path.join(REPO_ROOT, "data", "spy_daily_yfinance.parquet")
if os.path.exists(_default_data):
    datas.append((_default_data, "data"))

a = Analysis(
    [os.path.join(REPO_ROOT, "desktop", "backend", "main.py")],
    pathex=[REPO_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BacktestApiServer",
    console=True,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="BacktestApiServer",
)

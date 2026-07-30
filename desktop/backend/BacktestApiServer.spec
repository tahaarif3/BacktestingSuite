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
for pkg in ["data", "backtest", "analytics", "validation", "domain", "presentation", "options",
            "portfolio_backtest", "dca"]:
    hiddenimports += collect_submodules(pkg)

# strat/ is deliberately NOT swept with collect_submodules: it may contain
# private strategy files that must never ship in a public build. Only this
# allowlist of public-safe built-ins is bundled.
PUBLIC_STRAT_MODULES = [
    "strat",
    "strat.base",
    "strat.rs_breakout",
]
hiddenimports += PUBLIC_STRAT_MODULES
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

# --- Public-safety assertions: fail the build if private content leaks in. ---
def _is_repo_module(src):
    p = (src or "").replace("\\", "/")
    return p.startswith(REPO_ROOT.replace("\\", "/")) and "/.venv/" not in p and "site-packages" not in p


_strat_leaks = [
    n for (n, _, _) in a.pure
    if (n == "strat" or n.startswith("strat.")) and n not in PUBLIC_STRAT_MODULES
]
# Only repo-local modules are checked: stdlib `secrets` and third-party
# `*._private` internals are legitimate and must not trip the guard.
_private_leaks = [
    n for (n, src, _) in a.pure
    if _is_repo_module(src)
    and ("secret" in n.lower() or "private" in n.lower() or n.startswith("user_strategies"))
]
assert not (_strat_leaks or _private_leaks), (
    f"PRIVATE MODULES LEAKED INTO BUNDLE: {_strat_leaks + _private_leaks}"
)

_data_leaks = [
    d for d in a.datas
    if d[0].replace("\\", "/").lower().endswith((".parquet", ".json"))
    and "spy_daily_yfinance" not in d[0]
    and "site-packages" not in d[1].replace("\\", "/")
]
assert not _data_leaks, f"UNEXPECTED DATA FILES IN BUNDLE: {_data_leaks}"

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

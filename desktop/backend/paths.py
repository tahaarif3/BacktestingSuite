"""Resolves the backtesting suite's repo root / data dirs and puts the suite on
sys.path.

Dev: everything lives under the repo root next to this file.
Frozen (PyInstaller onedir): suite code is bundled next to the executable, while
data and output go to a user-writable dir (installed apps can't write under
Program Files). The bundled default SPY dataset is seeded there on first run.
"""

import os
import shutil
import sys

if getattr(sys, "frozen", False):
    _BUNDLE_DIR = os.path.dirname(sys.executable)
    REPO_ROOT = os.environ.get("BACKTEST_REPO_ROOT", _BUNDLE_DIR)

    _USER_BASE = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "BacktestingSuite"
    )
    DATA_DIR = os.path.join(_USER_BASE, "data")
    OUTPUT_DIR = os.path.join(_USER_BASE, "output")
    SESSIONS_DIR = os.path.join(_USER_BASE, "replay_sessions")
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(SESSIONS_DIR, exist_ok=True)

    # Seed the default dataset from the bundle if the user dir is empty.
    # PyInstaller unpacks bundled datas under sys._MEIPASS (the _internal dir in
    # onedir mode); fall back to the executable directory just in case.
    _bundled_data = os.path.join(getattr(sys, "_MEIPASS", _BUNDLE_DIR), "data")
    if os.path.isdir(_bundled_data):
        for fname in os.listdir(_bundled_data):
            dest = os.path.join(DATA_DIR, fname)
            if not os.path.exists(dest):
                try:
                    shutil.copy2(os.path.join(_bundled_data, fname), dest)
                except OSError:
                    pass
else:
    REPO_ROOT = os.environ.get(
        "BACKTEST_REPO_ROOT",
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")),
    )
    DATA_DIR = os.path.join(REPO_ROOT, "data")
    OUTPUT_DIR = os.path.join(REPO_ROOT, "output")
    SESSIONS_DIR = os.path.join(OUTPUT_DIR, "replay_sessions")
    os.makedirs(SESSIONS_DIR, exist_ok=True)

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

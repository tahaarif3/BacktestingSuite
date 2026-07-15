"""Save, validate, list, and delete user-authored strategies (in-app editor).

Code is validated BEFORE it is written: it must compile, import, contain at
least one concrete IStrategy subclass constructible with no arguments, and
produce a bar-aligned list of signals on synthetic data. Only then is it saved
to USER_STRATEGIES_DIR and registered via the shared strategy registry.

Executing user code is inherent to this feature; the app is a local,
single-user desktop tool, so the author and the executor are the same person.
"""

import math
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta
from typing import List

from domain.models import Bar
from strategy_registry import (
    USER_STRATEGIES_DIR,
    load_strategy_classes_from_source,
    refresh_user_strategies,
)

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

TEMPLATE = '''"""Custom strategy.

Contract (same as the built-in strategies):
  * generate_signals(bars) receives a list of Bar objects
    (bar.open / high / low / close / volume, bar.timestamp) and must return a
    list of floats aligned 1:1 with the bars.
  * Signal values: 1.0 = long, 0.0 = flat, -1.0 = short.
  * Every __init__ parameter needs a default value; numeric ones (int/float)
    automatically become editable fields in the Configure panel. Including a
    `long_only: bool = True` parameter enables the "Allow shorting" toggle
    (use self._flat_value() for the not-long signal, as below).
"""

import numpy as np
import pandas as pd

from strat.base import BaseStrategy


class MyStrategy(BaseStrategy):
    """Momentum example: long when the N-bar return is positive."""

    def __init__(self, lookback: int = 20, long_only: bool = True):
        self.lookback = int(lookback)
        self.long_only = long_only

    def generate_signals(self, bars):
        closes = pd.Series([b.close for b in bars], dtype=float)
        momentum = closes.pct_change(self.lookback)
        signals = np.where(momentum > 0, 1.0, self._flat_value())
        signals[: self.lookback] = 0.0  # warm-up: stay flat
        return [float(s) for s in signals]
'''


def _stem(filename: str) -> str:
    stem = filename[:-3] if filename.endswith(".py") else filename
    if not _NAME_RE.match(stem):
        raise ValueError(
            "Filename must start with a letter and contain only letters, digits, "
            "and underscores (e.g. my_strategy)."
        )
    return stem


def _synthetic_bars(n: int = 80) -> List[Bar]:
    """Deterministic wavy-uptrend bars so crossovers/momentum flips occur."""
    bars = []
    t0 = datetime(2020, 1, 1)
    price = 100.0
    for i in range(n):
        price *= 1.0 + 0.002 * math.sin(i / 5.0) + 0.0005
        bars.append(
            Bar(t0 + timedelta(days=i), price * 0.999, price * 1.01, price * 0.99, price, 1e6)
        )
    return bars


def _validate(stem: str, code: str) -> None:
    """Raise ValueError with a user-facing message if the code is not a valid strategy."""
    try:
        compile(code, f"{stem}.py", "exec")
    except SyntaxError as e:
        raise ValueError(f"Syntax error on line {e.lineno}: {e.msg}")

    fd, tmp_path = tempfile.mkstemp(suffix=".py", text=True)
    module_name = f"user_validation_{stem}"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            classes = load_strategy_classes_from_source(module_name, tmp_path)
        except Exception as e:
            raise ValueError(f"Import failed: {e}")
    finally:
        sys.modules.pop(module_name, None)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not classes:
        raise ValueError(
            "No concrete IStrategy subclass found. Subclass strat.base.BaseStrategy "
            "and implement generate_signals(bars)."
        )

    bars = _synthetic_bars()
    for cls in classes:
        try:
            instance = cls()
        except TypeError as e:
            raise ValueError(
                f"{cls.__name__} must be constructible with no arguments — give every "
                f"__init__ parameter a default value. ({e})"
            )
        try:
            signals = instance.generate_signals(bars)
        except Exception as e:
            raise ValueError(f"{cls.__name__}.generate_signals crashed on test data: {e}")
        if not isinstance(signals, list) or len(signals) != len(bars):
            got = len(signals) if hasattr(signals, "__len__") else "?"
            raise ValueError(
                f"{cls.__name__}.generate_signals must return a list of floats aligned "
                f"with the input bars (got length {got}, expected {len(bars)})."
            )


def list_files() -> List[str]:
    if not os.path.isdir(USER_STRATEGIES_DIR):
        return []
    return sorted(f for f in os.listdir(USER_STRATEGIES_DIR) if f.endswith(".py"))


def get_code(filename: str) -> str:
    path = os.path.join(USER_STRATEGIES_DIR, _stem(filename) + ".py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"User strategy not found: {filename}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def save(filename: str, code: str) -> List[str]:
    """Validate and persist the strategy, then refresh the registry.

    Returns the ids of all registered user strategies.
    """
    stem = _stem(filename)
    _validate(stem, code)

    os.makedirs(USER_STRATEGIES_DIR, exist_ok=True)
    with open(os.path.join(USER_STRATEGIES_DIR, stem + ".py"), "w", encoding="utf-8") as f:
        f.write(code)
    return refresh_user_strategies()


def delete(filename: str) -> List[str]:
    path = os.path.join(USER_STRATEGIES_DIR, _stem(filename) + ".py")
    if not os.path.exists(path):
        raise FileNotFoundError(f"User strategy not found: {filename}")
    os.remove(path)
    return refresh_user_strategies()

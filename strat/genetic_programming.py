"""Genetic-programming strategy loader.

The original evolved artifact (``champion_gp.json``) is gitignored and was not in
the clone, so this reconstruction can only *interpret* a champion file when one is
supplied. Without the JSON the strategy is hidden in the desktop app (see the
registry). It still honours the contract exercised by test/test_gp.py:
raising ``FileNotFoundError`` for a missing path, exposing ``tree``,
``volatility_threshold`` and ``deadband``, and enforcing a 60-bar warm-up.

The tree grammar is interpreted defensively: function nodes are ``{"op": name,
"children": [...]}`` (or ``{"func": ...}``) and terminals are either a feature
name string or a numeric constant. Because the original grammar is unavailable,
signals produced from a foreign champion file are best-effort, not guaranteed to
reproduce the original results.
"""

import json
import os
from typing import Any, List

import numpy as np
import pandas as pd

from domain.models import Bar
from strat.base import BaseStrategy

WARMUP_BARS = 60

_BINARY_OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b if abs(b) > 1e-12 else 0.0,
    "max": max,
    "min": min,
    "gt": lambda a, b: 1.0 if a > b else 0.0,
    "lt": lambda a, b: 1.0 if a < b else 0.0,
}
_UNARY_OPS = {
    "neg": lambda a: -a,
    "abs": abs,
    "sign": lambda a: float(np.sign(a)),
    "tanh": lambda a: float(np.tanh(a)),
}


class GeneticProgrammingStrategy(BaseStrategy):
    def __init__(self, json_path: str = "champion_gp.json"):
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"Genetic programming champion file not found: {json_path}")

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.tree: Any = data.get("tree", [])
        self.volatility_threshold: float = float(data.get("volatility_threshold", 0.0035))
        self.deadband: float = float(data.get("deadband", 0.15))
        self.long_only = bool(data.get("long_only", False))

    def _features(self, closes: pd.Series) -> pd.DataFrame:
        returns = closes.pct_change().fillna(0.0)
        return pd.DataFrame(
            {
                "close": closes,
                "return": returns,
                "momentum": closes.pct_change(10).fillna(0.0),
                "volatility": returns.rolling(20).std().fillna(0.0),
                "sma_ratio": (closes / closes.rolling(20).mean()).fillna(1.0) - 1.0,
            }
        )

    def _evaluate(self, node: Any, row: pd.Series) -> float:
        if isinstance(node, (int, float)):
            return float(node)
        if isinstance(node, str):
            return float(row[node]) if node in row.index else 0.0
        if isinstance(node, dict):
            op = node.get("op") or node.get("func") or node.get("type")
            children = node.get("children") or node.get("args") or []
            vals = [self._evaluate(c, row) for c in children]
            if op in _BINARY_OPS and len(vals) >= 2:
                return float(_BINARY_OPS[op](vals[0], vals[1]))
            if op in _UNARY_OPS and len(vals) >= 1:
                return float(_UNARY_OPS[op](vals[0]))
            return vals[0] if vals else 0.0
        if isinstance(node, list) and node:
            # Prefix notation: [op, arg1, arg2, ...]
            return self._evaluate({"op": node[0], "children": node[1:]}, row)
        return 0.0

    def generate_signals(self, bars: List[Bar]) -> List[float]:
        closes = self._closes(bars)
        features = self._features(closes)
        vol = features["volatility"]

        signals: List[float] = []
        for i in range(len(bars)):
            if i < WARMUP_BARS:
                signals.append(0.0)
                continue

            raw = self._evaluate(self.tree, features.iloc[i]) if self.tree else 0.0

            # Volatility filter: stay flat in low-volatility regimes.
            if vol.iloc[i] < self.volatility_threshold:
                signals.append(0.0)
                continue

            if raw > self.deadband:
                signals.append(1.0)
            elif raw < -self.deadband:
                signals.append(0.0 if self.long_only else -1.0)
            else:
                signals.append(0.0)

        return signals

"""Single source of truth for strategies, their parameters, and sizers.

Consumed by both cli.py and the desktop backend (desktop/backend) so the
command line, the GUI's dynamic config form, and the robustness grids never
drift apart. Adding a strategy here makes it available everywhere.
"""

import importlib
import importlib.util
import inspect
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from domain.interfaces import IStrategy
from backtest.position_sizing import (
    ATRPercentRiskSizer,
    FixedSharesSizer,
    FixedFractionalSizer,
    VolatilityBasedSizer,
)


def _try_import(module: str, clsname: str):
    """Import a built-in strategy class, or None if its module is absent.

    strat/ may be partially populated (private strategies are gitignored), so
    each built-in registers only when its module is actually importable.
    """
    try:
        return getattr(importlib.import_module(module), clsname)
    except Exception:
        return None


RSBreakoutStrategy = _try_import("strat.rs_breakout", "RSBreakoutStrategy")


@dataclass
class ParamSpec:
    """Describes one tunable strategy parameter for the config form."""

    name: str            # kwarg passed to the strategy constructor
    label: str
    type: str            # "int" | "float"
    default: Any
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "step": self.step,
        }


@dataclass
class StrategySpec:
    id: str
    name: str
    cls: Type[IStrategy]
    params: List[ParamSpec] = field(default_factory=list)
    supports_short: bool = False
    # Grid used by walk-forward / grid-search robustness checks.
    wfa_grid: Dict[str, List[Any]] = field(default_factory=dict)
    # When set, the strategy is available only if this file exists (e.g. GP champion).
    requires_file: Optional[str] = None
    # True for strategies authored in the desktop app's code editor.
    is_user: bool = False

    def is_available(self) -> bool:
        if self.requires_file is None:
            return True
        return os.path.exists(self.requires_file)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "params": [p.to_dict() for p in self.params],
            "supports_short": self.supports_short,
            "available": self.is_available(),
            "is_user": self.is_user,
        }


# --- Strategy definitions -------------------------------------------------

STRATEGIES: Dict[str, StrategySpec] = {}


def _register(spec: StrategySpec) -> None:
    """Add a built-in spec, skipping those whose strat module wasn't importable."""
    if spec.cls is not None:
        STRATEGIES[spec.id] = spec


_register(
    StrategySpec(
        id="rs_breakout",
        name="Relative-Strength Breakout",
        cls=RSBreakoutStrategy,
        params=[
            ParamSpec("trend_ma", "Trend MA (bars)", "int", 90, 20, 250, 1),
            ParamSpec("slope_lookback", "MA Slope Lookback", "int", 10, 1, 60, 1),
            ParamSpec("rs_lookback", "Rel-Strength Lookback", "int", 20, 2, 120, 1),
            ParamSpec("rs_edge", "Rel-Strength Edge", "float", 0.0, 0.0, 0.1, 0.005),
            ParamSpec("gap_edge", "Overnight-Gap Edge", "float", 0.0, 0.0, 0.05, 0.001),
            ParamSpec("breakout_window", "Breakout Lookback", "int", 20, 3, 120, 1),
            ParamSpec("range_mult", "Momentum Range x ATR", "float", 1.2, 0.5, 4.0, 0.1),
            ParamSpec("atr_window", "ATR Window", "int", 14, 2, 60, 1),
            ParamSpec("vol_mult", "Volume Spike x Avg", "float", 1.5, 1.0, 5.0, 0.1),
            ParamSpec("vol_window", "Volume Avg Window", "int", 20, 2, 120, 1),
            ParamSpec("entry_window_bars", "Entry Bars After Open", "int", 3, 1, 40, 1),
            ParamSpec("stop_pct", "Stop %", "float", 0.02, 0.0, 0.2, 0.005),
            ParamSpec("take_pct", "Take-Profit %", "float", 0.06, 0.0, 0.5, 0.01),
            ParamSpec("max_hold_bars", "Max Hold (0=off)", "int", 0, 0, 500, 1),
        ],
        supports_short=False,
        wfa_grid={"breakout_window": [10, 20, 40], "rs_lookback": [10, 20, 40]},
    )
)


# --- Sizer definitions ----------------------------------------------------

@dataclass
class SizerSpec:
    id: str
    name: str
    value_label: str
    default_value: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "value_label": self.value_label,
            "default_value": self.default_value,
        }


SIZERS: Dict[str, SizerSpec] = {
    "fixed_shares": SizerSpec("fixed_shares", "Fixed Shares", "Shares per trade", 100),
    "fixed_fractional": SizerSpec("fixed_fractional", "Fixed Fractional", "Fraction of equity", 0.5),
    "volatility": SizerSpec("volatility", "Volatility Adjusted", "Risk per trade ($)", 500),
    "atr_percent_risk": SizerSpec(
        "atr_percent_risk",
        "ATR Risk (2x Stop)",
        "Fraction of equity at risk",
        0.005,
    ),
}


# --- Builders -------------------------------------------------------------

def build_strategy(
    strategy_id: str,
    values: Dict[str, Any],
    allow_short: bool = False,
    gp_json: str = "champion_gp.json",
):
    """Instantiate a strategy and return (instance, resolved_params_dict).

    ``values`` holds the raw parameter values from the CLI/GUI; unknown keys are
    ignored and missing keys fall back to the registry default.
    """
    spec = STRATEGIES.get(strategy_id)
    if spec is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    if strategy_id == "gp":
        params = {"json_path": values.get("json_path", gp_json)}
        return spec.cls(**params), params

    params: Dict[str, Any] = {}
    for p in spec.params:
        raw = values.get(p.name, p.default)
        params[p.name] = int(raw) if p.type == "int" else float(raw)

    if spec.supports_short:
        params["long_only"] = not allow_short

    return spec.cls(**params), params


def build_sizer(sizer_id: str, value: float, initial_capital: float):
    """Instantiate a position sizer from its id and single value."""
    if sizer_id == "fixed_shares":
        return FixedSharesSizer(fixed_shares=int(value))
    if sizer_id == "fixed_fractional":
        return FixedFractionalSizer(fraction=float(value), initial_capital=initial_capital)
    if sizer_id == "volatility":
        return VolatilityBasedSizer(target_risk_per_trade=float(value), window=20)
    if sizer_id == "atr_percent_risk":
        return ATRPercentRiskSizer(
            risk_fraction=float(value),
            window=14,
            stop_multiple=2.0,
        )
    raise ValueError(f"Unknown sizer: {sizer_id}")


def list_strategies(include_unavailable: bool = False) -> List[Dict[str, Any]]:
    return [
        s.to_dict()
        for s in STRATEGIES.values()
        if include_unavailable or s.is_available()
    ]


def list_sizers() -> List[Dict[str, Any]]:
    return [s.to_dict() for s in SIZERS.values()]


# --- User strategies (authored in the desktop app's code editor) -----------

if getattr(sys, "frozen", False):
    # Frozen app: user strategies live in the writable per-user dir.
    USER_STRATEGIES_DIR = os.path.join(
        os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
        "BacktestingSuite",
        "user_strategies",
    )
else:
    USER_STRATEGIES_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "user_strategies"
    )


def _introspect_params(cls: Type) -> Tuple[List[ParamSpec], bool]:
    """Derive ParamSpecs from a strategy's __init__ numeric defaults.

    A ``long_only`` keyword marks the strategy as short-capable (the engine
    convention used by the built-in strategies).
    """
    params: List[ParamSpec] = []
    supports_short = False
    for name, p in inspect.signature(cls.__init__).parameters.items():
        if name == "self":
            continue
        if name == "long_only":
            supports_short = True
            continue
        default = p.default
        if default is inspect.Parameter.empty or isinstance(default, bool):
            continue
        if isinstance(default, int):
            params.append(ParamSpec(name, name.replace("_", " ").title(), "int", default))
        elif isinstance(default, float):
            params.append(ParamSpec(name, name.replace("_", " ").title(), "float", default))
    return params, supports_short


def load_strategy_classes_from_source(module_name: str, filepath: str) -> List[Type[IStrategy]]:
    """Import a strategy source file and return its concrete IStrategy subclasses."""
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    classes = []
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if (
            issubclass(cls, IStrategy)
            and not inspect.isabstract(cls)
            and cls.__module__ == module_name
        ):
            classes.append(cls)
    return classes


def refresh_user_strategies() -> List[str]:
    """(Re)load ``*.py`` files from USER_STRATEGIES_DIR into the registry.

    Returns the ids of the registered user strategies. Files that fail to
    import are skipped (the editor's save endpoint validates before writing,
    so this mainly guards hand-copied files).
    """
    for key in [k for k, s in STRATEGIES.items() if s.is_user]:
        del STRATEGIES[key]

    loaded: List[str] = []
    if not os.path.isdir(USER_STRATEGIES_DIR):
        return loaded

    for fname in sorted(os.listdir(USER_STRATEGIES_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        stem = fname[:-3]
        path = os.path.join(USER_STRATEGIES_DIR, fname)
        try:
            classes = load_strategy_classes_from_source(f"user_strategies_{stem}", path)
        except Exception as e:
            print(f"[registry] Skipping user strategy {fname}: {e}")
            continue
        for cls in classes:
            params, supports_short = _introspect_params(cls)
            sid = f"user_{stem}" if len(classes) == 1 else f"user_{stem}_{cls.__name__.lower()}"
            STRATEGIES[sid] = StrategySpec(
                id=sid,
                name=f"{cls.__name__} (user)",
                cls=cls,
                params=params,
                supports_short=supports_short,
                is_user=True,
            )
            loaded.append(sid)
    return loaded


refresh_user_strategies()

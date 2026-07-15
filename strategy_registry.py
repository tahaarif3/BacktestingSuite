"""Single source of truth for strategies, their parameters, and sizers.

Consumed by both cli.py and the desktop backend (desktop/backend) so the
command line, the GUI's dynamic config form, and the robustness grids never
drift apart. Adding a strategy here makes it available everywhere.
"""

import importlib.util
import inspect
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from domain.interfaces import IStrategy
from backtest.position_sizing import (
    FixedSharesSizer,
    FixedFractionalSizer,
    VolatilityBasedSizer,
)

from strat.buy_and_hold import BuyAndHoldStrategy
from strat.sma_crossover import SMACrossoverStrategy
from strat.ema_crossover import EMACrossoverStrategy
from strat.rsi_mean_reversion import RSIMeanReversionStrategy
from strat.bollinger_bands import BollingerBandsStrategy
from strat.macd import MACDStrategy
from strat.genetic_programming import GeneticProgrammingStrategy

DEFAULT_GP_JSON = "champion_gp.json"


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

STRATEGIES: Dict[str, StrategySpec] = {
    "buy_and_hold": StrategySpec(
        id="buy_and_hold",
        name="Buy & Hold",
        cls=BuyAndHoldStrategy,
        params=[],
        supports_short=False,
    ),
    "sma": StrategySpec(
        id="sma",
        name="SMA Crossover",
        cls=SMACrossoverStrategy,
        params=[
            ParamSpec("fast_window", "Fast Window", "int", 10, 2, 200, 1),
            ParamSpec("slow_window", "Slow Window", "int", 50, 3, 400, 1),
        ],
        supports_short=True,
        wfa_grid={"fast_window": [5, 10, 20], "slow_window": [30, 50, 70]},
    ),
    "ema": StrategySpec(
        id="ema",
        name="EMA Crossover",
        cls=EMACrossoverStrategy,
        params=[
            ParamSpec("fast_window", "Fast Window", "int", 10, 2, 200, 1),
            ParamSpec("slow_window", "Slow Window", "int", 50, 3, 400, 1),
        ],
        supports_short=True,
        wfa_grid={"fast_window": [5, 10, 20], "slow_window": [30, 50, 70]},
    ),
    "rsi": StrategySpec(
        id="rsi",
        name="RSI Mean Reversion",
        cls=RSIMeanReversionStrategy,
        params=[
            ParamSpec("window", "RSI Window", "int", 14, 2, 100, 1),
            ParamSpec("oversold", "Oversold", "float", 30.0, 1, 50, 1),
            ParamSpec("overbought", "Overbought", "float", 70.0, 50, 99, 1),
            ParamSpec("exit_level", "Exit Level", "float", 50.0, 1, 99, 1),
        ],
        supports_short=True,
        wfa_grid={"window": [10, 14, 20], "oversold": [25, 30, 35], "overbought": [65, 70, 75]},
    ),
    "bb": StrategySpec(
        id="bb",
        name="Bollinger Bands Breakout",
        cls=BollingerBandsStrategy,
        params=[
            ParamSpec("window", "Window", "int", 20, 3, 200, 1),
            ParamSpec("num_std", "Std Dev Multiplier", "float", 2.0, 0.5, 4.0, 0.1),
        ],
        supports_short=True,
        wfa_grid={"window": [15, 20, 25], "num_std": [1.5, 2.0, 2.5]},
    ),
    "macd": StrategySpec(
        id="macd",
        name="MACD Trend Following",
        cls=MACDStrategy,
        params=[
            ParamSpec("fast_window", "Fast EMA", "int", 12, 2, 100, 1),
            ParamSpec("slow_window", "Slow EMA", "int", 26, 3, 200, 1),
            ParamSpec("signal_window", "Signal", "int", 9, 2, 100, 1),
        ],
        supports_short=True,
        wfa_grid={"fast_window": [10, 12, 15], "slow_window": [22, 26, 30], "signal_window": [7, 9, 11]},
    ),
    "gp": StrategySpec(
        id="gp",
        name="Genetic Programming (Champion)",
        cls=GeneticProgrammingStrategy,
        params=[],
        supports_short=False,
        requires_file=DEFAULT_GP_JSON,
    ),
}


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
}


# --- Builders -------------------------------------------------------------

def build_strategy(
    strategy_id: str,
    values: Dict[str, Any],
    allow_short: bool = False,
    gp_json: str = DEFAULT_GP_JSON,
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

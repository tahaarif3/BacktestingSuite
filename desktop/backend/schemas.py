from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    source: str = "file"                 # "file" | "ticker"
    file: Optional[str] = None           # parquet filename under data/
    ticker: Optional[str] = None
    start: Optional[str] = None          # YYYY-MM-DD
    end: Optional[str] = None
    interval: str = "1d"


class OptionStructureConfig(BaseModel):
    """Mirrors options.structures.StructureSpec — the template used to open a
    structure (in a backtest or a replay session)."""

    structure_type: str = "bear_call_spread"
    selection: Literal["delta", "pct_otm", "absolute"] = "delta"
    short_delta: float = 0.30
    pct_otm: float = 0.05
    width: float = 5.0
    strikes: Optional[List[float]] = None
    dte_bars: int = 30
    contracts: int = 1
    grid_spacing: float = 5.0


class VolModelConfig(BaseModel):
    """Black-Scholes synthetic-pricing knobs (see options.volatility)."""

    risk_free_rate: float = 0.04
    iv_window: int = 20
    iv_multiplier: float = 1.0
    iv_override: Optional[float] = None
    iv_floor: float = 0.05
    iv_cap: float = 3.0
    margin_policy: Literal["defined_risk", "reg_t"] = "defined_risk"


class BacktestConfig(BaseModel):
    strategy: str = "sma"
    params: Dict[str, Any] = Field(default_factory=dict)
    short: bool = False

    sizer: str = "fixed_fractional"
    sizer_value: float = 0.5

    capital: float = 100000.0
    slippage_pct: float = 0.0002
    commission_pct: float = 0.0005
    commission_per_share: float = 0.0
    min_trade_shares: float = 1e-8
    timing: str = "next_open"            # "next_open" | "next_close"

    # Trade mode: "equity" (shares, default) or "options" (Black-Scholes synthetic).
    mode: Literal["equity", "options"] = "equity"
    options: Optional[OptionStructureConfig] = None
    vol: Optional[VolModelConfig] = None

    data: DataConfig = Field(default_factory=DataConfig)


class FetchRequest(BaseModel):
    ticker: str
    start: str
    end: str
    interval: str = "1d"
    merge: bool = True      # merge into an existing cache file rather than clobber it
    refresh: bool = False   # force refetch even if the range looks cached


class RobustnessRequest(BaseModel):
    config: BacktestConfig
    tests: List[str] = Field(
        default_factory=lambda: ["train_test", "walk_forward", "monte_carlo", "cost_sensitivity"]
    )
    mc_iterations: int = 1000


class CompareRequest(BaseModel):
    runs: List[BacktestConfig]
    labels: Optional[List[str]] = None


class SaveStrategyRequest(BaseModel):
    filename: str
    code: str


# --- Replay / manual-trading -----------------------------------------------


class ReplaySessionConfig(BaseModel):
    """Mirrors BacktestConfig (so run_engine can be reused verbatim) plus
    replay-only knobs."""

    strategy: str = "sma"
    params: Dict[str, Any] = Field(default_factory=dict)
    short: bool = False

    sizer: str = "fixed_fractional"
    sizer_value: float = 0.5

    capital: float = 100000.0
    slippage_pct: float = 0.0002
    commission_pct: float = 0.0005
    commission_per_share: float = 0.0
    min_trade_shares: float = 1e-8
    timing: Literal["next_open", "next_close"] = "next_open"

    data: DataConfig = Field(default_factory=DataConfig)

    # Replay-only
    warmup_bars: int = 200                                       # context bars before the cursor starts
    signal_mode: Literal["batch", "causal"] = "batch"
    margin_policy: Literal["cash_only", "unlimited"] = "cash_only"
    whole_shares: bool = False
    label: Optional[str] = None

    # Trade mode (see BacktestConfig).
    mode: Literal["equity", "options"] = "equity"
    options: Optional[OptionStructureConfig] = None
    vol: Optional[VolModelConfig] = None

    def to_backtest_config(self) -> "BacktestConfig":
        return BacktestConfig(
            strategy=self.strategy,
            params=self.params,
            short=self.short,
            sizer=self.sizer,
            sizer_value=self.sizer_value,
            capital=self.capital,
            slippage_pct=self.slippage_pct,
            commission_pct=self.commission_pct,
            commission_per_share=self.commission_per_share,
            min_trade_shares=self.min_trade_shares,
            timing=self.timing,
            mode=self.mode,
            options=self.options,
            vol=self.vol,
            data=self.data,
        )


class CreateReplaySessionRequest(BaseModel):
    config: ReplaySessionConfig = Field(default_factory=ReplaySessionConfig)


class ReplayOrderRequest(BaseModel):
    bar_index: int
    side: Literal["buy", "sell", "close"]
    qty_mode: Literal["shares", "fraction", "algo", "algo_scaled"] = "shares"
    qty_value: float = 0.0
    note: str = ""


class ReplayOptionOrderRequest(BaseModel):
    """Open a structure (carrying its template) or close an existing one."""

    bar_index: int
    action: Literal["open", "close"] = "open"
    structure: Optional[OptionStructureConfig] = None   # required for "open"
    target_structure_id: Optional[str] = None           # required for "close"
    note: str = ""


class OptionPreviewRequest(BaseModel):
    """Dry-run: price a structure template against a session bar (no order placed)."""

    bar_index: int
    structure: OptionStructureConfig = Field(default_factory=OptionStructureConfig)


class SeekRequest(BaseModel):
    to_index: int


class StepRequest(BaseModel):
    mode: Literal["bar", "signal", "n_bars"] = "bar"
    n: int = 1


class RewindRequest(BaseModel):
    to_index: int
    confirm_discard_orders: bool = False


class TickerValidateRequest(BaseModel):
    ticker: str
    interval: str = "1d"
    start: Optional[str] = None
    end: Optional[str] = None


class PortfolioSessionConfig(BaseModel):
    """A multi-symbol options portfolio replay (SPY clock + watchlist)."""

    tickers: Optional[List[str]] = None
    start: str
    end: str
    capital: float = 100000.0
    timing: Literal["next_open", "next_close"] = "next_close"
    warmup_bars: int = 120
    refresh: bool = True
    params: Dict[str, Any] = Field(default_factory=dict)
    vol: Optional[VolModelConfig] = None


class CreatePortfolioRequest(BaseModel):
    config: PortfolioSessionConfig


class PortfolioOrderRequest(BaseModel):
    bar_index: int
    symbol: str
    action: Literal["open", "close"] = "open"
    structure: Optional[OptionStructureConfig] = None
    target_structure_id: Optional[str] = None
    note: str = ""


class ScreenRequest(BaseModel):
    """Scan a basket for the RS-Breakout setup. Empty tickers -> default watchlist."""

    tickers: Optional[List[str]] = None
    start: str
    end: str
    interval: str = "1d"
    params: Dict[str, Any] = Field(default_factory=dict)
    window: int = 60          # bars counted as "recent" for entries-in-window
    refresh: bool = True      # re-fetch data + SPY so "armed now" is current

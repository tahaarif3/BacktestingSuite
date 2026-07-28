from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class DataConfig(BaseModel):
    source: str = "file"                 # "file" | "ticker"
    file: Optional[str] = None           # parquet filename under data/
    ticker: Optional[str] = None
    start: Optional[str] = None          # YYYY-MM-DD
    end: Optional[str] = None
    interval: str = "1d"


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

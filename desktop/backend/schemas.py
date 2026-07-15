from typing import Any, Dict, List, Optional

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

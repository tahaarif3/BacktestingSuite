export interface ParamSpec {
  name: string;
  label: string;
  type: "int" | "float";
  default: number;
  min: number | null;
  max: number | null;
  step: number | null;
}

export interface StrategySpec {
  id: string;
  name: string;
  params: ParamSpec[];
  supports_short: boolean;
  available: boolean;
}

export interface SizerSpec {
  id: string;
  name: string;
  value_label: string;
  default_value: number;
}

export interface DataFile {
  name: string;
  rows: number | null;
  start: string | null;
  end: string | null;
}

export interface DataConfig {
  source: "file" | "ticker";
  file?: string;
  ticker?: string;
  start?: string;
  end?: string;
  interval?: string;
}

export interface BacktestConfig {
  strategy: string;
  params: Record<string, number>;
  short: boolean;
  sizer: string;
  sizer_value: number;
  capital: number;
  slippage_pct: number;
  commission_pct: number;
  commission_per_share: number;
  min_trade_shares: number;
  timing: string;
  data: DataConfig;
}

export type Summary = Record<string, number>;

export interface Series {
  dates: string[];
  equity: number[];
  benchmark: number[];
  drawdown: number[];
  rolling_returns: number[];
  close: number[];
}

export interface Trade {
  entry_time: string;
  exit_time: string;
  direction: string;
  size: number;
  entry_price: number;
  exit_price: number;
  pnl_usd: number;
  pnl_pct: number;
  duration_days: number;
}

export interface BacktestResult {
  strategy: string;
  strategy_name: string;
  params: Record<string, unknown>;
  summary: Summary;
  series: Series;
  trades: Trade[];
  initial_equity: number;
  final_equity: number;
}

export interface WalkForwardWindow {
  window: number;
  train_dates: string;
  test_dates: string;
  train_sharpe: number;
  test_sharpe: number;
  best_params: Record<string, unknown>;
}

export interface RobustnessResult {
  strategy: string;
  train_test: {
    is_sharpe: number;
    oos_sharpe: number;
    decay: number;
    warning: boolean;
  } | null;
  walk_forward:
    | {
        wfe?: number;
        avg_is_sharpe?: number;
        oos_sharpe?: number;
        warning?: boolean;
        warning_message?: string;
        windows?: WalkForwardWindow[];
        skipped?: boolean;
        reason?: string;
      }
    | null;
  monte_carlo:
    | {
        probability_of_ruin?: number;
        median_max_drawdown?: number;
        drawdown_95th_percentile?: number;
        median_final_equity?: number;
        final_equity_5th_percentile?: number;
        final_equity_95th_percentile?: number;
        total_trades?: number;
        skipped?: boolean;
        reason?: string;
      }
    | null;
  cost_sensitivity: {
    commission_grid: number[];
    slippage_grid: number[];
    sharpe_matrix: number[][];
  } | null;
}

export interface CompareRun {
  label: string;
  strategy: string;
  params: Record<string, unknown>;
  summary: Summary;
  dates: string[];
  equity: number[];
}

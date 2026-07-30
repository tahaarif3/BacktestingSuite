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

export type TradeMode = "equity" | "options";
export type StrikeMode = "delta" | "pct_otm" | "absolute";

export interface OptionStructureConfig {
  structure_type: string;
  selection: StrikeMode;
  short_delta: number;
  pct_otm: number;
  width: number;
  strikes?: number[] | null;
  dte_bars: number;
  contracts: number;
  grid_spacing: number;
}

export interface VolModelConfig {
  risk_free_rate: number;
  iv_window: number;
  iv_multiplier: number;
  iv_override?: number | null;
  iv_floor: number;
  iv_cap: number;
  margin_policy: "defined_risk" | "reg_t";
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
  mode?: TradeMode;
  options?: OptionStructureConfig | null;
  vol?: VolModelConfig | null;
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

// --- Replay / manual trading ------------------------------------------------

export type SignalValue = -1 | 0 | 1;
export type OrderSide = "buy" | "sell" | "close";
export type QtyMode = "shares" | "fraction" | "algo" | "algo_scaled";

export interface IntervalSpec {
  id: string;
  label: string;
  intraday: boolean;
  max_lookback_days: number | null;
  max_span_days: number | null;
  note: string;
}

export interface TickerInfo {
  ticker: string;
  valid: boolean;
  long_name?: string | null;
  short_name?: string | null;
  exchange?: string | null;
  currency?: string | null;
  timezone?: string | null;
  instrument_type?: string | null;
  first_trade_date?: string | null;
  valid_intervals?: string[];
  range_ok?: boolean;
  range_message?: string | null;
  suggested_start?: string | null;
  suggested_end?: string | null;
}

export interface TickerSearchHit {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  quote_type?: string | null;
}

export interface ReplaySessionConfig {
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
  warmup_bars: number;
  signal_mode?: "batch" | "causal";
  margin_policy?: "cash_only" | "unlimited";
  whole_shares?: boolean;
  label?: string | null;
  mode?: TradeMode;
  options?: OptionStructureConfig | null;
  vol?: VolModelConfig | null;
}

export interface ReplayBars {
  start: number;
  count: number;
  total: number;
  t: (number | string)[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  signal: number[];
}

export interface SignalEvent {
  index: number;
  fill_index: number;
  t: number | string;
  from_signal: number;
  to_signal: number;
  kind: string;
  close: number;
  algo_target_shares: number;
}

export interface ReplayAccount {
  cash: number;
  position: number;
  avg_price: number;
  holdings: number;
  equity: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_return: number;
  total_slippage: number;
  total_commission: number;
  open_trade: {
    direction: string;
    size: number;
    avg_entry_price: number;
    entry_t: number | string | null;
  } | null;
}

export interface ReplayFill {
  order_id: string;
  decision_index: number;
  fill_index: number;
  t: number | string;
  trade_shares: number;
  exec_price: number;
  slippage: number;
  commission: number;
  position_after: number;
  cash_after: number;
  equity_after: number;
  no_op: boolean;
}

export interface ReplayOrderRecord {
  id: string;
  bar_index: number;
  side: OrderSide;
  qty_mode: QtyMode;
  qty_value: number;
  note: string;
  placed_at: string;
}

export interface ReplayState {
  session_id: string;
  mode?: TradeMode;
  cursor: number;
  high_water: number;
  start_index: number;
  total_bars: number;
  at_end: boolean;
  current_signal: number;
  algo_target_shares?: number;
  next_signal_event: SignalEvent | null;
  account?: ReplayAccount;
  orders?: ReplayOrderRecord[];
  fills?: ReplayFill[];
  options_account?: OptionsAccount;
  option_orders?: OptionOrderRecord[];
  option_fills?: OptionFill[];
  equity_tail: number[];
  stale: boolean;
  warnings: string[];
}

export interface CausalityReport {
  causal: boolean;
  first_divergence_index: number | null;
  probes_checked: number[];
}

export interface ReplaySessionResponse {
  session_id: string;
  total_bars: number;
  start_index: number;
  cursor: number;
  instrument: {
    symbol: string;
    interval: string;
    intraday: boolean;
    timezone: string | null;
    long_name: string | null;
    exchange: string | null;
    currency: string | null;
  };
  strategy_name: string;
  params: Record<string, unknown>;
  signal_events: SignalEvent[];
  causality: CausalityReport;
  warnings: string[];
  chunk_size: number;
  bars: ReplayBars | null;
  account?: ReplayAccount;
  mode?: TradeMode;
  options_account?: OptionsAccount;
  options_config?: OptionStructureConfig | null;
}

export interface ReplayOrderRequest {
  bar_index: number;
  side: OrderSide;
  qty_mode: QtyMode;
  qty_value: number;
  note?: string;
}

export interface ReplayOrderResponse {
  accepted: boolean;
  fill: ReplayFill | null;
  state: ReplayState;
}

export interface ReplayTrack {
  summary: Summary;
  series: { dates: (number | string)[]; equity: number[]; benchmark: number[] };
  trades?: Trade[];
  option_trades?: OptionTrade[];
  realized_pnl?: number;
  unrealized_pnl?: number;
}

export interface ReplayScore {
  cursor: number;
  mode?: TradeMode;
  bars_elapsed: number;
  start_index: number;
  user: ReplayTrack;
  algo: ReplayTrack;
  buy_hold: ReplayTrack;
  delta: {
    vs_algo: Record<string, number>;
    vs_buy_hold: Record<string, number>;
  };
  behaviour: {
    signals_shown: number;
    signals_followed: number;
    signals_faded: number;
    signals_ignored: number;
    unprompted_orders: number;
    follow_rate: number;
  };
  fairness: {
    algo_min_cash?: number;
    algo_used_leverage?: boolean;
    user_margin_policy?: string;
    note: string | null;
  };
  warnings: string[];
}

export interface JournalEntry {
  bar_index: number;
  t: number | string;
  close: number;
  signal_from: number | null;
  signal_to: number | null;
  event_kind: string | null;
  algo_target_shares: number | null;
  user_action:
    | { side: OrderSide; qty_mode: QtyMode; qty_value: number; note: string }[]
    | null;
  fill: ReplayFill | null;
  verdict: string;
}

// --- Options ----------------------------------------------------------------

export interface OptionStructureMeta {
  id: string;
  name: string;
  legs: number;
  direction: "bullish" | "bearish" | "neutral";
  defined_risk: boolean;
  net: "debit" | "credit" | "either";
  needs_width: boolean;
}

export interface OptionGreeks {
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  rho?: number;
}

export interface OptionLegView {
  kind: "call" | "put";
  action?: "buy" | "sell";
  strike: number;
  quantity: number;
  dte?: number;
  dte_bars?: number;
  mark: number;
  value?: number;
  iv?: number;
  delta: number;
  theta: number;
  vega: number;
  gamma?: number;
  greeks?: OptionGreeks;
}

export interface PayoffPoint {
  s: number;
  pnl: number;
}

export interface OptionPreview {
  structure: string;
  spot: number;
  iv: number;
  dte: number;
  net_price: number;
  net_is_credit: boolean;
  contracts: number;
  multiplier: number;
  max_profit: number | null;
  max_loss: number | null;
  breakevens: number[];
  greeks: OptionGreeks;
  legs: OptionLegView[];
  payoff: PayoffPoint[];
  warnings: string[];
}

export interface OptionPosition {
  id: string;
  structure_type: string;
  contracts: number;
  open_index: number;
  expiry_index: number;
  dte_bars: number;
  value: number;
  max_risk: number | null;
  breakevens: number[];
  greeks: OptionGreeks;
  legs: OptionLegView[];
}

export interface OptionsAccount {
  mode: "options";
  cash: number;
  equity: number;
  net_liq: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_return: number;
  max_risk: number;
  buying_power_used: number;
  net_delta: number;
  net_gamma: number;
  net_theta: number;
  net_vega: number;
  positions: OptionPosition[];
}

export interface OptionFill {
  order_id: string;
  structure_id: string;
  decision_index: number;
  fill_index: number;
  t: number | string;
  action: "open" | "close" | "expiry";
  structure_type: string;
  spot: number;
  net_cash: number;
  costs: number;
  cash_after: number;
  realized_pnl: number;
}

export interface OptionOrderRecord {
  id: string;
  bar_index: number;
  action: "open" | "close";
  structure_type: string;
  selection: StrikeMode;
  short_delta: number;
  pct_otm: number;
  width: number;
  strikes: number[] | null;
  dte_bars: number;
  contracts: number;
  grid_spacing: number;
  target_structure_id: string | null;
  note: string;
  placed_at: string;
}

export interface OptionOrderRequest {
  bar_index: number;
  action: "open" | "close";
  structure?: OptionStructureConfig;
  target_structure_id?: string;
  note?: string;
}

export interface OptionTrade {
  entry_time: string;
  exit_time: string;
  structure: string;
  contracts: number;
  entry_cash: number;
  exit_cash: number;
  pnl_usd: number;
  pnl_pct: number;
  max_risk: number;
  reason: string;
}

export interface OptionsBacktestResult {
  strategy: string;
  strategy_name: string;
  mode: "options";
  params: Record<string, unknown>;
  options_config: OptionStructureConfig | null;
  summary: Summary;
  series: Series;
  option_trades: OptionTrade[];
  realized_pnl: number;
  unrealized_pnl: number;
  max_risk: number;
  initial_equity: number;
  final_equity: number;
}

// --- Screener ---------------------------------------------------------------

export interface ScreenResult {
  symbol: string;
  file: string;
  bars: number;
  has_reference: boolean;
  armed_now: boolean;
  long_now: boolean;
  fresh_entry: boolean;
  entries_in_window: number;
  total_entries: number;
  last_entry_bars_ago: number | null;
  rs_now: number;
  last_close: number;
  last_date: string | null;
  score: number;
  warning: string | null;
}

export interface ScreenResponse {
  results: ScreenResult[];
  errors: { symbol: string; error: string }[];
  scanned: number;
  window: number;
  as_of: string;
}

export interface OptionsReplayTrack {
  summary: Summary;
  series: { dates: (number | string)[]; equity: number[]; benchmark: number[] };
  option_trades: OptionTrade[];
  realized_pnl: number;
  unrealized_pnl: number;
}

import type {
  BacktestConfig,
  BacktestResult,
  CompareRun,
  DataFile,
  IntervalSpec,
  JournalEntry,
  ReplayBars,
  ReplayOrderRequest,
  ReplayOrderResponse,
  ReplayScore,
  ReplaySessionConfig,
  ReplaySessionResponse,
  ReplayState,
  RobustnessResult,
  SizerSpec,
  StrategySpec,
  TickerInfo,
  TickerSearchHit,
} from "./types";

export type UpdateEvent =
  | { type: "checking" }
  | { type: "available"; version: string }
  | { type: "none" }
  | { type: "progress"; percent: number }
  | { type: "downloaded"; version: string }
  | { type: "error"; message: string };

declare global {
  interface Window {
    backtest?: {
      baseUrl: string;
      appVersion?: string;
      platform?: string;
      onUpdateEvent?: (cb: (e: UpdateEvent) => void) => () => void;
      checkForUpdates?: () => Promise<unknown>;
      installUpdate?: () => Promise<void>;
      reportBug?: () => Promise<void>;
    };
  }
}

// Under Electron the port is injected via preload; fall back to the dev default
// so the UI also works in a plain browser pointed at a running backend.
const BASE = window.backtest?.baseUrl ?? "http://127.0.0.1:8765";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = JSON.parse(detail).detail ?? detail;
    } catch {
      /* keep raw text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: "DELETE" });
  if (!res.ok) {
    let detail = await res.text();
    try {
      detail = JSON.parse(detail).detail ?? detail;
    } catch {
      /* keep raw text */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  baseUrl: BASE,

  getStrategies: () =>
    get<{ strategies: StrategySpec[] }>("/api/strategies").then((r) => r.strategies),

  getSizers: () => get<{ sizers: SizerSpec[] }>("/api/sizers").then((r) => r.sizers),

  listData: () => get<{ files: DataFile[] }>("/api/data/list").then((r) => r.files),

  fetchTicker: (ticker: string, start: string, end: string, interval = "1d") =>
    post<DataFile>("/api/data/fetch", { ticker, start, end, interval }),

  runBacktest: (config: BacktestConfig) => post<BacktestResult>("/api/backtest/run", config),

  runRobustness: (config: BacktestConfig, tests: string[], mcIterations = 1000) =>
    post<RobustnessResult>("/api/robustness/run", {
      config,
      tests,
      mc_iterations: mcIterations,
    }),

  compare: (runs: BacktestConfig[], labels: string[]) =>
    post<{ runs: CompareRun[] }>("/api/compare", { runs, labels }).then((r) => r.runs),

  listUserStrategies: () =>
    get<{ files: string[] }>("/api/user-strategies").then((r) => r.files),

  getUserStrategyTemplate: () =>
    get<{ code: string }>("/api/user-strategies/template").then((r) => r.code),

  getUserStrategy: (name: string) =>
    get<{ name: string; code: string }>(`/api/user-strategies/${name}`),

  saveUserStrategy: (filename: string, code: string) =>
    post<{ ok: boolean; registered: string[] }>("/api/user-strategies", { filename, code }),

  deleteUserStrategy: (name: string) =>
    del<{ ok: boolean; registered: string[] }>(`/api/user-strategies/${name}`),

  reportUrl: `${BASE}/api/backtest/report`,

  // --- Market metadata & ticker lookup ---
  listIntervals: () =>
    get<{ intervals: IntervalSpec[] }>("/api/data/intervals").then((r) => r.intervals),

  validateTicker: (ticker: string, interval = "1d", start?: string, end?: string) =>
    post<TickerInfo>("/api/data/validate", { ticker, interval, start, end }),

  searchTickers: (q: string, limit = 10) =>
    get<{ results: TickerSearchHit[] }>(
      `/api/data/search?q=${encodeURIComponent(q)}&limit=${limit}`
    ).then((r) => r.results),

  // --- Replay / manual trading ---
  createReplaySession: (config: ReplaySessionConfig) =>
    post<ReplaySessionResponse>("/api/replay/sessions", { config }),

  getReplayState: (id: string) =>
    get<ReplayState>(`/api/replay/sessions/${id}`),

  getReplayBars: (id: string, start: number, count: number) =>
    get<ReplayBars>(`/api/replay/sessions/${id}/bars?start=${start}&count=${count}`),

  submitReplayOrder: (id: string, order: ReplayOrderRequest) =>
    post<ReplayOrderResponse>(`/api/replay/sessions/${id}/orders`, order),

  undoReplayOrder: (id: string) =>
    post<ReplayState>(`/api/replay/sessions/${id}/orders/undo`, {}),

  seekReplay: (id: string, toIndex: number) =>
    post<ReplayState>(`/api/replay/sessions/${id}/seek`, { to_index: toIndex }),

  rewindReplay: (id: string, toIndex: number, confirm = false) =>
    post<ReplayState>(`/api/replay/sessions/${id}/rewind`, {
      to_index: toIndex,
      confirm_discard_orders: confirm,
    }),

  resetReplay: (id: string) => post<ReplayState>(`/api/replay/sessions/${id}/reset`, {}),

  scoreReplay: (id: string, upto?: number) =>
    get<ReplayScore>(
      `/api/replay/sessions/${id}/score${upto !== undefined ? `?upto=${upto}` : ""}`
    ),

  getReplayJournal: (id: string, upto?: number) =>
    get<{ entries: JournalEntry[] }>(
      `/api/replay/sessions/${id}/journal${upto !== undefined ? `?upto=${upto}` : ""}`
    ).then((r) => r.entries),

  deleteReplaySession: (id: string) =>
    del<{ ok: boolean }>(`/api/replay/sessions/${id}`),
};

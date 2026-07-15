import type {
  BacktestConfig,
  BacktestResult,
  CompareRun,
  DataFile,
  RobustnessResult,
  SizerSpec,
  StrategySpec,
} from "./types";

declare global {
  interface Window {
    backtest?: { baseUrl: string };
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
};

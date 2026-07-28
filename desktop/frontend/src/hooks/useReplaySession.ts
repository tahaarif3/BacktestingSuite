import { useCallback, useEffect, useReducer, useRef } from "react";
import { api } from "../api";
import type {
  JournalEntry,
  ReplayAccount,
  ReplayBars,
  ReplayFill,
  ReplayOrderRecord,
  ReplayOrderRequest,
  ReplayScore,
  ReplaySessionConfig,
  ReplaySessionResponse,
  ReplayState,
  SignalEvent,
} from "../types";

const LS_KEY = "bt.replay.session";

export interface LoadedBars {
  dates: (number | string)[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  signal: number[];
}

export type Phase = "setup" | "loading" | "running" | "scored" | "error";

export interface ReplaySessionState {
  phase: Phase;
  sessionId: string | null;
  symbol: string;
  interval: string;
  intraday: boolean;
  strategyName: string;
  totalBars: number;
  startIndex: number;
  bars: LoadedBars | null;
  signalEvents: SignalEvent[];
  causalityWarning: string | null;
  account: ReplayAccount | null;
  orders: ReplayOrderRecord[];
  fills: ReplayFill[];
  cursor: number;
  highWater: number;
  capital: number;
  equityTail: number[];
  score: ReplayScore | null;
  journal: JournalEntry[];
  submitting: boolean;
  error: string | null;
  warnings: string[];
}

const initial: ReplaySessionState = {
  phase: "setup",
  sessionId: null,
  symbol: "",
  interval: "1d",
  intraday: false,
  strategyName: "",
  totalBars: 0,
  startIndex: 0,
  bars: null,
  signalEvents: [],
  causalityWarning: null,
  account: null,
  orders: [],
  fills: [],
  cursor: 0,
  highWater: 0,
  capital: 100000,
  equityTail: [],
  score: null,
  journal: [],
  submitting: false,
  error: null,
  warnings: [],
};

type Action =
  | { t: "loading" }
  | { t: "started"; resp: ReplaySessionResponse; bars: LoadedBars }
  | { t: "orderPending" }
  | { t: "stateSynced"; state: ReplayState }
  | { t: "orderErr"; message: string }
  | { t: "scored"; score: ReplayScore; journal: JournalEntry[] }
  | { t: "clearScore" }
  | { t: "error"; message: string }
  | { t: "close" };

function applyState(s: ReplaySessionState, st: ReplayState): ReplaySessionState {
  return {
    ...s,
    account: st.account,
    orders: st.orders,
    fills: st.fills,
    cursor: st.cursor,
    highWater: st.high_water,
    equityTail: st.equity_tail,
    warnings: st.warnings,
    submitting: false,
  };
}

function reducer(s: ReplaySessionState, a: Action): ReplaySessionState {
  switch (a.t) {
    case "loading":
      return { ...initial, phase: "loading" };
    case "started": {
      const causal = a.resp.causality?.causal ?? true;
      return {
        ...s,
        phase: "running",
        sessionId: a.resp.session_id,
        symbol: a.resp.instrument.symbol,
        interval: a.resp.instrument.interval,
        intraday: a.resp.instrument.intraday,
        strategyName: a.resp.strategy_name,
        totalBars: a.resp.total_bars,
        startIndex: a.resp.start_index,
        bars: a.bars,
        signalEvents: a.resp.signal_events,
        causalityWarning: causal
          ? null
          : `This strategy may use future data (first divergence at bar ${a.resp.causality.first_divergence_index}). Its signals may not be realistic.`,
        account: a.resp.account,
        orders: [],
        fills: [],
        cursor: a.resp.cursor,
        highWater: a.resp.start_index,
        capital: a.resp.account.equity,
        equityTail: [a.resp.account.equity],
        score: null,
        journal: [],
        submitting: false,
        error: null,
        warnings: a.resp.warnings,
      };
    }
    case "orderPending":
      return { ...s, submitting: true, error: null };
    case "stateSynced":
      return applyState(s, a.state);
    case "orderErr":
      return { ...s, submitting: false, error: a.message };
    case "scored":
      return { ...s, phase: "scored", score: a.score, journal: a.journal };
    case "clearScore":
      return { ...s, phase: "running", score: null };
    case "error":
      return { ...s, phase: "error", error: a.message, submitting: false };
    case "close":
      return { ...initial };
    default:
      return s;
  }
}

async function loadAllBars(resp: ReplaySessionResponse): Promise<LoadedBars> {
  const empty: LoadedBars = { dates: [], open: [], high: [], low: [], close: [], volume: [], signal: [] };
  const push = (dst: LoadedBars, src: ReplayBars) => {
    dst.dates.push(...src.t);
    dst.open.push(...src.o);
    dst.high.push(...src.h);
    dst.low.push(...src.l);
    dst.close.push(...src.c);
    dst.volume.push(...src.v);
    dst.signal.push(...src.signal);
  };
  if (resp.bars) {
    push(empty, resp.bars);
    return empty;
  }
  // Paged fetch for large (intraday) sessions.
  const chunk = resp.chunk_size || 5000;
  for (let start = 0; start < resp.total_bars; start += chunk) {
    const b = await api.getReplayBars(resp.session_id, start, chunk);
    push(empty, b);
  }
  return empty;
}

export function useReplaySession() {
  const [state, dispatch] = useReducer(reducer, initial);
  const idRef = useRef<string | null>(null);
  idRef.current = state.sessionId;

  const start = useCallback(async (config: ReplaySessionConfig) => {
    dispatch({ t: "loading" });
    try {
      const resp = await api.createReplaySession(config);
      const bars = await loadAllBars(resp);
      // Persist the session descriptor (minus the heavy bar arrays, which we
      // re-fetch from the backend on resume) so a reload restores it fully.
      localStorage.setItem(LS_KEY, JSON.stringify({ sessionId: resp.session_id, resp: { ...resp, bars: null } }));
      dispatch({ t: "started", resp, bars });
    } catch (e) {
      dispatch({ t: "error", message: (e as Error).message });
    }
  }, []);

  const submitOrder = useCallback(async (order: ReplayOrderRequest): Promise<ReplayState | null> => {
    const id = idRef.current;
    if (!id) return null;
    dispatch({ t: "orderPending" });
    try {
      const resp = await api.submitReplayOrder(id, order);
      dispatch({ t: "stateSynced", state: resp.state });
      return resp.state;
    } catch (e) {
      dispatch({ t: "orderErr", message: (e as Error).message });
      return null;
    }
  }, []);

  const syncState = useCallback((st: ReplayState) => dispatch({ t: "stateSynced", state: st }), []);

  const undo = useCallback(async () => {
    const id = idRef.current;
    if (!id) return null;
    try {
      const st = await api.undoReplayOrder(id);
      dispatch({ t: "stateSynced", state: st });
      return st;
    } catch (e) {
      dispatch({ t: "orderErr", message: (e as Error).message });
      return null;
    }
  }, []);

  const rewind = useCallback(async (toIndex: number, confirm = true) => {
    const id = idRef.current;
    if (!id) return null;
    try {
      const st = await api.rewindReplay(id, toIndex, confirm);
      dispatch({ t: "stateSynced", state: st });
      return st;
    } catch (e) {
      dispatch({ t: "orderErr", message: (e as Error).message });
      return null;
    }
  }, []);

  const reset = useCallback(async () => {
    const id = idRef.current;
    if (!id) return null;
    try {
      const st = await api.resetReplay(id);
      dispatch({ t: "stateSynced", state: st });
      return st;
    } catch (e) {
      dispatch({ t: "orderErr", message: (e as Error).message });
      return null;
    }
  }, []);

  const seek = useCallback((toIndex: number) => {
    const id = idRef.current;
    if (!id) return;
    // fire-and-forget persistence of the view cursor
    api.seekReplay(id, toIndex).catch(() => {});
  }, []);

  const finish = useCallback(async (upto?: number) => {
    const id = idRef.current;
    if (!id) return;
    try {
      const [score, journal] = await Promise.all([
        api.scoreReplay(id, upto),
        api.getReplayJournal(id, upto),
      ]);
      dispatch({ t: "scored", score, journal });
    } catch (e) {
      dispatch({ t: "orderErr", message: (e as Error).message });
    }
  }, []);

  const backToRunning = useCallback(() => dispatch({ t: "clearScore" }), []);

  const close = useCallback(async () => {
    const id = idRef.current;
    localStorage.removeItem(LS_KEY);
    dispatch({ t: "close" });
    if (id) await api.deleteReplaySession(id).catch(() => {});
  }, []);

  // Resume a persisted session on mount (first persistence in the app).
  useEffect(() => {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return;
    let saved: { sessionId?: string; resp?: ReplaySessionResponse } = {};
    try {
      saved = JSON.parse(raw);
    } catch {
      localStorage.removeItem(LS_KEY);
      return;
    }
    if (!saved.sessionId || !saved.resp) {
      localStorage.removeItem(LS_KEY);
      return;
    }
    (async () => {
      try {
        // Probe the backend first: 404/410 means the session is gone or stale.
        const st = await api.getReplayState(saved.sessionId!);
        const resp = { ...saved.resp!, bars: null } as ReplaySessionResponse;
        const bars = await loadAllBars(resp); // re-fetch bars from the live session
        dispatch({ t: "started", resp, bars });
        dispatch({ t: "stateSynced", state: st });
      } catch {
        // 404 / stale -> clear the stale pointer, stay on setup.
        localStorage.removeItem(LS_KEY);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Note: no beforeunload DELETE — the fetch API can't reliably fire on unload,
  // and the backend reaps orphaned sessions via TTL. The localStorage pointer
  // lets the next launch resume or clean up.

  return {
    state,
    start,
    submitOrder,
    syncState,
    undo,
    rewind,
    reset,
    seek,
    finish,
    backToRunning,
    close,
  };
}

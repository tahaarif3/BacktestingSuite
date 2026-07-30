import { useCallback, useRef, useState } from "react";
import { api } from "../api";
import type {
  PortfolioCreateResponse,
  PortfolioScore,
  PortfolioSessionConfig,
  PortfolioState,
  PortfolioSymbolBars,
} from "../types";

export type PortfolioPhase = "setup" | "loading" | "running" | "scored" | "error";

export function usePortfolioSession() {
  const [phase, setPhase] = useState<PortfolioPhase>("setup");
  const [created, setCreated] = useState<PortfolioCreateResponse | null>(null);
  const [state, setState] = useState<PortfolioState | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [symbolBars, setSymbolBars] = useState<PortfolioSymbolBars | null>(null);
  const [score, setScore] = useState<PortfolioScore | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const idRef = useRef<string | null>(null);

  const start = useCallback(async (config: PortfolioSessionConfig) => {
    setPhase("loading");
    setError(null);
    try {
      const resp = await api.createPortfolioSession(config);
      idRef.current = resp.session_id;
      setCreated(resp);
      setState(resp.state);
      setSelected(null);
      setSymbolBars(null);
      setScore(null);
      setPhase("running");
    } catch (e) {
      setError((e as Error).message);
      setPhase("error");
    }
  }, []);

  const selectSymbol = useCallback(async (symbol: string) => {
    const id = idRef.current;
    if (!id) return;
    setSelected(symbol);
    try {
      setSymbolBars(await api.getPortfolioSymbol(id, symbol));
    } catch {
      setSymbolBars(null);
    }
  }, []);

  const submitOrder = useCallback(async (order: unknown): Promise<PortfolioState | null> => {
    const id = idRef.current;
    if (!id) return null;
    setSubmitting(true);
    setError(null);
    try {
      const resp = await api.submitPortfolioOrder(id, order);
      setState(resp.state);
      return resp.state;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const seek = useCallback((toIndex: number) => {
    const id = idRef.current;
    if (id) api.seekPortfolio(id, toIndex).then(setState).catch(() => {});
  }, []);

  const rewind = useCallback(async (toIndex: number): Promise<PortfolioState | null> => {
    const id = idRef.current;
    if (!id) return null;
    try {
      const st = await api.rewindPortfolio(id, toIndex);
      setState(st);
      return st;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, []);

  const reset = useCallback(async (): Promise<PortfolioState | null> => {
    const id = idRef.current;
    if (!id) return null;
    const st = await api.resetPortfolio(id).catch(() => null);
    if (st) setState(st);
    return st;
  }, []);

  const undo = useCallback(async () => {
    const id = idRef.current;
    if (!id) return;
    const st = await api.undoPortfolio(id).catch(() => null);
    if (st) setState(st);
  }, []);

  const finish = useCallback(async () => {
    const id = idRef.current;
    if (!id) return;
    try {
      setScore(await api.scorePortfolio(id));
      setPhase("scored");
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  const backToRunning = useCallback(() => setPhase("running"), []);

  const close = useCallback(async () => {
    const id = idRef.current;
    idRef.current = null;
    setPhase("setup");
    setCreated(null);
    setState(null);
    setSelected(null);
    setScore(null);
    if (id) await api.deletePortfolioSession(id).catch(() => {});
  }, []);

  return {
    phase, created, state, selected, symbolBars, score, error, submitting,
    start, selectSymbol, submitOrder, seek, rewind, reset, undo, finish, backToRunning, close,
  };
}

import { useCallback, useEffect, useRef, useState } from "react";

export type PlaybackStatus = "idle" | "playing" | "paused" | "ended";

export interface PlaybackState {
  cursor: number;
  maxCursorReached: number;
  status: PlaybackStatus;
  msPerBar: number;
  autoPauseOnSignal: boolean;
  reviewing: boolean;
}

export interface PlaybackControls {
  play(): void;
  pause(): void;
  toggle(): void;
  stepForward(n?: number): void;
  stepBack(n?: number): void;
  jumpToNextSignal(): void;
  jumpToLive(): void;
  jumpToBar(i: number): void;
  restart(): void;
  setSpeed(msPerBar: number): void;
  setAutoPause(v: boolean): void;
  setMaxReached(i: number): void;
  replaceProgress(i: number): void;
}

interface Options {
  lastIndex: number;
  startIndex: number;
  signalBars: Set<number>;
  onDraw: (cursor: number) => void;
  onSignalPause?: (barIndex: number) => void;
  onEnd?: () => void;
  onCursorSettled?: (cursor: number) => void; // debounced commit for persistence
  enabled: boolean;
}

const MAX_PER_FRAME = 8;
const DT_CLAMP = 250;

export function usePlayback(opts: Options): [PlaybackState, PlaybackControls] {
  const { lastIndex, startIndex, signalBars, onDraw, onSignalPause, onEnd, onCursorSettled, enabled } = opts;

  const [state, setState] = useState<PlaybackState>({
    cursor: startIndex,
    maxCursorReached: startIndex,
    status: "idle",
    msPerBar: 200,
    autoPauseOnSignal: true,
    reviewing: false,
  });

  const cursorRef = useRef(startIndex);
  const maxRef = useRef(startIndex);
  const accRef = useRef(0);
  const lastTsRef = useRef(0);
  const rafRef = useRef<number | null>(null);
  const msRef = useRef(200);
  const autoPauseRef = useRef(true);
  const settleRef = useRef<number | null>(null);

  // Refs to the latest callbacks / bounds so the rAF closure never goes stale.
  const drawRef = useRef(onDraw);
  const endRef = useRef(onEnd);
  const sigPauseRef = useRef(onSignalPause);
  const settledRef = useRef(onCursorSettled);
  const lastIndexRef = useRef(lastIndex);
  const signalBarsRef = useRef(signalBars);
  drawRef.current = onDraw;
  endRef.current = onEnd;
  sigPauseRef.current = onSignalPause;
  settledRef.current = onCursorSettled;
  lastIndexRef.current = lastIndex;
  signalBarsRef.current = signalBars;

  const commit = useCallback((status?: PlaybackStatus) => {
    if (cursorRef.current > maxRef.current) maxRef.current = cursorRef.current;
    setState((s) => ({
      ...s,
      cursor: cursorRef.current,
      maxCursorReached: maxRef.current,
      reviewing: cursorRef.current < maxRef.current,
      status: status ?? s.status,
    }));
    // debounced settle for persistence
    if (settleRef.current) window.clearTimeout(settleRef.current);
    settleRef.current = window.setTimeout(() => {
      settledRef.current?.(cursorRef.current);
    }, 600);
  }, []);

  const stop = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  }, []);

  const pause = useCallback(() => {
    stop();
    setState((s) => (s.status === "playing" ? { ...s, status: "paused" } : s));
  }, [stop]);

  const frame = useCallback(
    (ts: number) => {
      const dt = Math.min(ts - lastTsRef.current, DT_CLAMP);
      lastTsRef.current = ts;
      accRef.current += dt;

      let advanced = 0;
      let hitSignal = -1;
      const last = lastIndexRef.current;
      while (accRef.current >= msRef.current && cursorRef.current < last && advanced < MAX_PER_FRAME) {
        accRef.current -= msRef.current;
        cursorRef.current += 1;
        advanced += 1;
        if (autoPauseRef.current && signalBarsRef.current.has(cursorRef.current)) {
          hitSignal = cursorRef.current;
          break;
        }
      }
      if (advanced === MAX_PER_FRAME) accRef.current = 0; // catch-up guard

      if (advanced > 0) {
        drawRef.current(cursorRef.current);
        commit();
      }

      if (hitSignal >= 0) {
        stop();
        setState((s) => ({ ...s, status: "paused" }));
        sigPauseRef.current?.(hitSignal);
        return;
      }
      if (cursorRef.current >= last) {
        stop();
        setState((s) => ({ ...s, status: "ended" }));
        endRef.current?.();
        return;
      }
      rafRef.current = requestAnimationFrame(frame);
    },
    [commit, stop]
  );

  const play = useCallback(() => {
    if (cursorRef.current >= lastIndexRef.current) return;
    if (rafRef.current !== null) return;
    lastTsRef.current = performance.now();
    accRef.current = 0;
    setState((s) => ({ ...s, status: "playing" }));
    rafRef.current = requestAnimationFrame(frame);
  }, [frame]);

  const setCursor = useCallback(
    (i: number, { redraw = true }: { redraw?: boolean } = {}) => {
      const clamped = Math.max(startIndex, Math.min(i, lastIndexRef.current));
      cursorRef.current = clamped;
      if (redraw) drawRef.current(clamped);
      commit();
    },
    [commit, startIndex]
  );

  const controls: PlaybackControls = {
    play,
    pause,
    toggle: () => {
      if (rafRef.current !== null) pause();
      else play();
    },
    stepForward: (n = 1) => {
      pause();
      setCursor(cursorRef.current + n);
    },
    stepBack: (n = 1) => {
      pause();
      setCursor(cursorRef.current - n);
    },
    jumpToNextSignal: () => {
      pause();
      let next = -1;
      for (const b of signalBarsRef.current) {
        if (b > cursorRef.current && (next === -1 || b < next)) next = b;
      }
      if (next >= 0) {
        setCursor(next);
        sigPauseRef.current?.(next);
      }
    },
    jumpToLive: () => {
      pause();
      setCursor(maxRef.current);
    },
    jumpToBar: (i: number) => {
      pause();
      setCursor(i);
    },
    restart: () => {
      pause();
      maxRef.current = startIndex;
      setCursor(startIndex);
    },
    setSpeed: (ms: number) => {
      msRef.current = ms;
      setState((s) => ({ ...s, msPerBar: ms }));
    },
    setAutoPause: (v: boolean) => {
      autoPauseRef.current = v;
      setState((s) => ({ ...s, autoPauseOnSignal: v }));
    },
    setMaxReached: (i: number) => {
      maxRef.current = Math.max(maxRef.current, i);
      cursorRef.current = Math.max(startIndex, Math.min(i, lastIndexRef.current));
      commit();
    },
    replaceProgress: (i: number) => {
      pause();
      const clamped = Math.max(startIndex, Math.min(i, lastIndexRef.current));
      maxRef.current = clamped;
      cursorRef.current = clamped;
      drawRef.current(clamped);
      commit("paused");
    },
  };

  // Pause when the tab/panel is hidden or the window is backgrounded.
  useEffect(() => {
    if (!enabled) pause();
  }, [enabled, pause]);

  useEffect(() => {
    const onVis = () => {
      if (document.hidden) pause();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [pause]);

  useEffect(() => () => stop(), [stop]);

  return [state, controls];
}

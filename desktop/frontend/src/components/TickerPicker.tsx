import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { TickerInfo, TickerSearchHit } from "../types";
import { INTERVALS, clampRange, earliestFor, estimateBars } from "../intervals";

export interface TickerSelection {
  ticker: string;
  start: string;
  end: string;
  interval: string;
}

interface Props {
  value: TickerSelection;
  onChange: (v: TickerSelection) => void;
  onFetch?: (v: TickerSelection) => void;
  busy?: boolean;
  showInterval?: boolean;
  compact?: boolean;
}

export default function TickerPicker({
  value,
  onChange,
  onFetch,
  busy = false,
  showInterval = true,
  compact = false,
}: Props) {
  const [info, setInfo] = useState<TickerInfo | null>(null);
  const [hits, setHits] = useState<TickerSearchHit[]>([]);
  const [resolveError, setResolveError] = useState<string | null>(null);
  const resolveTimer = useRef<number | null>(null);
  const searchTimer = useRef<number | null>(null);

  const set = (patch: Partial<TickerSelection>) => onChange({ ...value, ...patch });

  // Debounced ticker resolution (never blocks the Fetch button).
  useEffect(() => {
    if (resolveTimer.current) window.clearTimeout(resolveTimer.current);
    setResolveError(null);
    if (!value.ticker.trim()) {
      setInfo(null);
      return;
    }
    resolveTimer.current = window.setTimeout(async () => {
      try {
        const r = await api.validateTicker(value.ticker, value.interval, value.start, value.end);
        setInfo(r);
      } catch (e) {
        setInfo(null);
        setResolveError((e as Error).message || "Couldn't verify (offline?) — you can still try fetching.");
      }
    }, 450);
    return () => {
      if (resolveTimer.current) window.clearTimeout(resolveTimer.current);
    };
  }, [value.ticker, value.interval, value.start, value.end]);

  // Debounced autocomplete suggestions.
  useEffect(() => {
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    const q = value.ticker.trim();
    if (q.length < 2) {
      setHits([]);
      return;
    }
    searchTimer.current = window.setTimeout(async () => {
      try {
        setHits(await api.searchTickers(q, 8));
      } catch {
        setHits([]);
      }
    }, 400);
    return () => {
      if (searchTimer.current) window.clearTimeout(searchTimer.current);
    };
  }, [value.ticker]);

  const onIntervalChange = (interval: string) => {
    const clamped = clampRange({ ...value, interval });
    set({ interval, start: clamped.start, end: clamped.end });
  };

  const clamp = clampRange(value);
  const bars = estimateBars(value);
  const minStart = earliestFor(value.interval);
  const today = new Date().toISOString().slice(0, 10);

  const resolvedLine = info?.valid
    ? `${info.ticker} — ${info.long_name ?? info.short_name ?? "resolved"}${
        info.exchange ? `, ${info.exchange}` : ""
      }${info.currency ? `, ${info.currency}` : ""}`
    : null;

  return (
    <div className={compact ? "ticker-picker compact" : "ticker-picker"}>
      <div className="field">
        <label>Ticker</label>
        <input
          list="ticker-suggestions"
          value={value.ticker}
          onChange={(e) => set({ ticker: e.target.value.toUpperCase() })}
          placeholder="AAPL"
        />
        <datalist id="ticker-suggestions">
          {hits.map((h) => (
            <option key={h.symbol} value={h.symbol}>
              {h.name ?? ""} {h.exchange ? `(${h.exchange})` : ""}
            </option>
          ))}
        </datalist>
      </div>

      {showInterval && (
        <div className="field">
          <label>Interval</label>
          <select value={value.interval} onChange={(e) => onIntervalChange(e.target.value)}>
            {INTERVALS.map((i) => (
              <option key={i.id} value={i.id}>
                {i.label}
              </option>
            ))}
          </select>
          <div className="hint">{INTERVALS.find((i) => i.id === value.interval)?.note}</div>
        </div>
      )}

      <div className="row">
        <div className="field">
          <label>Start</label>
          <input
            type="date"
            min={minStart}
            max={today}
            value={value.start}
            onChange={(e) => set({ start: e.target.value })}
          />
        </div>
        <div className="field">
          <label>End</label>
          <input
            type="date"
            min={value.start}
            max={today}
            value={value.end}
            onChange={(e) => set({ end: e.target.value })}
          />
        </div>
      </div>

      {clamp.warning && <div className="hint warn">{clamp.warning}</div>}
      <div className="hint">≈ {bars.toLocaleString()} bars</div>

      {resolvedLine && <div className="hint ok">{resolvedLine}</div>}
      {info && !info.valid && info.range_message && <div className="hint warn">{info.range_message}</div>}
      {resolveError && <div className="hint">{resolveError}</div>}

      {onFetch && (
        <button
          className="btn btn-secondary"
          disabled={busy}
          onClick={() => {
            const c = clampRange(value);
            onFetch({ ...value, start: c.start, end: c.end });
          }}
        >
          {busy && <span className="spinner" />}
          Fetch &amp; use {value.ticker || "ticker"}
        </button>
      )}
    </div>
  );
}

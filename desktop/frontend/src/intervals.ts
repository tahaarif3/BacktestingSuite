// Interval catalog mirroring the backend (market_meta.INTERVALS). Kept static so
// the picker works offline; the backend remains the source of truth for fetches.

export interface IntervalDef {
  id: string;
  label: string;
  intraday: boolean;
  maxLookbackDays: number | null;
  maxSpanDays: number | null;
  barsPerDay: number; // rough, for the "≈ N bars" estimate
  note: string;
}

export const INTERVALS: IntervalDef[] = [
  { id: "1d", label: "1 day", intraday: false, maxLookbackDays: null, maxSpanDays: null, barsPerDay: 1, note: "Full history available." },
  { id: "1h", label: "1 hour", intraday: true, maxLookbackDays: 730, maxSpanDays: 730, barsPerDay: 7, note: "Last 730 days only." },
  { id: "30m", label: "30 min", intraday: true, maxLookbackDays: 60, maxSpanDays: 60, barsPerDay: 13, note: "Last 60 days only." },
  { id: "15m", label: "15 min", intraday: true, maxLookbackDays: 60, maxSpanDays: 60, barsPerDay: 26, note: "Last 60 days only." },
  { id: "5m", label: "5 min", intraday: true, maxLookbackDays: 60, maxSpanDays: 60, barsPerDay: 78, note: "Last 60 days only." },
  { id: "1m", label: "1 min", intraday: true, maxLookbackDays: 30, maxSpanDays: 7, barsPerDay: 390, note: "Last 30 days; fetched 7 days at a time." },
];

export function intervalDef(id: string): IntervalDef {
  return INTERVALS.find((i) => i.id === id) ?? INTERVALS[0];
}

const DAY_MS = 86_400_000;

function isoToday(): string {
  return new Date().toISOString().slice(0, 10);
}

export interface RangeSel {
  start: string;
  end: string;
  interval: string;
}

/** Nearest valid (start, end) for the interval and a human warning if clamped. */
export function clampRange(sel: RangeSel): { start: string; end: string; warning: string | null } {
  const def = intervalDef(sel.interval);
  const today = isoToday();
  let start = sel.start;
  let end = sel.end > today ? today : sel.end;
  let warning: string | null = null;

  if (def.maxLookbackDays !== null) {
    const earliest = new Date(Date.now() - def.maxLookbackDays * DAY_MS).toISOString().slice(0, 10);
    if (start < earliest) {
      start = earliest;
      warning = `${def.label} data only goes back ${def.maxLookbackDays} days — start moved to ${earliest}.`;
    }
  }
  if (end < start) end = start;
  return { start, end, warning };
}

/** Rough bar-count estimate so the user knows if a session is 2 minutes or 2 hours. */
export function estimateBars(sel: RangeSel): number {
  const def = intervalDef(sel.interval);
  const days = Math.max(0, (Date.parse(sel.end) - Date.parse(sel.start)) / DAY_MS);
  const businessDays = days * (5 / 7);
  if (!def.intraday) return Math.round(businessDays);
  return Math.round(businessDays * def.barsPerDay);
}

export function earliestFor(interval: string): string | undefined {
  const def = intervalDef(interval);
  if (def.maxLookbackDays === null) return undefined;
  return new Date(Date.now() - def.maxLookbackDays * DAY_MS).toISOString().slice(0, 10);
}

import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { PALETTE } from "./Plot";

export interface CandleMarker {
  index: number;
  to_signal: number; // -1 | 0 | 1
}

export interface CandleFill {
  index: number;
  side: "buy" | "sell" | "close";
  price: number;
}

export interface PriceOverlay {
  id: string;
  label: string;
  color: string;
  values: (number | null)[]; // full-length, sliced to the window internally
}

export interface SubPanel {
  id: string;
  label: string;
  color: string;
  values: (number | null)[]; // full-length
  fixedRange?: [number, number]; // e.g. RSI [0,100]
  guides?: number[]; // horizontal guide lines (e.g. 30/70, or 100 baseline)
}

export interface CandleChartProps {
  dates: (number | string)[]; // full-length, for tick labels + hover
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  signals: CandleMarker[];
  fills: CandleFill[];
  overlays?: PriceOverlay[];
  panels?: SubPanel[];
  windowSize?: number;
  height?: number;
  sessionKey: string; // bump to force a full re-init
  intraday?: boolean;
}

export interface CandleChartHandle {
  draw(cursor: number): void;
  resize(): void;
}

const GRID = "#1e293b";
const LAYOUT_BASE: Record<string, unknown> = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#cbd5e1", family: "Inter, Segoe UI, system-ui, sans-serif", size: 11 },
  margin: { l: 56, r: 16, t: 12, b: 28 },
  showlegend: false,
  hovermode: "x unified",
  dragmode: "pan",
};

function fmtDate(d: number | string, intraday: boolean): string {
  if (typeof d === "number") {
    const dt = new Date(d * 1000);
    return intraday
      ? dt.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
      : dt.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  return String(d);
}

const CandleChart = forwardRef<CandleChartHandle, CandleChartProps>(function CandleChart(props, ref) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const propsRef = useRef(props);
  const yRangeRef = useRef<[number, number] | null>(null);
  const initedRef = useRef(false);
  const lastCursorRef = useRef(0);

  propsRef.current = props;

  const config = { displayModeBar: false, responsive: false, scrollZoom: true };

  function buildTraces(cursor: number) {
    const p = propsRef.current;
    const win = p.windowSize ?? 120;
    const hi = Math.max(1, Math.min(cursor + 1, p.close.length));
    const lo = Math.max(0, hi - win);
    const xs: number[] = [];
    for (let i = lo; i < hi; i++) xs.push(i);

    const o = p.open.slice(lo, hi);
    const h = p.high.slice(lo, hi);
    const l = p.low.slice(lo, hi);
    const c = p.close.slice(lo, hi);
    const v = p.volume.slice(lo, hi);
    const hoverDates = xs.map((i) => fmtDate(p.dates[i], !!p.intraday));

    // y-range with hysteresis so the axis doesn't "breathe" every frame.
    let ymin = Math.min(...l);
    let ymax = Math.max(...h);
    if (!Number.isFinite(ymin) || !Number.isFinite(ymax)) {
      ymin = 0;
      ymax = 1;
    }
    const pad = (ymax - ymin) * 0.06 || 1;
    const desired: [number, number] = [ymin - pad, ymax + pad];
    const cur = yRangeRef.current;
    let yr = desired;
    if (cur) {
      const span = cur[1] - cur[0];
      const inside = desired[0] > cur[0] && desired[1] < cur[1];
      const muchSmaller = desired[1] - desired[0] < 0.6 * span;
      yr = inside && !muchSmaller ? cur : desired;
    }
    yRangeRef.current = yr;

    const volColors = c.map((cl, i) => (cl >= o[i] ? "rgba(52,211,153,0.35)" : "rgba(248,113,113,0.35)"));

    const sigMarks = p.signals.filter((s) => s.index >= lo && s.index < hi);
    const fillMarks = p.fills.filter((f) => f.index >= lo && f.index < hi);

    const candle = {
      type: "candlestick",
      x: xs,
      open: o,
      high: h,
      low: l,
      close: c,
      customdata: hoverDates,
      increasing: { line: { color: PALETTE.up } },
      decreasing: { line: { color: PALETTE.down } },
      xaxis: "x",
      yaxis: "y",
      hovertext: hoverDates,
      name: "",
    };
    const volume = {
      type: "bar",
      x: xs,
      y: v,
      marker: { color: volColors },
      xaxis: "x",
      yaxis: "y2",
      hoverinfo: "skip",
    };
    const signalTrace = {
      type: "scatter",
      mode: "markers",
      x: sigMarks.map((s) => s.index),
      y: sigMarks.map((s) => (s.to_signal > 0 ? p.low[s.index] * 0.985 : p.high[s.index] * 1.015)),
      marker: {
        symbol: sigMarks.map((s) => (s.to_signal > 0 ? "triangle-up" : "triangle-down")),
        color: sigMarks.map((s) =>
          s.to_signal > 0 ? PALETTE.success : s.to_signal < 0 ? PALETTE.danger : PALETTE.benchmark
        ),
        size: 11,
        line: { width: 1, color: "#0f172a" },
      },
      xaxis: "x",
      yaxis: "y",
      hoverinfo: "skip",
    };
    const fillTrace = {
      type: "scatter",
      mode: "markers",
      x: fillMarks.map((f) => f.index),
      y: fillMarks.map((f) => f.price),
      marker: {
        symbol: fillMarks.map((f) => (f.side === "buy" ? "triangle-up" : "triangle-down")),
        color: fillMarks.map((f) => (f.side === "buy" ? PALETTE.primary : PALETTE.accent)),
        size: 13,
        line: { width: 1.5, color: "#e2e8f0" },
      },
      xaxis: "x",
      yaxis: "y",
      hoverinfo: "skip",
    };

    // Price-panel overlay lines (SMA / EMA), sliced to the window.
    const overlays = p.overlays ?? [];
    const overlayTraces = overlays.map((ov) => ({
      type: "scatter",
      mode: "lines",
      x: xs,
      y: ov.values.slice(lo, hi),
      line: { color: ov.color, width: 1.4 },
      xaxis: "x",
      yaxis: "y",
      name: ov.label,
      hoverinfo: "skip",
      connectgaps: false,
    }));

    // Stacked lower sub-panels (RSI, relative-strength) above the volume strip.
    const panels = p.panels ?? [];
    const volTop = 0.12;
    const gap = 0.03;
    const panelH = 0.16;
    let yStart = volTop + gap;
    const panelDomains: [number, number][] = [];
    for (let k = 0; k < panels.length; k++) {
      panelDomains.push([yStart, yStart + panelH]);
      yStart += panelH + gap;
    }
    const priceBottom = panels.length > 0 ? yStart : volTop + gap;

    const panelTraces = panels.map((pan, k) => ({
      type: "scatter",
      mode: "lines",
      x: xs,
      y: pan.values.slice(lo, hi),
      line: { color: pan.color, width: 1.4 },
      xaxis: "x",
      yaxis: `y${k + 3}`,
      name: pan.label,
      hoverinfo: "skip",
      connectgaps: false,
    }));

    // ~6 tick labels across the window.
    const nTicks = 6;
    const tickvals: number[] = [];
    const ticktext: string[] = [];
    const stride = Math.max(1, Math.floor(xs.length / nTicks));
    for (let i = 0; i < xs.length; i += stride) {
      tickvals.push(xs[i]);
      ticktext.push(fmtDate(p.dates[xs[i]], !!p.intraday));
    }

    const shapes: Record<string, unknown>[] = [];
    const annotations: Record<string, unknown>[] = [];
    panels.forEach((pan, k) => {
      (pan.guides ?? []).forEach((g) => {
        shapes.push({
          type: "line", xref: "x domain", x0: 0, x1: 1,
          yref: `y${k + 3}`, y0: g, y1: g,
          line: { color: "#334155", width: 1, dash: "dot" },
        });
      });
      annotations.push({
        xref: "paper", yref: `y${k + 3} domain`, x: 0.004, y: 1,
        xanchor: "left", yanchor: "top", text: pan.label, showarrow: false,
        font: { size: 10, color: pan.color },
      });
    });

    const layout: Record<string, unknown> = {
      ...LAYOUT_BASE,
      xaxis: {
        type: "linear",
        range: [Math.max(-0.5, hi - win - 0.5), hi + 1.5],
        gridcolor: GRID,
        zerolinecolor: GRID,
        tickvals,
        ticktext,
        rangeslider: { visible: false },
      },
      yaxis: { domain: [priceBottom, 1], range: yr, gridcolor: GRID, zerolinecolor: GRID, side: "right" },
      yaxis2: { domain: [0, volTop], gridcolor: "rgba(0,0,0,0)", showticklabels: false },
      shapes,
      annotations,
      uirevision: p.sessionKey,
    };
    panels.forEach((pan, k) => {
      layout[`yaxis${k + 3}`] = {
        domain: panelDomains[k],
        gridcolor: GRID,
        zerolinecolor: GRID,
        side: "right",
        range: pan.fixedRange,
        fixedrange: !!pan.fixedRange,
      };
    });
    return {
      traces: [candle, volume, ...overlayTraces, signalTrace, fillTrace, ...panelTraces],
      layout,
    };
  }

  function draw(cursor: number) {
    const div = divRef.current;
    if (!div) return;
    lastCursorRef.current = cursor;
    // A rendering hiccup must never propagate and stall the playback clock or
    // block a cursor commit — swallow and log.
    try {
      const { traces, layout } = buildTraces(cursor);
      const t0 = performance.now();
      if (!initedRef.current) {
        Plotly.newPlot(div, traces, layout, config);
        initedRef.current = true;
      } else {
        Plotly.react(div, traces, layout, config);
      }
      if (import.meta.env.DEV) {
        const ms = performance.now() - t0;
        if (ms > 25) console.debug(`[CandleChart] slow frame ${ms.toFixed(1)}ms`);
      }
    } catch (e) {
      if (import.meta.env.DEV) console.debug("[CandleChart] draw error", e);
    }
  }

  useImperativeHandle(ref, () => ({
    draw,
    resize: () => {
      if (divRef.current && initedRef.current) Plotly.Plots.resize(divRef.current);
    },
  }));

  // Re-init from scratch when the session changes.
  useEffect(() => {
    initedRef.current = false;
    yRangeRef.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.sessionKey]);

  useEffect(() => {
    draw(0);
    return () => {
      if (divRef.current) {
        try {
          Plotly.purge(divRef.current);
        } catch {
          /* ignore */
        }
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.sessionKey]);

  // Redraw at the last cursor when markers change (an order placed, reset, etc.)
  // so fill/signal markers stay in sync without the parent driving the cursor.
  useEffect(() => {
    if (initedRef.current) draw(lastCursorRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.fills, props.signals, props.overlays, props.panels]);

  return <div ref={divRef} style={{ width: "100%", height: props.height ?? 420 }} />;
});

export default CandleChart;

export const pct = (v: number) => `${(v * 100).toFixed(2)}%`;
export const dec = (v: number) => (Number.isFinite(v) ? v.toFixed(4) : "∞");
export const usd = (v: number) =>
  v.toLocaleString("en-US", { style: "currency", currency: "USD" });

// How each summary metric should be rendered, in display order.
export const METRIC_FORMAT: Record<string, { fmt: (v: number) => string; goodHigh: boolean }> = {
  "Total Return": { fmt: pct, goodHigh: true },
  CAGR: { fmt: pct, goodHigh: true },
  "Sharpe Ratio": { fmt: dec, goodHigh: true },
  "Sortino Ratio": { fmt: dec, goodHigh: true },
  "Max Drawdown": { fmt: pct, goodHigh: false },
  "Win Rate": { fmt: pct, goodHigh: true },
  "Profit Factor": { fmt: dec, goodHigh: true },
  "Exposure Time": { fmt: pct, goodHigh: true },
  "Total Trades": { fmt: (v) => String(Math.round(v)), goodHigh: true },
};

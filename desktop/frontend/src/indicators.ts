// Client-side technical indicators for the replay chart. All operate on the
// full close series (the frontend already holds every bar); the chart slices
// to the visible window itself. Warm-up bars are `null` so Plotly leaves a gap.

export type IndicatorType = "sma" | "ema" | "rsi";

export interface Indicator {
  id: string;
  type: IndicatorType;
  period: number;
  color: string;
}

export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period < 1) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period < 1 || values.length === 0) return out;
  const k = 2 / (period + 1);
  // seed with the SMA of the first `period` values
  let seed = 0;
  for (let i = 0; i < values.length; i++) {
    if (i < period) {
      seed += values[i];
      if (i === period - 1) out[i] = seed / period;
      continue;
    }
    const prev = out[i - 1] as number;
    out[i] = values[i] * k + prev * (1 - k);
  }
  return out;
}

/** Wilder's RSI. */
export function rsi(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period < 1 || values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    const g = d >= 0 ? d : 0;
    const l = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

/** Relative strength of `stock` vs `ref` (SPY), rebased to 100 at the first
 *  bar where both exist. Rising => the stock is outperforming the index. */
export function relativeStrength(stock: number[], ref: number[]): (number | null)[] {
  const n = Math.min(stock.length, ref.length);
  const out: (number | null)[] = new Array(stock.length).fill(null);
  let base: number | null = null;
  for (let i = 0; i < n; i++) {
    if (!ref[i] || !stock[i]) continue;
    const ratio = stock[i] / ref[i];
    if (base === null) base = ratio;
    out[i] = (ratio / base) * 100;
  }
  return out;
}

export interface Regime {
  spyWeak: boolean;
  stockStrong: boolean;
  rsPct: number; // stock return - spy return over lookback
  armed: boolean; // both regime legs satisfied
}

/** The RS-Breakout regime at a bar, computed from aligned stock + SPY closes.
 *  Mirrors the strategy's regime test (90-MA trend + rising/falling slope) so
 *  the readout matches why a signal fires. */
export function regimeAt(
  stock: number[],
  spy: number[],
  i: number,
  trendMa = 90,
  slopeLookback = 10,
  rsLookback = 20
): Regime | null {
  if (i < trendMa || i >= stock.length || spy.length <= i) return null;
  const smaAt = (arr: number[], idx: number) => {
    let s = 0;
    for (let k = idx - trendMa + 1; k <= idx; k++) s += arr[k];
    return s / trendMa;
  };
  const stockMa = smaAt(stock, i);
  const stockMaPrev = i - slopeLookback >= trendMa - 1 ? smaAt(stock, i - slopeLookback) : stockMa;
  const spyMa = smaAt(spy, i);
  const spyMaPrev = i - slopeLookback >= trendMa - 1 ? smaAt(spy, i - slopeLookback) : spyMa;

  const stockStrong = stock[i] > stockMa && stockMa - stockMaPrev > 0;
  const spyWeak = spy[i] < spyMa && spyMa - spyMaPrev < 0;
  const rsPct =
    i - rsLookback >= 0
      ? stock[i] / stock[i - rsLookback] - 1 - (spy[i] / spy[i - rsLookback] - 1)
      : 0;
  return { spyWeak, stockStrong, rsPct, armed: spyWeak && stockStrong && rsPct > 0 };
}

// A small rotating palette for user-added indicators.
export const INDICATOR_COLORS = ["#f59e0b", "#38bdf8", "#a78bfa", "#34d399", "#f472b6", "#e2e8f0"];

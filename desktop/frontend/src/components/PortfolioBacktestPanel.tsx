import { useEffect, useState } from "react";
import { api } from "../api";
import type { PortfolioBacktestResult } from "../types";
import { pct, usd, dec } from "../format";
import MetricCard from "./MetricCard";
import Plot, { PALETTE } from "./Plot";

const PCT_KEYS = new Set(["Total Return", "CAGR", "Max Drawdown", "Win Rate", "Exposure", "Worst Month", "Worst Year"]);
const INT_KEYS = new Set(["Total Trades"]);

function fmtMetric(k: string, v: number): string {
  if (k.includes("$")) return usd(v);
  if (PCT_KEYS.has(k)) return pct(v);
  if (INT_KEYS.has(k)) return String(Math.round(v));
  return dec(v);
}
function tone(k: string, v: number): "pos" | "neg" | "neutral" {
  if (k === "Max Drawdown" || k === "Worst Month" || k === "Worst Year" || k === "Avg Loss ($)") return v < 0 ? "neg" : "neutral";
  if (["Total Return", "CAGR", "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio", "Win Rate", "Profit Factor", "Expectancy ($)", "Avg R-Multiple"].includes(k))
    return v > 0 ? "pos" : "neg";
  return "neutral";
}

const SENS_LABELS: Record<string, string> = {
  market_ma: "Market MA", breakout_window: "Breakout window", rs_lookback: "RS lookback",
  rs_threshold: "RS threshold", volume_mult: "Volume ×", stop_atr_mult: "Stop × ATR",
  max_positions: "Max positions", risk_per_trade: "Risk / trade",
};

export default function PortfolioBacktestPanel() {
  const [tickers, setTickers] = useState("");
  const [interval, setIntervalValue] = useState("1d");
  const [start, setStart] = useState("2016-01-01");
  const [end, setEnd] = useState("2025-12-31");
  const [capital, setCapital] = useState(100000);

  const onIntervalChange = (iv: string) => {
    setIntervalValue(iv);
    const today = new Date();
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    if (iv === "5m" || iv === "15m") {
      const s = new Date(today); s.setDate(s.getDate() - 45);
      setStart(iso(s)); setEnd(iso(today));
    } else if (iv === "1h") {
      const s = new Date(today); s.setDate(s.getDate() - 540);
      setStart(iso(s)); setEnd(iso(today));
    } else {
      setStart("2016-01-01"); setEnd("2025-12-31");
    }
  };
  const [maxPos, setMaxPos] = useState(10);
  const [maxSector, setMaxSector] = useState(2);
  const [risk, setRisk] = useState(0.005);
  const [rsThresh, setRsThresh] = useState(0.05);
  const [stopAtr, setStopAtr] = useState(2.0);
  const [marketMa, setMarketMa] = useState(90);
  const [breakout, setBreakout] = useState(20);
  const [refresh, setRefresh] = useState(true);
  const [sensitivity, setSensitivity] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<PortfolioBacktestResult | null>(null);

  useEffect(() => {
    api.getWatchlist().then((t) => setTickers(t.join(", "))).catch(() => {});
  }, []);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const list = tickers.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
      const r = await api.runPortfolioBacktest({
        tickers: list.length ? list : null,
        start,
        end,
        interval,
        sensitivity,
        config: {
          initial_capital: capital, max_positions: maxPos, max_per_sector: maxSector,
          risk_per_trade: risk, rs_threshold: rsThresh, stop_atr_mult: stopAtr,
          market_ma: marketMa, breakout_window: breakout, refresh,
        },
      });
      setRes(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const c = res?.comparison;
  const rg = res?.regime;

  return (
    <div className="scanner">
      <div className="card">
        <h3>Multi-position portfolio backtest</h3>
        <p className="hint">
          Scans the universe each day, ranks breakout signals (SPY-regime filter + trend + relative
          strength), and opens up to {maxPos} risk-sized positions with sector caps — modelling next-open
          fills, ATR stops with gap-throughs, and daily accounting reconciliation. The first run downloads
          daily data for every name; sensitivity re-runs the engine across parameter grids (slower).
        </p>
        <div className="field">
          <label>Universe (comma/space separated)</label>
          <textarea rows={2} value={tickers} onChange={(e) => setTickers(e.target.value)} />
        </div>
        <div className="row">
          <div className="field">
            <label>Timeframe</label>
            <select value={interval} onChange={(e) => onIntervalChange(e.target.value)}>
              <option value="1d">Daily</option>
              <option value="1h">Hourly</option>
              <option value="15m">15-minute</option>
              <option value="5m">5-minute</option>
            </select>
          </div>
          <div className="field"><label>Start</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div className="field"><label>End</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="field"><label>Capital ($)</label><input type="number" value={capital} onChange={(e) => setCapital(+e.target.value || 0)} /></div>
        </div>
        {interval !== "1d" && (
          <p className="hint">
            Intraday: history is limited (~60 days for 5m/15m, ~2 years for 1h), and window params
            (Market MA, breakout, ATR) are counted in {interval} <em>bars</em> — shrink them accordingly.
          </p>
        )}
        <div className="row">
          <div className="field"><label>Max positions</label><input type="number" value={maxPos} onChange={(e) => setMaxPos(+e.target.value || 1)} /></div>
          <div className="field"><label>Max / sector</label><input type="number" value={maxSector} onChange={(e) => setMaxSector(+e.target.value || 1)} /></div>
          <div className="field"><label>Risk / trade</label><input type="number" step="0.0025" value={risk} onChange={(e) => setRisk(+e.target.value || 0)} /></div>
          <div className="field"><label>Stop × ATR</label><input type="number" step="0.5" value={stopAtr} onChange={(e) => setStopAtr(+e.target.value || 0)} /></div>
        </div>
        <div className="row">
          <div className="field"><label>RS threshold</label><input type="number" step="0.01" value={rsThresh} onChange={(e) => setRsThresh(+e.target.value || 0)} /></div>
          <div className="field"><label>Market MA</label><input type="number" value={marketMa} onChange={(e) => setMarketMa(+e.target.value || 1)} /></div>
          <div className="field"><label>Breakout window</label><input type="number" value={breakout} onChange={(e) => setBreakout(+e.target.value || 1)} /></div>
        </div>
        <div className="field checkbox">
          <input id="pbt-refresh" type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} />
          <label htmlFor="pbt-refresh" style={{ margin: 0 }}>Re-download data</label>
        </div>
        <div className="field checkbox">
          <input id="pbt-sens" type="checkbox" checked={sensitivity} onChange={(e) => setSensitivity(e.target.checked)} />
          <label htmlFor="pbt-sens" style={{ margin: 0 }}>Run parameter sensitivity (slower)</label>
        </div>
        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy} onClick={run}>
          {busy && <span className="spinner" />}{busy ? "Running…" : "Run backtest"}
        </button>
      </div>

      {res && (
        <>
          <div className="card">
            <h3>Performance ({res.universe.length} names, {res.trade_count} trades)</h3>
            <div className="metrics">
              {Object.entries(res.summary).map(([k, v]) => (
                <MetricCard key={k} label={k} value={fmtMetric(k, v)} tone={tone(k, v)} />
              ))}
            </div>
          </div>

          <div className="card">
            <h3>Equity: strategy vs SPY vs equal-weight</h3>
            <Plot
              height={360}
              data={[
                { x: res.series.dates, y: res.series.equity, type: "scatter", mode: "lines", name: "Strategy", line: { color: PALETTE.primary, width: 2 } },
                { x: res.series.dates, y: res.series.benchmark, type: "scatter", mode: "lines", name: "SPY B&H", line: { color: PALETTE.benchmark, width: 1.5, dash: "dot" } },
                { x: res.series.dates, y: res.series.equal_weight, type: "scatter", mode: "lines", name: "Equal-weight", line: { color: PALETTE.accent, width: 1.2 } },
              ]}
              layout={{ yaxis: { title: "Equity ($)" } }}
            />
          </div>

          <div className="card">
            <h3>Drawdown</h3>
            <Plot
              height={220}
              data={[{ x: res.series.dates, y: res.series.drawdown.map((d) => d * 100), type: "scatter", mode: "lines", fill: "tozeroy", name: "Drawdown", line: { color: PALETTE.danger, width: 1 }, fillcolor: "rgba(248,113,113,0.15)" }]}
              layout={{ yaxis: { title: "Drawdown (%)" } }}
            />
          </div>

          {c && (
            <div className="card">
              <h3>Ablation vs baselines</h3>
              <div className="metrics">
                <MetricCard label="Strategy total return" value={pct(res.summary["Total Return"])} tone={tone("Total Return", res.summary["Total Return"])} />
                <MetricCard label="SPY buy & hold" value={pct(c.spy_buy_hold_return)} tone="neutral" />
                <MetricCard label="Equal-weight universe" value={pct(c.equal_weight_return)} tone="neutral" />
                <MetricCard label="Without market filter" value={pct(c.no_market_filter_return)} tone="neutral" />
                <MetricCard label="Without RS filter" value={pct(c.no_rs_filter_return)} tone="neutral" />
              </div>
            </div>
          )}

          {rg && (
            <div className="card">
              <h3>Regime</h3>
              <div className="hint" style={{ marginBottom: 8 }}>
                SPY above 200-MA: {rg.spy_above_200ma.days} days, {pct(rg.spy_above_200ma.ann_return)} annualized ·
                below: {rg.spy_below_200ma.days} days, {pct(rg.spy_below_200ma.ann_return)} annualized
              </div>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Year</th>{rg.by_year.map((y) => <th key={y.year}>{y.year}</th>)}</tr></thead>
                  <tbody><tr><td style={{ color: "var(--text-muted)" }}>Return</td>{rg.by_year.map((y) => <td key={y.year} className={y.return >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(y.return)}</td>)}</tr></tbody>
                </table>
              </div>
            </div>
          )}

          {Object.keys(res.sensitivity).length > 0 && (
            <div className="card">
              <h3>Parameter sensitivity</h3>
              {Object.entries(res.sensitivity).map(([param, rows]) => (
                <div key={param} style={{ marginBottom: 10 }}>
                  <div className="section-title">{SENS_LABELS[param] ?? param}</div>
                  <div className="table-scroll">
                    <table>
                      <thead><tr><th>Value</th><th>Total return</th><th>CAGR</th><th>Max DD</th><th>Sharpe</th><th>Trades</th></tr></thead>
                      <tbody>
                        {rows.map((r, i) => (
                          <tr key={i}>
                            <td>{r.value}</td>
                            {r.error ? <td colSpan={5}>{r.error}</td> : (
                              <>
                                <td className={(r.total_return ?? 0) >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(r.total_return ?? 0)}</td>
                                <td>{pct(r.cagr ?? 0)}</td>
                                <td className="pnl-neg">{pct(r.max_drawdown ?? 0)}</td>
                                <td>{dec(r.sharpe ?? 0)}</td>
                                <td>{r.trades ?? 0}</td>
                              </>
                            )}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          )}

          <div className="card">
            <h3>Trade ledger (last {res.trades.length} of {res.trade_count})</h3>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Ticker</th><th>Sector</th><th>Entry</th><th>Exit</th><th>Reason</th><th>Shares</th><th>Net P&L</th><th>R</th><th>Days</th></tr></thead>
                <tbody>
                  {res.trades.slice().reverse().slice(0, 200).map((t, i) => (
                    <tr key={i}>
                      <td><strong>{t.ticker}</strong></td>
                      <td>{t.sector}</td>
                      <td>{t.entry_date}</td>
                      <td>{t.exit_date}</td>
                      <td>{t.exit_reason}</td>
                      <td>{t.shares}</td>
                      <td className={t.net_pnl >= 0 ? "pnl-pos" : "pnl-neg"}>{usd(t.net_pnl)}</td>
                      <td className={t.r_multiple >= 0 ? "pnl-pos" : "pnl-neg"}>{dec(t.r_multiple)}</td>
                      <td>{t.holding_days}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {res.warnings.length > 0 && <div className="card insight">Notes: {res.warnings.join("; ")}</div>}
        </>
      )}
    </div>
  );
}

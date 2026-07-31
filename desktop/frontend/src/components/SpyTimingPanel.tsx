import { useEffect, useState } from "react";
import { api } from "../api";
import type { TimingResponse, TimingResult, TimingStrategy } from "../types";
import { usd, pct, dec } from "../format";
import Plot, { PALETTE } from "./Plot";

const PRESETS_KEY = "bt.timing.presets";
const STRATS = [
  ["buy_hold", "Buy & hold (static)"], ["ma", "Moving-average regime"], ["golden_cross", "Golden cross 50/200"],
  ["momentum", "Absolute momentum"], ["vol_target", "Volatility target"], ["vol_derisk", "Vol de-risk"],
  ["seasonal", "Seasonal (sell-in-May)"], ["dip", "Buy-the-dip 80/20"],
];

const BASE: TimingStrategy = {
  label: "", strategy: "ma", ma_type: "sma", ma_period: 200, signal_freq: "daily", band_pct: 0,
  fast_period: 50, slow_period: 200, mom_lookback: 252, require_ma: false, vol_window: 20,
  vol_target: 0.15, vol_cap: 1, vol_thr: 0.2, derisk_exposure: 0.5, season_out_start: 5,
  season_out_end: 10, season_require_ma: false, dip_lookback: 60, dip_threshold: 0.1,
  dip_base_exposure: 0.8, exposure_in: 1, exposure_out: 0, cost_pct: 0.0005, cash_yield_annual: 0.045,
  borrow_annual: 0.055, rebalance_band: 0.03,
};
const mk = (o: Partial<TimingStrategy>): TimingStrategy => ({ ...BASE, ...o });

const DEFAULTS: TimingStrategy[] = [
  mk({ label: "MA 10-month (monthly)", strategy: "ma", ma_period: 210, signal_freq: "monthly" }),
  mk({ label: "Momentum 12m + >200-SMA", strategy: "momentum", mom_lookback: 252, require_ma: true }),
  mk({ label: "Vol target 15%", strategy: "vol_target", vol_target: 0.15 }),
  mk({ label: "Sell-in-May (if <200-SMA)", strategy: "seasonal", season_require_ma: true }),
  mk({ label: "Leverage 1.5× >200-SMA", strategy: "ma", ma_period: 200, exposure_in: 1.5, exposure_out: 1 }),
];

const SUMMARY_ORDER = ["Final Value", "CAGR", "Max Drawdown", "Sharpe Ratio", "Sortino Ratio",
  "Calmar Ratio", "Avg Exposure", "Turnover / yr", "Rebalances"];
const PCTK = new Set(["CAGR", "Max Drawdown"]);
function fmt(k: string, v: number): string {
  if (k === "Final Value") return usd(v);
  if (PCTK.has(k)) return pct(v);
  if (k === "Rebalances") return String(Math.round(v));
  return dec(v);
}

export default function SpyTimingPanel() {
  const [start, setStart] = useState("2004-01-01");
  const [end, setEnd] = useState("2026-07-31");
  const [capital, setCapital] = useState(10000);
  // Reuse the cached SPY series while tuning parameters; refresh is an
  // explicit opt-in so every small tweak does not trigger another download.
  const [refresh, setRefresh] = useState(false);
  const [strategies, setStrategies] = useState<TimingStrategy[]>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<TimingResponse | null>(null);
  const [logFor, setLogFor] = useState<string | null>(null);
  const [presets, setPresets] = useState<Record<string, TimingStrategy[]>>({});
  const [presetName, setPresetName] = useState("");

  useEffect(() => { try { setPresets(JSON.parse(localStorage.getItem(PRESETS_KEY) || "{}")); } catch { /* */ } }, []);
  const savePresets = (p: Record<string, TimingStrategy[]>) => { setPresets(p); localStorage.setItem(PRESETS_KEY, JSON.stringify(p)); };

  const set = (i: number, patch: Partial<TimingStrategy>) => setStrategies(strategies.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const add = () => setStrategies([...strategies, mk({ label: `Strategy ${strategies.length + 1}` })]);
  const remove = (i: number) => setStrategies(strategies.filter((_, j) => j !== i));

  const run = async () => {
    setBusy(true); setError(null);
    try { setRes(await api.runTiming({ symbol: "SPY", start, end, refresh, start_capital: capital, strategies })); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const num = (i: number, k: keyof TimingStrategy, label: string, step = 1) => (
    <div className="field"><label>{label}</label>
      <input type="number" step={step} value={strategies[i][k] as number} onChange={(e) => set(i, { [k]: +e.target.value || 0 } as Partial<TimingStrategy>)} /></div>
  );

  const params = (s: TimingStrategy, i: number) => {
    switch (s.strategy) {
      case "buy_hold": return <>{num(i, "exposure_in", "Exposure (1=100%)", 0.25)}</>;
      case "ma": return <>
        <div className="field"><label>MA</label><select value={s.ma_type} onChange={(e) => set(i, { ma_type: e.target.value })}><option value="sma">SMA</option><option value="ema">EMA</option></select></div>
        {num(i, "ma_period", "Period")}
        <div className="field"><label>Signal</label><select value={s.signal_freq} onChange={(e) => set(i, { signal_freq: e.target.value })}><option value="daily">daily</option><option value="monthly">monthly</option></select></div>
        {num(i, "band_pct", "Band %", 0.01)}{num(i, "exposure_in", "In-exposure", 0.25)}{num(i, "exposure_out", "Out-exposure", 0.25)}</>;
      case "golden_cross": return <>{num(i, "fast_period", "Fast MA")}{num(i, "slow_period", "Slow MA")}{num(i, "exposure_in", "In", 0.25)}{num(i, "exposure_out", "Out", 0.25)}</>;
      case "momentum": return <>{num(i, "mom_lookback", "Lookback (bars)")}
        <div className="field checkbox"><input id={`rm${i}`} type="checkbox" checked={s.require_ma} onChange={(e) => set(i, { require_ma: e.target.checked })} /><label htmlFor={`rm${i}`} style={{ margin: 0 }}>AND &gt; MA</label></div>
        {num(i, "ma_period", "MA period")}{num(i, "exposure_in", "In", 0.25)}{num(i, "exposure_out", "Out", 0.25)}</>;
      case "vol_target": return <>{num(i, "vol_target", "Target vol", 0.01)}{num(i, "vol_window", "Vol window")}{num(i, "vol_cap", "Max exposure", 0.25)}</>;
      case "vol_derisk": return <>{num(i, "vol_thr", "Vol threshold", 0.01)}{num(i, "vol_window", "Vol window")}{num(i, "derisk_exposure", "De-risk to", 0.1)}{num(i, "exposure_in", "Normal", 0.25)}</>;
      case "seasonal": return <>{num(i, "season_out_start", "Out month start")}{num(i, "season_out_end", "Out month end")}
        <div className="field checkbox"><input id={`sr${i}`} type="checkbox" checked={s.season_require_ma} onChange={(e) => set(i, { season_require_ma: e.target.checked })} /><label htmlFor={`sr${i}`} style={{ margin: 0 }}>only if &lt; 200-MA</label></div></>;
      case "dip": return <>{num(i, "dip_lookback", "High lookback")}{num(i, "dip_threshold", "Dip threshold", 0.02)}{num(i, "dip_base_exposure", "Base exposure", 0.1)}{num(i, "exposure_in", "On-dip", 0.25)}</>;
      default: return null;
    }
  };

  const tracks: TimingResult[] = res ? [res.baseline, ...res.results.filter((r) => !r.error)] : [];
  const colors = [PALETTE.benchmark, PALETTE.primary, PALETTE.accent, PALETTE.success, PALETTE.danger, "#f59e0b", "#f472b6"];
  const bCagr = res ? res.baseline.summary["CAGR"] : 0;

  return (
    <div className="scanner">
      <div className="card">
        <h3>SPY timing — buy &amp; sell (exposure) strategies</h3>
        <p className="hint">
          Lump-sum ${capital.toLocaleString()} in SPY (total return), long-only unless you set exposure &gt; 1 (leverage,
          charged 5.5% margin). Each strategy sets a daily target exposure from a rule; compared to buy-and-hold.
          Reminder from the studies: on raw return, only leverage beats B&amp;H (with bigger drawdowns) — the honest win
          is <em>risk-adjusted</em> (Sharpe/Calmar) via monthly trend-timing.
        </p>
        <div className="row">
          <div className="field"><label>Start</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div className="field"><label>End</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
          <div className="field"><label>Capital $</label><input type="number" value={capital} onChange={(e) => setCapital(+e.target.value || 0)} /></div>
          <div className="field checkbox"><input id="tm-ref" type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} /><label htmlFor="tm-ref" style={{ margin: 0 }}>Re-download</label></div>
        </div>

        <div className="section-title">Strategies</div>
        {strategies.map((s, i) => (
          <div key={i} className="opt-position" style={{ marginBottom: 8 }}>
            <div className="row">
              <div className="field" style={{ flex: 2 }}><label>Label</label><input value={s.label} onChange={(e) => set(i, { label: e.target.value })} /></div>
              <div className="field" style={{ flex: 2 }}><label>Type</label>
                <select value={s.strategy} onChange={(e) => set(i, { strategy: e.target.value })}>
                  {STRATS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            </div>
            <div className="row">{params(s, i)}
              <div className="field" style={{ display: "flex", alignItems: "flex-end" }}><button className="btn-inline" onClick={() => remove(i)}>Remove</button></div>
            </div>
          </div>
        ))}
        <button className="btn-inline" onClick={add}>+ Add strategy</button>

        <div className="section-title">Presets</div>
        <div className="row">
          <div className="field" style={{ flex: 2 }}><label>Name</label><input value={presetName} onChange={(e) => setPresetName(e.target.value)} /></div>
          <div className="field" style={{ display: "flex", alignItems: "flex-end" }}><button className="btn-inline" disabled={!presetName.trim()} onClick={() => savePresets({ ...presets, [presetName.trim()]: strategies })}>Save</button></div>
          <div className="field"><label>Load</label><select value="" onChange={(e) => { if (presets[e.target.value]) setStrategies(presets[e.target.value]); }}><option value="">—</option>{Object.keys(presets).map((n) => <option key={n} value={n}>{n}</option>)}</select></div>
        </div>

        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy} onClick={run}>{busy && <span className="spinner" />}{busy ? "Running…" : "Run"}</button>
      </div>

      {res && (
        <>
          <div className="card">
            <h3>Comparison (vs Buy &amp; Hold)</h3>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Metric</th>{tracks.map((t) => <th key={t.label}>{t.label}</th>)}</tr></thead>
                <tbody>
                  {SUMMARY_ORDER.map((k) => (
                    <tr key={k}>
                      <td style={{ color: "var(--text-muted)" }}>{k}</td>
                      {tracks.map((t) => {
                        const v = t.summary[k] ?? 0;
                        let cls = "";
                        if (t.label !== "Buy & Hold") {
                          if (k === "CAGR") cls = v > bCagr ? "pnl-pos" : "pnl-neg";
                          if (k === "Max Drawdown") cls = v > (res.baseline.summary[k] ?? 0) ? "pnl-pos" : "pnl-neg";
                        }
                        return <td key={t.label} className={cls}>{fmt(k, v)}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">Green CAGR = beats buy &amp; hold; green Max DD = shallower drop.</p>
          </div>

          <div className="card">
            <h3>Growth of ${capital.toLocaleString()} (log scale)</h3>
            <Plot height={380}
              data={tracks.map((t, i) => ({ x: t.dates, y: t.value, type: "scatter", mode: "lines", name: t.label, line: { color: colors[i % colors.length], width: t.label === "Buy & Hold" ? 2.4 : 1.5 } }))}
              layout={{ yaxis: { title: "Value ($)", type: "log" } }} />
          </div>

          <div className="card">
            <h3>Trade log</h3>
            <div className="tabs" style={{ borderBottom: "none", gap: 6, flexWrap: "wrap" }}>
              {tracks.map((t) => (
                <button key={t.label} className="btn-inline" onClick={() => setLogFor(logFor === t.label ? null : t.label)}>
                  {logFor === t.label ? "▾ " : "▸ "}{t.label} ({t.log.length})
                </button>
              ))}
            </div>
            {logFor && (() => {
              const t = tracks.find((x) => x.label === logFor); if (!t) return null;
              return (
                <div className="table-scroll" style={{ marginTop: 8, maxHeight: 360 }}>
                  <table>
                    <thead><tr><th>Date</th><th>Action</th><th>Price</th><th>From→To exp.</th><th>Trade $</th><th>Value</th></tr></thead>
                    <tbody>{t.log.map((e, i) => (
                      <tr key={i}><td>{e.date}</td><td className={e.action === "increase" ? "pnl-pos" : "pnl-neg"}>{e.action}</td>
                        <td>{usd(e.price)}</td><td>{dec(e.from_exposure)}→{dec(e.to_exposure)}</td><td>{usd(e.trade)}</td><td>{usd(e.value)}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              );
            })()}
          </div>
        </>
      )}
    </div>
  );
}

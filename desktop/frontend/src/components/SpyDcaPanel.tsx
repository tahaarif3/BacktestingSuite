import { useEffect, useState } from "react";
import { api } from "../api";
import type { DcaResponse, DcaResult, DcaScheme } from "../types";
import { usd, pct, dec } from "../format";
import Plot, { PALETTE } from "./Plot";

const PRESETS_KEY = "bt.dca.presets";
const CADENCES = ["weekly", "biweekly", "semimonthly", "monthly", "quarterly"];

const DEFAULT_SCHEMES: DcaScheme[] = [
  { label: "$300 / quarter", amount: 300, cadence: "quarterly", buy_rule: "always", ma_type: "sma", ma_period: 200, unused_cash: "accumulate", cash_yield_annual: 0, sell_rule: "none", sell_fraction: 1 },
  { label: "Only buy above 200-SMA", amount: 100, cadence: "monthly", buy_rule: "above_ma", ma_type: "sma", ma_period: 200, unused_cash: "accumulate", cash_yield_annual: 0, sell_rule: "none", sell_fraction: 1 },
  { label: "Buy dips below 200-SMA", amount: 100, cadence: "monthly", buy_rule: "below_ma", ma_type: "sma", ma_period: 200, unused_cash: "accumulate", cash_yield_annual: 0, sell_rule: "none", sell_fraction: 1 },
  { label: "De-risk below 200-SMA", amount: 100, cadence: "monthly", buy_rule: "always", ma_type: "sma", ma_period: 200, unused_cash: "accumulate", cash_yield_annual: 0.04, sell_rule: "below_ma", sell_fraction: 1 },
];

const SUMMARY_ORDER = ["Final Value", "Total Contributed", "Profit", "ROI on Contributions",
  "Money-Weighted Return (IRR)", "Max Drawdown", "Avg Time in Market", "Buys", "Sells"];

function fmt(k: string, v: number): string {
  if (["ROI on Contributions", "Money-Weighted Return (IRR)", "Max Drawdown", "Avg Time in Market"].includes(k)) return pct(v);
  if (["Final Value", "Total Contributed", "Profit"].includes(k)) return usd(v);
  if (["Buys", "Sells"].includes(k)) return String(Math.round(v));
  return dec(v);
}

export default function SpyDcaPanel() {
  const [start, setStart] = useState("2010-01-01");
  const [end, setEnd] = useState("2025-12-31");
  const [schemes, setSchemes] = useState<DcaScheme[]>(DEFAULT_SCHEMES);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<DcaResponse | null>(null);
  const [logFor, setLogFor] = useState<string | null>(null);
  const [presets, setPresets] = useState<Record<string, DcaScheme[]>>({});
  const [presetName, setPresetName] = useState("");

  useEffect(() => {
    try { setPresets(JSON.parse(localStorage.getItem(PRESETS_KEY) || "{}")); } catch { /* ignore */ }
  }, []);

  const savePresets = (p: Record<string, DcaScheme[]>) => {
    setPresets(p);
    localStorage.setItem(PRESETS_KEY, JSON.stringify(p));
  };

  const setScheme = (i: number, patch: Partial<DcaScheme>) =>
    setSchemes(schemes.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const addScheme = () =>
    setSchemes([...schemes, { ...DEFAULT_SCHEMES[0], label: `Scheme ${schemes.length + 1}` }]);
  const removeScheme = (i: number) => setSchemes(schemes.filter((_, j) => j !== i));

  const run = async () => {
    setBusy(true); setError(null);
    try {
      setRes(await api.runDca({ symbol: "SPY", start, end, refresh: false, schemes }));
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const tracks: DcaResult[] = res ? [res.baseline, ...res.results.filter((r) => !r.error), res.lump_sum] : [];
  const colors = [PALETTE.benchmark, PALETTE.primary, PALETTE.accent, PALETTE.success, PALETTE.danger, "#f59e0b", "#f472b6"];

  return (
    <div className="scanner">
      <div className="card">
        <h3>SPY long-term bankroll backtest</h3>
        <p className="hint">
          SPY only, long-only. Every scheme is compared against the <strong>$100/month baseline</strong>,
          plus a lump-sum reference. The goal isn't to out-trade the market — it's to see whether
          contribution timing and simple moving-average rules can beat plain monthly buying or cut
          drawdowns. Skipped contributions accumulate as dry powder and deploy when the rule allows.
        </p>
        <div className="row">
          <div className="field"><label>Start</label><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></div>
          <div className="field"><label>End</label><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></div>
        </div>

        <div className="section-title">Schemes</div>
        {schemes.map((s, i) => (
          <div key={i} className="opt-position" style={{ marginBottom: 8 }}>
            <div className="row">
              <div className="field" style={{ flex: 2 }}><label>Label</label><input value={s.label} onChange={(e) => setScheme(i, { label: e.target.value })} /></div>
              <div className="field"><label>Amount $</label><input type="number" value={s.amount} onChange={(e) => setScheme(i, { amount: +e.target.value || 0 })} /></div>
              <div className="field"><label>Cadence</label>
                <select value={s.cadence} onChange={(e) => setScheme(i, { cadence: e.target.value })}>
                  {CADENCES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="row">
              <div className="field"><label>Buy rule</label>
                <select value={s.buy_rule} onChange={(e) => setScheme(i, { buy_rule: e.target.value })}>
                  <option value="always">Always</option>
                  <option value="above_ma">Only above MA</option>
                  <option value="below_ma">Only below MA (dips)</option>
                </select>
              </div>
              <div className="field"><label>MA</label>
                <select value={s.ma_type} onChange={(e) => setScheme(i, { ma_type: e.target.value })}>
                  <option value="sma">SMA</option><option value="ema">EMA</option>
                </select>
              </div>
              <div className="field"><label>MA period</label><input type="number" value={s.ma_period} onChange={(e) => setScheme(i, { ma_period: +e.target.value || 1 })} /></div>
              <div className="field"><label>Unused cash</label>
                <select value={s.unused_cash} onChange={(e) => setScheme(i, { unused_cash: e.target.value })}>
                  <option value="accumulate">Accumulate</option><option value="skip">Skip</option>
                </select>
              </div>
            </div>
            <div className="row">
              <div className="field"><label>Sell rule</label>
                <select value={s.sell_rule} onChange={(e) => setScheme(i, { sell_rule: e.target.value })}>
                  <option value="none">None (never sell)</option>
                  <option value="below_ma">De-risk below MA</option>
                  <option value="above_ma">Trim above MA</option>
                </select>
              </div>
              <div className="field"><label>Sell fraction</label><input type="number" step="0.1" min="0" max="1" value={s.sell_fraction} onChange={(e) => setScheme(i, { sell_fraction: +e.target.value || 0 })} /></div>
              <div className="field"><label>Cash yield %/yr</label><input type="number" step="0.01" value={s.cash_yield_annual} onChange={(e) => setScheme(i, { cash_yield_annual: +e.target.value || 0 })} /></div>
              <div className="field" style={{ display: "flex", alignItems: "flex-end" }}>
                <button className="btn-inline" onClick={() => removeScheme(i)}>Remove</button>
              </div>
            </div>
          </div>
        ))}
        <button className="btn-inline" onClick={addScheme}>+ Add scheme</button>

        <div className="section-title">Presets</div>
        <div className="row">
          <div className="field" style={{ flex: 2 }}><label>Name</label><input value={presetName} onChange={(e) => setPresetName(e.target.value)} placeholder="my winning settings" /></div>
          <div className="field" style={{ display: "flex", alignItems: "flex-end" }}>
            <button className="btn-inline" disabled={!presetName.trim()} onClick={() => savePresets({ ...presets, [presetName.trim()]: schemes })}>Save</button>
          </div>
          <div className="field"><label>Load</label>
            <select value="" onChange={(e) => { if (presets[e.target.value]) setSchemes(presets[e.target.value]); }}>
              <option value="">—</option>
              {Object.keys(presets).map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
        </div>

        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy} onClick={run}>
          {busy && <span className="spinner" />}{busy ? "Running…" : "Run backtest"}
        </button>
      </div>

      {res && (
        <>
          <div className="card">
            <h3>Comparison</h3>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Metric</th>{tracks.map((t) => <th key={t.label}>{t.label}</th>)}</tr></thead>
                <tbody>
                  {SUMMARY_ORDER.map((k) => (
                    <tr key={k}>
                      <td style={{ color: "var(--text-muted)" }}>{k}</td>
                      {tracks.map((t) => {
                        const v = t.summary[k] ?? 0;
                        const beatsBase = k !== "Max Drawdown" ? v > (res.baseline.summary[k] ?? 0) : v > (res.baseline.summary[k] ?? 0);
                        const cls = t.label === "Baseline $100/mo" ? "" : beatsBase ? "pnl-pos" : "pnl-neg";
                        return <td key={t.label} className={["Final Value", "ROI on Contributions", "Money-Weighted Return (IRR)", "Max Drawdown"].includes(k) ? cls : ""}>{fmt(k, v)}</td>;
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="hint">Green = better than the $100/mo baseline (for Max Drawdown, higher = shallower drop).</p>
          </div>

          <div className="card">
            <h3>Portfolio value</h3>
            <Plot
              height={380}
              data={tracks.map((t, i) => ({ x: t.dates, y: t.value, type: "scatter", mode: "lines", name: t.label, line: { color: colors[i % colors.length], width: t.label.startsWith("Baseline") ? 2.4 : 1.6, dash: t.label.startsWith("Lump") ? "dot" : undefined } }))}
              layout={{ yaxis: { title: "Value ($)" } }}
            />
          </div>

          <div className="card">
            <h3>Trade log</h3>
            <div className="tabs" style={{ borderBottom: "none", gap: 6, flexWrap: "wrap" }}>
              {tracks.map((t) => (
                <button key={t.label} className={`btn-inline ${logFor === t.label ? "" : ""}`} onClick={() => setLogFor(logFor === t.label ? null : t.label)}>
                  {logFor === t.label ? "▾ " : "▸ "}{t.label} ({t.log.length})
                </button>
              ))}
            </div>
            {logFor && (() => {
              const t = tracks.find((x) => x.label === logFor);
              if (!t) return null;
              return (
                <div className="table-scroll" style={{ marginTop: 8, maxHeight: 360 }}>
                  <table>
                    <thead><tr><th>Date</th><th>Action</th><th>Price</th><th>Cash</th><th>Shares Δ</th><th>Shares after</th><th>Value</th></tr></thead>
                    <tbody>
                      {t.log.map((e, i) => (
                        <tr key={i}>
                          <td>{e.date}</td>
                          <td className={e.action === "buy" ? "pnl-pos" : "pnl-neg"}>{e.action}</td>
                          <td>{usd(e.price)}</td>
                          <td>{usd(e.cash)}</td>
                          <td>{dec(e.shares)}</td>
                          <td>{dec(e.shares_after)}</td>
                          <td>{usd(e.value)}</td>
                        </tr>
                      ))}
                    </tbody>
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

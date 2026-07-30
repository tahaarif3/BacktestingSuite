import { useEffect, useState } from "react";
import { api } from "../api";
import type { ScreenResult } from "../types";
import { pct, usd } from "../format";

interface Props {
  onBacktest: (file: string, symbol: string) => void;
  onReplay: (file: string, symbol: string) => void;
}

export default function ScannerPanel({ onBacktest, onReplay }: Props) {
  const [tickersText, setTickersText] = useState("");
  const [start, setStart] = useState("2019-01-01");
  const [end, setEnd] = useState("2024-12-31");
  const [window, setWindow] = useState(60);
  const [refresh, setRefresh] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<ScreenResult[] | null>(null);
  const [errors, setErrors] = useState<{ symbol: string; error: string }[]>([]);
  const [asOf, setAsOf] = useState<string>("");

  useEffect(() => {
    api.getWatchlist().then((t) => setTickersText(t.join(", "))).catch(() => {});
  }, []);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const tickers = tickersText
        .split(/[\s,]+/)
        .map((t) => t.trim().toUpperCase())
        .filter(Boolean);
      const res = await api.scanScreener({
        tickers: tickers.length ? tickers : null,
        start,
        end,
        interval: "1d",
        window,
        refresh,
      });
      setResults(res.results);
      setErrors(res.errors);
      setAsOf(res.as_of);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="scanner">
      <div className="card">
        <h3>Relative-Strength Breakout scanner</h3>
        <p className="hint">
          Scans a basket for the RS-Breakout setup and ranks which names have the regime
          <strong> armed now</strong>, are <strong>currently long</strong>, or fired most recently.
          The first run downloads daily data for each symbol (and refreshes SPY) — that can take a
          minute. Then click <strong>Backtest</strong> or <strong>Replay</strong> to trade any hit.
        </p>

        <div className="field">
          <label>Watchlist (comma or space separated)</label>
          <textarea
            rows={2}
            value={tickersText}
            onChange={(e) => setTickersText(e.target.value)}
            placeholder="AAPL, MSFT, NVDA, ..."
          />
        </div>
        <div className="row">
          <div className="field">
            <label>Start</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>End (as-of)</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="field">
            <label>Recent window (bars)</label>
            <input type="number" min={5} value={window} onChange={(e) => setWindow(parseInt(e.target.value || "60", 10))} />
          </div>
        </div>
        <div className="field checkbox">
          <input id="scan-refresh" type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} />
          <label htmlFor="scan-refresh" style={{ margin: 0 }}>
            Re-download data so "armed now" is current (uncheck to reuse cache)
          </label>
        </div>

        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={busy} onClick={run}>
          {busy && <span className="spinner" />}
          {busy ? "Scanning…" : "Run scan"}
        </button>
      </div>

      {results && (
        <div className="card">
          <h3>
            Results — {results.length} ranked{asOf ? `, as of ${asOf}` : ""}
          </h3>
          {results.length === 0 && <div className="hint">No symbols scanned successfully.</div>}
          {results.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Status</th>
                    <th>Entries (recent / total)</th>
                    <th>RS now</th>
                    <th>Last close</th>
                    <th>As of</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r) => (
                    <tr key={r.symbol} className={r.armed_now ? "row-armed" : ""}>
                      <td><strong>{r.symbol}</strong></td>
                      <td>
                        <div className="scan-badges">
                          {r.armed_now && <span className="regime-tag armed">armed</span>}
                          {r.long_now && <span className="regime-tag on">long</span>}
                          {r.fresh_entry && <span className="regime-tag on">fresh entry</span>}
                          {!r.armed_now && !r.long_now && (
                            <span className="regime-tag">
                              {r.last_entry_bars_ago != null ? `${r.last_entry_bars_ago} bars since entry` : "no setup"}
                            </span>
                          )}
                          {r.warning && <span className="warn-tag">no SPY</span>}
                        </div>
                      </td>
                      <td>{r.entries_in_window} / {r.total_entries}</td>
                      <td className={r.rs_now >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(r.rs_now)}</td>
                      <td>{usd(r.last_close)}</td>
                      <td>{r.last_date ?? "—"}</td>
                      <td>
                        <div className="scan-actions">
                          <button className="btn-inline" onClick={() => onBacktest(r.file, r.symbol)}>Backtest</button>
                          <button className="btn-inline" onClick={() => onReplay(r.file, r.symbol)}>Replay</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {errors.length > 0 && (
            <p className="hint">
              Skipped: {errors.map((e) => `${e.symbol} (${e.error})`).join("; ")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

import { useEffect, useState } from "react";
import { api } from "../../api";
import type { OptionStructureConfig, OptionStructureMeta, PortfolioSessionConfig, VolModelConfig } from "../../types";
import OptionsConfig, { DEFAULT_OPTION_STRUCTURE, DEFAULT_VOL } from "../options/OptionsConfig";

interface Props {
  onStart: (config: PortfolioSessionConfig, defaultStructure: OptionStructureConfig) => void;
  loading: boolean;
  error: string | null;
}

export default function PortfolioSetup({ onStart, loading, error }: Props) {
  const [tickersText, setTickersText] = useState("");
  const [start, setStart] = useState("2019-01-01");
  const [end, setEnd] = useState("2024-12-31");
  const [capital, setCapital] = useState(100000);
  const [timing, setTiming] = useState("next_close");
  const [warmup, setWarmup] = useState(150);
  const [refresh, setRefresh] = useState(true);
  const [structure, setStructure] = useState<OptionStructureConfig>({ ...DEFAULT_OPTION_STRUCTURE, structure_type: "bull_put_spread" });
  const [vol, setVol] = useState<VolModelConfig>(DEFAULT_VOL);
  const [structures, setStructures] = useState<OptionStructureMeta[]>([]);

  useEffect(() => {
    api.getWatchlist().then((t) => setTickersText(t.join(", "))).catch(() => {});
    api.listOptionStructures().then(setStructures).catch(() => {});
  }, []);

  const build = (): PortfolioSessionConfig => {
    const tickers = tickersText.split(/[\s,]+/).map((t) => t.trim().toUpperCase()).filter(Boolean);
    return {
      tickers: tickers.length ? tickers : null,
      start,
      end,
      capital,
      timing,
      warmup_bars: warmup,
      refresh,
      vol,
    };
  };

  return (
    <div className="replay-setup">
      <div className="card setup-card">
        <h3>New portfolio replay</h3>
        <p className="hint">
          Replay the market on SPY's clock while a live scanner tracks your watchlist. Playback pauses
          when a name fires the RS-Breakout signal — click it in the radar to chart it and open an
          options trade on <strong>one shared cash account</strong>. The first run downloads daily data
          for every symbol (and refreshes SPY); that can take a minute.
        </p>

        <div className="field">
          <label>Watchlist (comma or space separated)</label>
          <textarea rows={2} value={tickersText} onChange={(e) => setTickersText(e.target.value)} />
        </div>
        <div className="row">
          <div className="field">
            <label>Start</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>End</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
        </div>
        <div className="row">
          <div className="field">
            <label>Capital ($)</label>
            <input type="number" value={capital} onChange={(e) => setCapital(parseFloat(e.target.value || "0"))} />
          </div>
          <div className="field">
            <label>Timing</label>
            <select value={timing} onChange={(e) => setTiming(e.target.value)}>
              <option value="next_open">Next open</option>
              <option value="next_close">Next close</option>
            </select>
          </div>
          <div className="field">
            <label>Warm-up bars</label>
            <input type="number" value={warmup} onChange={(e) => setWarmup(parseInt(e.target.value || "0", 10))} />
          </div>
        </div>
        <div className="field checkbox">
          <input id="pf-refresh" type="checkbox" checked={refresh} onChange={(e) => setRefresh(e.target.checked)} />
          <label htmlFor="pf-refresh" style={{ margin: 0 }}>Re-download data so the radar is current</label>
        </div>

        <div className="section-title">Default option structure</div>
        <OptionsConfig structures={structures} value={structure} onChange={setStructure} vol={vol} onVolChange={setVol} />

        {error && <div className="error">{error}</div>}
        <button className="btn btn-primary" disabled={loading} onClick={() => onStart(build(), structure)}>
          {loading && <span className="spinner" />}
          Start portfolio replay
        </button>
      </div>
    </div>
  );
}

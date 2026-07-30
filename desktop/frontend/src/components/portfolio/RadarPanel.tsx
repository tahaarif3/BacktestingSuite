import type { RadarRow } from "../../types";
import { pct, usd } from "../../format";

interface Props {
  radar: RadarRow[];
  selected: string | null;
  onSelect: (symbol: string) => void;
}

export default function RadarPanel({ radar, selected, onSelect }: Props) {
  const fired = radar.filter((r) => r.fresh_entry).length;
  return (
    <div className="radar">
      <div className="rail-section-title">
        Scanner radar {fired > 0 && <span className="badge">{fired} fired</span>}
      </div>
      <div className="radar-list">
        {radar.map((r) => (
          <button
            key={r.symbol}
            className={`radar-row ${selected === r.symbol ? "sel" : ""} ${r.fresh_entry ? "fired" : ""}`}
            onClick={() => onSelect(r.symbol)}
            disabled={!r.available}
            title={r.available ? "Chart & trade this name" : "Not yet listed at this date"}
          >
            <span className="radar-sym">{r.symbol}</span>
            <span className="radar-badges">
              {r.fresh_entry && <span className="regime-tag armed">fired</span>}
              {!r.fresh_entry && r.long && <span className="regime-tag on">long</span>}
              {!r.long && r.armed && <span className="regime-tag on">armed</span>}
              {!r.armed && !r.long && r.available && <span className="regime-tag">—</span>}
              {!r.available && <span className="regime-tag">n/a</span>}
            </span>
            <span className={`radar-rs ${r.rs >= 0 ? "pnl-pos" : "pnl-neg"}`}>{pct(r.rs)}</span>
            <span className="radar-px">{r.close != null ? usd(r.close) : "—"}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

import type { CompareRun } from "../types";
import { METRIC_FORMAT } from "../format";
import Plot from "./Plot";

interface Props {
  runs: CompareRun[];
  onClear: () => void;
  onRemove: (index: number) => void;
}

const CURVE_COLORS = ["#38bdf8", "#a78bfa", "#34d399", "#f472b6", "#fbbf24", "#f87171"];

export default function ComparePanel({ runs, onClear, onRemove }: Props) {
  if (runs.length === 0) {
    return <div className="empty">Add runs with “Add to Compare” to see them side by side.</div>;
  }

  const metricKeys = Object.keys(METRIC_FORMAT);

  return (
    <div>
      <div className="card">
        <h3>
          Equity Curves ({runs.length})
          <button className="btn btn-secondary" style={{ width: "auto", float: "right", padding: "4px 12px" }} onClick={onClear}>
            Clear all
          </button>
        </h3>
        <Plot
          height={380}
          data={runs.map((r, i) => ({
            x: r.dates,
            y: r.equity,
            type: "scatter",
            mode: "lines",
            name: r.label,
            line: { color: CURVE_COLORS[i % CURVE_COLORS.length], width: 2 },
          }))}
          layout={{ yaxis: { title: "Equity ($)" } }}
        />
      </div>

      <div className="card">
        <h3>Metrics</h3>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {runs.map((r, i) => (
                  <th key={i}>
                    {r.label}{" "}
                    <span
                      style={{ cursor: "pointer", color: "var(--danger)" }}
                      onClick={() => onRemove(i)}
                      title="Remove run"
                    >
                      ✕
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {metricKeys.map((k) => (
                <tr key={k}>
                  <td style={{ color: "var(--text-muted)" }}>{k}</td>
                  {runs.map((r, i) => (
                    <td key={i}>{METRIC_FORMAT[k].fmt(r.summary[k] ?? 0)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

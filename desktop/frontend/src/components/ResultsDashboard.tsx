import type { BacktestResult } from "../types";
import { METRIC_FORMAT, metricTone } from "../format";
import MetricCard from "./MetricCard";
import TradeTable from "./TradeTable";
import Plot, { PALETTE } from "./Plot";

export default function ResultsDashboard({ result }: { result: BacktestResult | null }) {
  if (!result) {
    return <div className="empty">Configure a strategy and click “Run Backtest” to see results.</div>;
  }

  const s = result.series;
  const tone = metricTone;

  return (
    <div>
      <div className="metrics">
        {Object.entries(result.summary).map(([k, v]) => {
          const meta = METRIC_FORMAT[k];
          return <MetricCard key={k} label={k} value={meta ? meta.fmt(v) : String(v)} tone={tone(k, v)} />;
        })}
      </div>

      <div className="card">
        <h3>Equity Curve vs. Buy &amp; Hold Benchmark</h3>
        <Plot
          height={360}
          data={[
            { x: s.dates, y: s.equity, type: "scatter", mode: "lines", name: result.strategy_name, line: { color: PALETTE.primary, width: 2 } },
            { x: s.dates, y: s.benchmark, type: "scatter", mode: "lines", name: "Benchmark", line: { color: PALETTE.benchmark, width: 1.5, dash: "dot" } },
          ]}
          layout={{ yaxis: { title: "Equity ($)" } }}
        />
      </div>

      <div className="card">
        <h3>Drawdown</h3>
        <Plot
          height={240}
          data={[
            { x: s.dates, y: s.drawdown.map((d) => d * 100), type: "scatter", mode: "lines", name: "Drawdown", fill: "tozeroy", line: { color: PALETTE.danger, width: 1 }, fillcolor: "rgba(248,113,113,0.15)" },
          ]}
          layout={{ yaxis: { title: "Drawdown (%)" } }}
        />
      </div>

      <div className="card">
        <h3>Rolling Annualized Return (21d)</h3>
        <Plot
          height={240}
          data={[
            { x: s.dates, y: s.rolling_returns.map((d) => d * 100), type: "scatter", mode: "lines", name: "Rolling return", line: { color: PALETTE.accent, width: 1.5 } },
          ]}
          layout={{ yaxis: { title: "Ann. return (%)" } }}
        />
      </div>

      <div className="card">
        <h3>Trade Log ({result.trades.length})</h3>
        <TradeTable trades={result.trades} />
      </div>
    </div>
  );
}

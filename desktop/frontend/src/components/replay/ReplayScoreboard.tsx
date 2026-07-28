import type { JournalEntry, ReplayScore } from "../../types";
import { METRIC_FORMAT, metricTone, usd } from "../../format";
import MetricCard from "../MetricCard";
import TradeTable from "../TradeTable";
import Plot, { PALETTE } from "../Plot";
import DecisionJournal from "./DecisionJournal";

interface Props {
  score: ReplayScore;
  journal: JournalEntry[];
  intraday: boolean;
  onResume: () => void;
  onNewSession: () => void;
}

const METRIC_KEYS = Object.keys(METRIC_FORMAT);

export default function ReplayScoreboard({ score, journal, intraday, onResume, onNewSession }: Props) {
  const tracks: { key: "user" | "algo" | "buy_hold"; label: string }[] = [
    { key: "user", label: "You" },
    { key: "algo", label: "Algo" },
    { key: "buy_hold", label: "Buy & Hold" },
  ];

  const b = score.behaviour;
  const overridePnl = score.delta.vs_algo["Total Return"];

  return (
    <div className="replay-scoreboard">
      <div className="scoreboard-actions">
        <button className="btn-inline" onClick={onResume}>
          ← Back to replay
        </button>
        <button className="btn-inline" onClick={onNewSession}>
          New session
        </button>
      </div>

      <h3 style={{ margin: "8px 0 12px" }}>Your results</h3>
      <div className="metrics">
        {METRIC_KEYS.map((k) => {
          const v = score.user.summary[k] ?? 0;
          return <MetricCard key={k} label={k} value={METRIC_FORMAT[k].fmt(v)} tone={metricTone(k, v)} />;
        })}
      </div>

      <div className="card insight">
        You followed the algo on{" "}
        <strong>
          {b.signals_followed} / {b.signals_shown}
        </strong>{" "}
        signals ({(b.follow_rate * 100).toFixed(0)}%), faded {b.signals_faded}, ignored {b.signals_ignored}, and
        made {b.unprompted_orders} discretionary trades. Your total return was{" "}
        <strong className={overridePnl >= 0 ? "pnl-pos" : "pnl-neg"}>
          {(overridePnl * 100).toFixed(2)}%
        </strong>{" "}
        vs. following the algo.
      </div>

      {score.fairness.note && <div className="error">{score.fairness.note}</div>}

      <div className="card">
        <h3>Equity: You vs Algo vs Buy &amp; Hold</h3>
        <Plot
          height={360}
          data={[
            { x: score.user.series.dates, y: score.user.series.equity, type: "scatter", mode: "lines", name: "You", line: { color: PALETTE.primary, width: 2 } },
            { x: score.algo.series.dates, y: score.algo.series.equity, type: "scatter", mode: "lines", name: "Algo", line: { color: PALETTE.accent, width: 1.5 } },
            { x: score.buy_hold.series.dates, y: score.buy_hold.series.equity, type: "scatter", mode: "lines", name: "Buy & Hold", line: { color: PALETTE.benchmark, width: 1.5, dash: "dot" } },
          ]}
          layout={{ yaxis: { title: "Equity ($)" } }}
        />
      </div>

      <div className="card">
        <h3>Comparison</h3>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Metric</th>
                {tracks.map((t) => (
                  <th key={t.key}>{t.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {METRIC_KEYS.map((k) => (
                <tr key={k}>
                  <td style={{ color: "var(--text-muted)" }}>{k}</td>
                  {tracks.map((t) => {
                    const v = score[t.key].summary[k] ?? 0;
                    return (
                      <td key={t.key} className={t.key === "user" ? metricTone(k, v).replace("pos", "pnl-pos").replace("neg", "pnl-neg").replace("neutral", "") : ""}>
                        {METRIC_FORMAT[k].fmt(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>Fairness</h3>
        <div className="hint">
          Algo minimum cash: {usd(score.fairness.algo_min_cash)} · leverage used:{" "}
          {score.fairness.algo_used_leverage ? "yes" : "no"} · your margin policy:{" "}
          {score.fairness.user_margin_policy}
        </div>
      </div>

      <div className="card">
        <h3>Your trade log ({score.user.trades.length})</h3>
        <TradeTable trades={score.user.trades} />
      </div>

      <div className="card">
        <h3>Decision journal</h3>
        <DecisionJournal entries={journal} intraday={intraday} />
      </div>
    </div>
  );
}

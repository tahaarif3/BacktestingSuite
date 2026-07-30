import type { PortfolioScore } from "../../types";
import { pct, usd } from "../../format";
import MetricCard from "../MetricCard";
import Plot, { PALETTE } from "../Plot";

interface Props {
  score: PortfolioScore;
  onResume: () => void;
  onNewSession: () => void;
}

export default function PortfolioScoreboard({ score, onResume, onNewSession }: Props) {
  return (
    <div className="replay-scoreboard">
      <div className="scoreboard-actions">
        <button className="btn-inline" onClick={onResume}>← Back to replay</button>
        <button className="btn-inline" onClick={onNewSession}>New session</button>
      </div>

      <h3 style={{ margin: "8px 0 12px" }}>Portfolio results</h3>
      <div className="metrics">
        <MetricCard label="Total Return" value={pct(score.total_return)} tone={score.total_return >= 0 ? "pos" : "neg"} />
        <MetricCard label="Net Liq" value={usd(score.final_equity)} tone="neutral" />
        <MetricCard label="Realized P&L" value={usd(score.realized_pnl)} tone={score.realized_pnl >= 0 ? "pos" : "neg"} />
        <MetricCard label="Unrealized P&L" value={usd(score.unrealized_pnl)} tone={score.unrealized_pnl >= 0 ? "pos" : "neg"} />
        <MetricCard label="Win Rate" value={pct(score.win_rate)} tone="neutral" />
        <MetricCard label="Trades" value={String(score.total_trades)} tone="neutral" />
      </div>

      {score.warnings.map((w, i) => (
        <div key={i} className="card insight">{w}</div>
      ))}

      <div className="card">
        <h3>Portfolio equity vs SPY buy &amp; hold</h3>
        <Plot
          height={360}
          data={[
            { x: score.dates, y: score.equity, type: "scatter", mode: "lines", name: "You", line: { color: PALETTE.primary, width: 2 } },
            { x: score.dates, y: score.benchmark, type: "scatter", mode: "lines", name: "SPY B&H", line: { color: PALETTE.benchmark, width: 1.5, dash: "dot" } },
          ]}
          layout={{ yaxis: { title: "Equity ($)" } }}
        />
      </div>

      <div className="card">
        <h3>Option trades ({score.trades.length})</h3>
        {score.trades.length === 0 ? (
          <div className="hint">No closed trades yet.</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Symbol</th><th>Structure</th><th>Qty</th><th>P&L</th><th>% risk</th><th>Outcome</th></tr>
              </thead>
              <tbody>
                {score.trades.map((t, i) => (
                  <tr key={i}>
                    <td><strong>{t.symbol}</strong></td>
                    <td>{t.structure.replace(/_/g, " ")}</td>
                    <td>{t.contracts}</td>
                    <td className={t.pnl_usd >= 0 ? "pnl-pos" : "pnl-neg"}>{usd(t.pnl_usd)}</td>
                    <td className={t.pnl_pct >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(t.pnl_pct)}</td>
                    <td>{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

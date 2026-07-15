import type { RobustnessResult } from "../types";
import { dec, pct, usd } from "../format";
import Plot from "./Plot";

export default function RobustnessPanel({ result }: { result: RobustnessResult | null }) {
  if (!result) {
    return <div className="empty">Click “Run Robustness” to validate the current configuration.</div>;
  }

  const tt = result.train_test;
  const wf = result.walk_forward;
  const mc = result.monte_carlo;
  const cs = result.cost_sensitivity;

  return (
    <div>
      {tt && (
        <div className="card">
          <h3>
            Train / Test Split (70 / 30)
            {tt.warning && <span className="warn-tag">Decay</span>}
          </h3>
          <div className="metrics">
            <div className="metric-card neutral"><div className="label">In-Sample Sharpe</div><div className="value">{dec(tt.is_sharpe)}</div></div>
            <div className="metric-card neutral"><div className="label">Out-of-Sample Sharpe</div><div className="value">{dec(tt.oos_sharpe)}</div></div>
            <div className="metric-card neutral"><div className="label">Decay Ratio</div><div className="value">{dec(tt.decay)}</div></div>
          </div>
        </div>
      )}

      {wf && (
        <div className="card">
          <h3>
            Walk-Forward Analysis
            {wf.warning && <span className="warn-tag">Overfit risk</span>}
          </h3>
          {wf.skipped ? (
            <div className="hint">{wf.reason}</div>
          ) : (
            <>
              <div className="metrics">
                <div className="metric-card neutral"><div className="label">Walk-Forward Efficiency</div><div className="value">{dec(wf.wfe ?? 0)}</div></div>
                <div className="metric-card neutral"><div className="label">Avg In-Sample Sharpe</div><div className="value">{dec(wf.avg_is_sharpe ?? 0)}</div></div>
                <div className="metric-card neutral"><div className="label">OOS Sharpe</div><div className="value">{dec(wf.oos_sharpe ?? 0)}</div></div>
              </div>
              {wf.windows && wf.windows.length > 0 && (
                <Plot
                  height={260}
                  data={[
                    { x: wf.windows.map((w) => w.window), y: wf.windows.map((w) => w.train_sharpe), type: "bar", name: "Train Sharpe" },
                    { x: wf.windows.map((w) => w.window), y: wf.windows.map((w) => w.test_sharpe), type: "bar", name: "Test Sharpe" },
                  ]}
                  layout={{ barmode: "group", xaxis: { title: "Window" }, yaxis: { title: "Sharpe" } }}
                />
              )}
            </>
          )}
        </div>
      )}

      {mc && (
        <div className="card">
          <h3>Monte Carlo (Trade Shuffling)</h3>
          {mc.skipped ? (
            <div className="hint">{mc.reason}</div>
          ) : (
            <div className="metrics">
              <div className="metric-card neg"><div className="label">Probability of Ruin</div><div className="value">{pct(mc.probability_of_ruin ?? 0)}</div></div>
              <div className="metric-card neutral"><div className="label">Median Max Drawdown</div><div className="value">{pct(mc.median_max_drawdown ?? 0)}</div></div>
              <div className="metric-card neutral"><div className="label">95% Drawdown VaR</div><div className="value">{pct(mc.drawdown_95th_percentile ?? 0)}</div></div>
              <div className="metric-card pos"><div className="label">Median Final Equity</div><div className="value">{usd(mc.median_final_equity ?? 0)}</div></div>
            </div>
          )}
        </div>
      )}

      {cs && (
        <div className="card">
          <h3>Cost Sensitivity — Sharpe Heatmap</h3>
          <Plot
            height={360}
            data={[
              {
                type: "heatmap",
                z: cs.sharpe_matrix,
                x: cs.slippage_grid.map((s) => `${(s * 100).toFixed(3)}%`),
                y: cs.commission_grid.map((c) => `${(c * 100).toFixed(3)}%`),
                colorscale: "RdYlGn",
                showscale: true,
              },
            ]}
            layout={{ xaxis: { title: "Slippage" }, yaxis: { title: "Commission" } }}
          />
        </div>
      )}
    </div>
  );
}

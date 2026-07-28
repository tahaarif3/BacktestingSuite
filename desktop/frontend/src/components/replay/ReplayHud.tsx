import type { ReplayAccount } from "../../types";
import { usd } from "../../format";
import MetricCard from "../MetricCard";
import Sparkline from "../Sparkline";
import { PALETTE } from "../Plot";

interface Props {
  symbol: string;
  interval: string;
  dateLabel: string;
  cursor: number;
  startIndex: number;
  totalBars: number;
  account: ReplayAccount | null;
  equityTail: number[];
  capital: number;
  reviewing: boolean;
}

export default function ReplayHud(props: Props) {
  const { symbol, interval, dateLabel, cursor, startIndex, totalBars, account, equityTail, capital, reviewing } = props;
  const progress = totalBars > 1 ? ((cursor - startIndex) / (totalBars - 1 - startIndex)) * 100 : 0;

  const posTone = account && account.position > 0 ? "pos" : account && account.position < 0 ? "neg" : "neutral";
  const uTone = account && account.unrealized_pnl >= 0 ? "pos" : "neg";
  const rTone = account && account.realized_pnl >= 0 ? "pos" : "neg";

  return (
    <div className="replay-hud">
      <div className="replay-hud-top">
        <div className="hud-symbol">
          <span className="hud-ticker">{symbol}</span>
          <span className="pill">{interval}</span>
          {reviewing && <span className="warn-tag">reviewing history</span>}
        </div>
        <div className="hud-date">{dateLabel}</div>
        <div className="hud-progress">
          <div className="hud-barcount">
            bar {cursor.toLocaleString()} / {(totalBars - 1).toLocaleString()}
          </div>
          <div className="progress">
            <div className="progress-bar" style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} />
          </div>
        </div>
        <div className="hud-spark">
          <Sparkline
            series={[{ values: equityTail.length ? equityTail : [capital, capital], color: PALETTE.primary, label: "You" }]}
            baseline={capital}
            height={44}
            width={180}
          />
          <div className="hint">equity (mark-to-close)</div>
        </div>
      </div>

      <div className="metrics replay-metrics">
        <MetricCard label="Cash" value={account ? usd(account.cash) : "—"} tone="neutral" />
        <MetricCard
          label="Position"
          value={account ? `${account.position.toFixed(2)} sh` : "—"}
          tone={posTone as "pos" | "neg" | "neutral"}
        />
        <MetricCard label="Avg entry" value={account && account.position ? usd(account.avg_price) : "—"} tone="neutral" />
        <MetricCard label="Unrealized P&L" value={account ? usd(account.unrealized_pnl) : "—"} tone={uTone as "pos" | "neg"} />
        <MetricCard label="Realized P&L" value={account ? usd(account.realized_pnl) : "—"} tone={rTone as "pos" | "neg"} />
        <MetricCard label="Equity" value={account ? usd(account.equity) : "—"} tone="neutral" />
      </div>
    </div>
  );
}

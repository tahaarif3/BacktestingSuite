import type { OptionsAccount } from "../../types";
import { usd, dec } from "../../format";
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
  account: OptionsAccount | null;
  equityTail: number[];
  capital: number;
  reviewing: boolean;
}

export default function OptionsHud(props: Props) {
  const { symbol, interval, dateLabel, cursor, startIndex, totalBars, account, equityTail, capital, reviewing } = props;
  const progress = totalBars > 1 ? ((cursor - startIndex) / (totalBars - 1 - startIndex)) * 100 : 0;
  const uTone = account && account.unrealized_pnl >= 0 ? "pos" : "neg";
  const rTone = account && account.realized_pnl >= 0 ? "pos" : "neg";

  return (
    <div className="replay-hud">
      <div className="replay-hud-top">
        <div className="hud-symbol">
          <span className="hud-ticker">{symbol}</span>
          <span className="pill">{interval}</span>
          <span className="pill">options</span>
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
          <div className="hint">net liq (mark-to-close)</div>
        </div>
      </div>

      <div className="metrics replay-metrics">
        <MetricCard label="Cash" value={account ? usd(account.cash) : "—"} tone="neutral" />
        <MetricCard label="Net Liq" value={account ? usd(account.net_liq) : "—"} tone="neutral" />
        <MetricCard label="Unrealized P&L" value={account ? usd(account.unrealized_pnl) : "—"} tone={uTone as "pos" | "neg"} />
        <MetricCard label="Realized P&L" value={account ? usd(account.realized_pnl) : "—"} tone={rTone as "pos" | "neg"} />
        <MetricCard label="Max Risk" value={account ? usd(account.max_risk) : "—"} tone="neutral" />
        <MetricCard label="Net Δ" value={account ? dec(account.net_delta) : "—"} tone="neutral" />
        <MetricCard label="Net Θ / day" value={account ? usd(account.net_theta) : "—"} tone="neutral" />
        <MetricCard label="Net Vega" value={account ? usd(account.net_vega) : "—"} tone="neutral" />
      </div>
    </div>
  );
}

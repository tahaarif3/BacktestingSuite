import type { OptionTrade } from "../../types";
import { usd, pct } from "../../format";

interface Props {
  trades: OptionTrade[];
}

export default function OptionTradeTable({ trades }: Props) {
  if (trades.length === 0) return <div className="hint">No option trades yet.</div>;
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Opened</th>
            <th>Closed</th>
            <th>Structure</th>
            <th>Qty</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>P&L</th>
            <th>% risk</th>
            <th>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              <td>{t.entry_time}</td>
              <td>{t.exit_time}</td>
              <td>{t.structure.replace(/_/g, " ")}</td>
              <td>{t.contracts}</td>
              <td>{usd(t.entry_cash)}</td>
              <td>{usd(t.exit_cash)}</td>
              <td className={t.pnl_usd >= 0 ? "pnl-pos" : "pnl-neg"}>{usd(t.pnl_usd)}</td>
              <td className={t.pnl_pct >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(t.pnl_pct)}</td>
              <td>{t.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

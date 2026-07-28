import type { ReplayFill } from "../../types";
import { usd } from "../../format";

export default function FillsList({ fills, intraday }: { fills: ReplayFill[]; intraday: boolean }) {
  if (!fills.length) return <div className="hint">No trades yet.</div>;
  const recent = fills.filter((f) => !f.no_op).slice(-8).reverse();
  const fmt = (t: number | string) =>
    typeof t === "number"
      ? new Date(t * 1000).toLocaleString(undefined, intraday ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric" })
      : String(t);

  return (
    <div className="fills-list">
      {recent.map((f, i) => (
        <div key={`${f.order_id}-${i}`} className="fill-row">
          <span className={f.trade_shares >= 0 ? "dir-long" : "dir-short"}>
            {f.trade_shares >= 0 ? "BUY" : "SELL"} {Math.abs(f.trade_shares).toFixed(1)}
          </span>
          <span>@ {usd(f.exec_price)}</span>
          <span className="hint">{fmt(f.t)}</span>
        </div>
      ))}
    </div>
  );
}

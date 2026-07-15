import { useMemo, useState } from "react";
import type { Trade } from "../types";
import { pct, usd } from "../format";

type SortKey = keyof Trade;

export default function TradeTable({ trades }: { trades: Trade[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("exit_time");
  const [asc, setAsc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...trades];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av < bv) return asc ? -1 : 1;
      if (av > bv) return asc ? 1 : -1;
      return 0;
    });
    return copy;
  }, [trades, sortKey, asc]);

  const toggle = (k: SortKey) => {
    if (k === sortKey) setAsc(!asc);
    else {
      setSortKey(k);
      setAsc(false);
    }
  };

  const cols: [SortKey, string][] = [
    ["entry_time", "Entry"],
    ["exit_time", "Exit"],
    ["direction", "Dir"],
    ["size", "Size"],
    ["entry_price", "Entry Px"],
    ["exit_price", "Exit Px"],
    ["pnl_usd", "PnL ($)"],
    ["pnl_pct", "PnL (%)"],
    ["duration_days", "Days"],
  ];

  if (trades.length === 0) return <div className="empty">No trades executed.</div>;

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {cols.map(([k, label]) => (
              <th key={k} onClick={() => toggle(k)}>
                {label}
                {sortKey === k ? (asc ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((t, i) => (
            <tr key={i}>
              <td>{t.entry_time}</td>
              <td>{t.exit_time}</td>
              <td className={t.direction === "Long" ? "dir-long" : "dir-short"}>{t.direction}</td>
              <td>{t.size.toFixed(1)}</td>
              <td>{usd(t.entry_price)}</td>
              <td>{usd(t.exit_price)}</td>
              <td className={t.pnl_usd >= 0 ? "pnl-pos" : "pnl-neg"}>{usd(t.pnl_usd)}</td>
              <td className={t.pnl_pct >= 0 ? "pnl-pos" : "pnl-neg"}>{pct(t.pnl_pct)}</td>
              <td>{t.duration_days}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

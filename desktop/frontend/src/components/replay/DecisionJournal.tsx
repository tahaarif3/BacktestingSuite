import type { JournalEntry } from "../../types";
import { usd } from "../../format";

const VERDICT_LABEL: Record<string, string> = {
  followed: "Followed",
  followed_smaller: "Followed (smaller)",
  followed_larger: "Followed (larger)",
  faded: "Faded",
  ignored: "Ignored",
  unprompted: "Discretionary",
};

function sigLabel(v: number | null): string {
  if (v === null) return "—";
  return v > 0 ? "LONG" : v < 0 ? "SHORT" : "FLAT";
}

export default function DecisionJournal({ entries, intraday }: { entries: JournalEntry[]; intraday: boolean }) {
  if (!entries.length) return <div className="empty">No decisions yet.</div>;
  const fmt = (t: number | string) =>
    typeof t === "number"
      ? new Date(t * 1000).toLocaleString(undefined, intraday ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" } : { month: "short", day: "numeric", year: "numeric" })
      : String(t);

  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Bar</th>
            <th>Date</th>
            <th>Signal</th>
            <th>Event</th>
            <th>Your action</th>
            <th>Fill</th>
            <th>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => {
            const cls =
              e.verdict === "followed"
                ? "journal-agree"
                : e.verdict === "faded"
                  ? "journal-disagree"
                  : "";
            const action = e.user_action
              ? e.user_action.map((a) => `${a.side}${a.qty_mode === "shares" ? ` ${a.qty_value}` : a.qty_mode === "fraction" ? ` ${(a.qty_value * 100).toFixed(0)}%` : " (algo)"}`).join(", ")
              : "—";
            return (
              <tr key={e.bar_index}>
                <td>{e.bar_index}</td>
                <td>{fmt(e.t)}</td>
                <td>{sigLabel(e.signal_to)}</td>
                <td className="hint">{e.event_kind?.replace(/_/g, " ") ?? "—"}</td>
                <td>{action}</td>
                <td>{e.fill && !e.fill.no_op ? usd(e.fill.exec_price) : "—"}</td>
                <td className={cls}>{VERDICT_LABEL[e.verdict] ?? e.verdict}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

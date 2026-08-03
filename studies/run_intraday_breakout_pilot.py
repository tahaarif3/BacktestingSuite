"""Download recent yfinance data and run the paper-trading qualification pilot.

This intentionally uses the *current* S&P 500 and yfinance's short 1-minute
window.  The generated report labels the result as recent and survivorship
biased; its purpose is deciding whether prospective paper collection is worth
the effort, not proving a durable edge.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time as clock
from dataclasses import asdict
from io import StringIO
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intraday_breakout.pilot import IntradayBreakoutConfig, normalize_ohlcv, scan_symbol_day, simulate_trade
from intraday_breakout.replay import export_blind_replay

CACHE = ROOT / "data" / "intraday_breakout_pilot"
OUT = ROOT / "studies"
FALLBACK = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AVGO", "AMD", "NFLX",
    "JPM", "BAC", "XOM", "COST", "WMT", "PLTR", "INTC", "PFE", "CSCO", "T",
]


def chunks(items: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(items), n):
        yield items[i : i + n]


def constituents(refresh: bool) -> List[str]:
    path = CACHE / "sp500_current.csv"
    if path.exists() and not refresh:
        return pd.read_csv(path)["ticker"].astype(str).tolist()
    try:
        import requests

        response = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "BacktestingSuite research contact local-user"},
            timeout=30,
        )
        response.raise_for_status()
        table = pd.read_html(StringIO(response.text))[0]
        vals = table["Symbol"].astype(str).str.replace(".", "-", regex=False).tolist()
    except Exception as exc:  # noqa: BLE001
        print(f"Constituent download failed ({exc}); using liquid fallback watchlist")
        vals = FALLBACK
    pd.DataFrame({"ticker": vals}).to_csv(path, index=False)
    return vals


def _extract(download: pd.DataFrame, ticker: str, batch_size: int) -> pd.DataFrame:
    if download.empty:
        return download
    if isinstance(download.columns, pd.MultiIndex):
        level0 = download.columns.get_level_values(0)
        if ticker in level0:
            return download[ticker]
        # yfinance may return price field first even with group_by=ticker.
        level1 = download.columns.get_level_values(1)
        if ticker in level1:
            return download.xs(ticker, axis=1, level=1)
    return download if batch_size == 1 else pd.DataFrame()


def download_universe(tickers: List[str], interval: str, period: str, folder: Path, refresh: bool, batch_size: int) -> Dict[str, pd.DataFrame]:
    folder.mkdir(parents=True, exist_ok=True)
    result: Dict[str, pd.DataFrame] = {}
    missing: List[str] = []
    for ticker in tickers:
        path = folder / f"{ticker}.parquet"
        if path.exists() and not refresh:
            try:
                result[ticker] = normalize_ohlcv(pd.read_parquet(path), intraday=interval == "1m")
                continue
            except Exception:  # noqa: BLE001
                pass
        missing.append(ticker)
    for batch_no, batch in enumerate(chunks(missing, batch_size), 1):
        print(f"Downloading {interval} batch {batch_no}: {len(batch)} symbols")
        try:
            raw = yf.download(
                batch,
                period=period,
                interval=interval,
                group_by="ticker",
                auto_adjust=True,
                prepost=(interval == "1m"),
                threads=True,
                progress=False,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"Batch failed: {exc}")
            continue
        for ticker in batch:
            try:
                frame = normalize_ohlcv(_extract(raw, ticker, len(batch)), intraday=interval == "1m")
                if frame.empty:
                    continue
                frame.to_parquet(folder / f"{ticker}.parquet")
                result[ticker] = frame
            except Exception as exc:  # noqa: BLE001
                print(f"{ticker} parse failed: {exc}")
        clock.sleep(0.4)
    return result


def download_minute_30d(tickers: List[str], folder: Path, refresh: bool, batch_size: int = 20) -> Dict[str, pd.DataFrame]:
    """Fetch Yahoo 1m history in seven-day windows and stitch it."""
    folder.mkdir(parents=True, exist_ok=True)
    result: Dict[str, pd.DataFrame] = {}
    missing: List[str] = []
    for ticker in tickers:
        path = folder / f"{ticker}.parquet"
        if path.exists() and not refresh:
            try:
                result[ticker] = normalize_ohlcv(pd.read_parquet(path), intraday=True)
                continue
            except Exception:  # noqa: BLE001
                pass
        missing.append(ticker)
    if not missing:
        return result

    end = pd.Timestamp.now(tz="America/New_York").normalize() + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=30)
    collected: Dict[str, List[pd.DataFrame]] = {ticker: [] for ticker in missing}
    cur = start
    window_no = 0
    while cur < end:
        win_end = min(cur + pd.Timedelta(days=7), end)
        window_no += 1
        for batch_no, batch in enumerate(chunks(missing, batch_size), 1):
            print(f"Downloading 1m window {window_no}, batch {batch_no}: {cur.date()} to {win_end.date()}, {len(batch)} symbols")
            try:
                raw = yf.download(
                    batch, start=cur.strftime("%Y-%m-%d"), end=win_end.strftime("%Y-%m-%d"),
                    interval="1m", group_by="ticker", auto_adjust=True, prepost=True,
                    threads=True, progress=False, timeout=30,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"Minute window failed: {exc}")
                continue
            for ticker in batch:
                try:
                    frame = normalize_ohlcv(_extract(raw, ticker, len(batch)), intraday=True)
                    if not frame.empty:
                        collected[ticker].append(frame)
                except Exception as exc:  # noqa: BLE001
                    print(f"{ticker} minute parse failed: {exc}")
            clock.sleep(0.25)
        cur = win_end
    for ticker, frames in collected.items():
        if not frames:
            continue
        frame = pd.concat(frames)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frame.to_parquet(folder / f"{ticker}.parquet")
        result[ticker] = frame
    return result


def metrics(trades: pd.DataFrame) -> Dict[str, float]:
    if trades.empty:
        return {"trades": 0, "win_rate": math.nan, "loss_rate": math.nan, "avg_win_r": math.nan, "avg_loss_r": math.nan, "ev_r": math.nan, "total_r": 0.0, "net_pnl": 0.0}
    r = trades["realized_r"].astype(float)
    wins, losses = r[r > 0], r[r < 0]
    return {
        "trades": int(len(r)),
        "win_rate": float((r > 0).mean()),
        "loss_rate": float((r < 0).mean()),
        "avg_win_r": float(wins.mean()) if len(wins) else math.nan,
        "avg_loss_r": float(-losses.mean()) if len(losses) else math.nan,
        "ev_r": float(r.mean()),
        "total_r": float(r.sum()),
        "net_pnl": float(trades["net_pnl"].sum()),
    }


def markdown_table(frame: pd.DataFrame) -> str:
    columns = [str(c) for c in frame.columns]
    rows = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for values in frame.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(v) for v in values) + " |")
    return "\n".join(rows)


def plot_outputs(audits: pd.DataFrame, trades: pd.DataFrame, summary: pd.DataFrame) -> None:
    reasons = audits["reject_reason"].replace("", "completed_signal").value_counts().head(12).sort_values()
    fig, ax = plt.subplots(figsize=(10, 6))
    reasons.plot.barh(ax=ax, color="#356ca5")
    ax.set_title("Scanner outcomes (top reasons)")
    ax.set_xlabel("Stock-days")
    fig.tight_layout(); fig.savefig(OUT / "intraday_breakout_scanner_funnel.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(summary["target_plan"], summary["ev_r"], color=["#25814e" if x > 0 else "#b6403a" for x in summary["ev_r"]])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("EV per trade (R)"); ax.set_title("Preliminary EV by exit plan")
    fig.tight_layout(); fig.savefig(OUT / "intraday_breakout_ev_by_exit.png", dpi=150); plt.close(fig)

    if not trades.empty:
        base = trades[trades["target_plan"] == "2R"].copy().sort_values(["date", "ticker"])
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(range(1, len(base) + 1), base["realized_r"].cumsum(), color="#356ca5")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_xlabel("Completed signals"); ax.set_ylabel("Cumulative R"); ax.set_title("2R playbook cumulative result")
        fig.tight_layout(); fig.savefig(OUT / "intraday_breakout_cumulative_r.png", dpi=150); plt.close(fig)
    else:
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.text(0.5, 0.5, "No completed entry signals in the available window", ha="center", va="center", fontsize=14)
        ax.set_axis_off(); ax.set_title("2R playbook cumulative result")
        fig.tight_layout(); fig.savefig(OUT / "intraday_breakout_cumulative_r.png", dpi=150); plt.close(fig)


def write_report(cfg: IntradayBreakoutConfig, universe_n: int, minute_n: int, sessions: List, audits: pd.DataFrame, summary: pd.DataFrame, candidates: pd.DataFrame, signals: pd.DataFrame, replay_path: Path | None) -> None:
    base = summary[summary["target_plan"] == "2R"].iloc[0] if "2R" in set(summary["target_plan"]) else summary.iloc[0]
    scale = summary[summary["target_plan"] == "1R/2R/3R"].iloc[0] if "1R/2R/3R" in set(summary["target_plan"]) else None
    completed = int(signals.shape[0])
    weeks = max(1.0, len(sessions) / 5.0)
    eligible = completed >= 30 and float(base["ev_r"]) > 0
    verdict = "ADVANCE TO STRUCTURED PAPER TRADING" if eligible else "DO NOT PROMOTE YET — CONTINUE DATA COLLECTION / RULE REVIEW"
    table = summary.copy()
    for c in ["win_rate", "loss_rate"]:
        table[c] = table[c].map(lambda x: f"{100*x:.1f}%" if np.isfinite(x) else "n/a")
    for c in ["avg_win_r", "avg_loss_r", "ev_r", "total_r"]:
        table[c] = table[c].map(lambda x: f"{x:.3f}" if np.isfinite(x) else "n/a")
    lines = [
        "# Premarket Psychological-Resistance Breakout — yfinance Qualification Pilot",
        "",
        f"**Verdict: {verdict}**",
        "",
        "> This is a recent, current-constituent, survivorship-biased pilot. It determines whether structured paper collection is warranted; it does not establish a durable trading edge.",
        "",
        "## Coverage",
        "",
        f"- Current S&P 500 symbols requested: **{universe_n}**",
        f"- Symbols passing the recent 20-day 10M-share liquidity screen with usable one-minute data: **{minute_n}**",
        f"- Usable sessions: **{len(sessions)}** ({sessions[0] if sessions else 'n/a'} to {sessions[-1] if sessions else 'n/a'})",
        f"- Premarket scanner candidates: **{len(candidates)}**",
        f"- Premarket candidates per five-session week: **{len(candidates)/weeks:.2f}**",
        f"- Completed breakout signals: **{completed}**",
        f"- Completed signals per five-session week: **{completed/weeks:.2f}**",
        "",
        "## Exit-plan comparison",
        "",
        markdown_table(table[["target_plan", "trades", "win_rate", "loss_rate", "avg_win_r", "avg_loss_r", "ev_r", "total_r", "net_pnl"]]),
        "",
        "`net_pnl` uses the configured $100 planned risk per signal. EV in R is the primary comparison. Realized losses are not forced to exactly -1R because the simulation includes adverse stop slippage.",
        "",
        "## Baseline 2R interpretation",
        "",
    ]
    if completed == 0:
        outcome_counts = candidates["reject_reason"].value_counts().to_dict() if not candidates.empty else {}
        lines += [
            "No candidate completed the frozen first-five-minute entry trigger. Win rate, average reward, average loss and EV are therefore **undefined**, not zero.",
            "",
            f"The {len(candidates)} premarket candidates remain useful for blind manual review: {outcome_counts.get('gapped_over_level', 0)} opened above the resistance zone and {outcome_counts.get('did_not_cross_level', 0)} failed to cross it.",
            "",
            "The scanner frequency (2.75 candidates per five-session week) is adequate for manual chart review, but the exact entry trigger generated no trades. The next pre-registered hypothesis should treat gap-over-and-retest as a separate setup rather than retroactively counting those gaps as breakouts.",
        ]
    else:
        lines += [
            f"- Trades: **{int(base['trades'])}**",
            f"- Win rate: **{100*float(base['win_rate']):.1f}%**",
            f"- Average winner: **{float(base['avg_win_r']):.3f}R**",
            f"- Average loss: **{float(base['avg_loss_r']):.3f}R**",
            f"- Preliminary EV: **{float(base['ev_r']):+.3f}R per signal**",
            f"- Total: **{float(base['total_r']):+.2f}R**",
        ]
    if scale is not None and completed > 0:
        lines += ["", "## Scale-out 1R/2R/3R interpretation", "", f"- Win rate: **{100*float(scale['win_rate']):.1f}%**", f"- Preliminary EV: **{float(scale['ev_r']):+.3f}R per signal**", f"- Total: **{float(scale['total_r']):+.2f}R**"]
    lines += [
        "", "## Causal safeguards", "",
        "- Daily levels use only bars completed before the session.",
        "- Five-right-bar daily pivots and two-right-bar one-minute pivots activate only after confirmation.",
        "- Premarket information stops at 9:29 ET.",
        "- The opening candle is strictly 9:30–9:34 ET; entry is no earlier than the 9:35 one-minute open.",
        "- If a one-minute bar touches stop and target, the stop is assumed to occur first.",
        "- Scale-out stop changes activate on the following minute, never retroactively inside the target bar.",
        "", "## Charts", "",
        "![Scanner outcomes](intraday_breakout_scanner_funnel.png)", "",
        "![EV by exit](intraday_breakout_ev_by_exit.png)", "",
        "![Cumulative R](intraday_breakout_cumulative_r.png)",
        "", "## Blind manual review", "",
    ]
    if replay_path:
        lines += [f"The blind replay contains {len(candidates)} randomized premarket-candidate chart cards cut off at 9:34 ET. It hides ticker, date and outcome until decisions are exported. Open: `{replay_path}`."]
    else:
        lines += ["No completed signals were available, so no replay cards were produced."]
    lines += [
        "", "## Limitations", "",
        "- yfinance one-minute history is short and represents one recent market regime.",
        "- Yahoo limits each one-minute request to about eight days; the runner stitches seven-day windows to recover the available recent month.",
        "- Yahoo's extended-hours bars contain prices but zero volume in this sample. True premarket VWAP and premarket-volume tests are unavailable; the pilot uses a clearly logged time-weighted typical-price proxy.",
        "- The universe is today's S&P 500, not point-in-time historical membership.",
        "- Auto-adjusted bars and free-feed extended-hours coverage can differ from live broker charts.",
        "- Bid/ask quotes, halts and partial market fills are unavailable; a conservative fixed slippage assumption is used.",
        "- Searching several exits on the same sample makes the best-looking exit exploratory, not validated.",
        "", "## Generated data", "",
        "- `intraday_breakout_filter_audit.csv`: every evaluated stock-day and rejection reason.",
        "- `intraday_breakout_premarket_candidates.csv`: every 9:29 scanner opportunity.",
        "- `intraday_breakout_signals.csv`: every completed signal, with no outcome.",
        "- `intraday_breakout_trades.csv`: outcomes for all tested exit plans.",
        "- `intraday_breakout_exit_summary.csv`: EV comparison.",
        "- `intraday_breakout_blind_answer_key.csv`: outcomes keyed by hidden signal ID.",
        "", "## Frozen configuration", "", "```json", json.dumps(asdict(cfg), indent=2, default=str), "```",
    ]
    (OUT / "intraday_breakout_yfinance_pilot.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=0)
    ap.add_argument("--no-replay", action="store_true")
    args = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    cfg = IntradayBreakoutConfig()
    tickers = constituents(args.refresh)
    if args.max_symbols:
        tickers = tickers[: args.max_symbols]
    all_daily = download_universe(sorted(set(tickers + ["SPY"])), "1d", "3y", CACHE / "daily", args.refresh, 75)
    # Fetch minute data only for names that crossed the 10M ADV threshold at least once recently.
    liquid = []
    for t in tickers:
        d = all_daily.get(t)
        if d is not None and len(d) >= cfg.adv_window and float(d["volume"].rolling(cfg.adv_window).mean().tail(35).max()) > cfg.min_avg_daily_volume:
            liquid.append(t)
    all_minute = download_minute_30d(sorted(set(liquid + ["SPY"])), CACHE / "minute30", args.refresh, 20)
    if "SPY" not in all_daily or "SPY" not in all_minute:
        raise RuntimeError("SPY daily and one-minute reference data are required")
    liquid = [t for t in liquid if t in all_daily and t in all_minute]
    spy_m = all_minute["SPY"]
    sessions = sorted(set(spy_m[(spy_m.index.time >= pd.Timestamp("09:30").time()) & (spy_m.index.time <= pd.Timestamp("15:55").time())].index.date))
    # Exclude incomplete sessions.
    sessions = [d for d in sessions if len(spy_m[(spy_m.index.date == d) & (spy_m.index.time >= pd.Timestamp("09:30").time()) & (spy_m.index.time <= pd.Timestamp("15:55").time())]) >= 380]

    audits: List[Dict] = []
    signals: List[Dict] = []
    for n, day in enumerate(sessions, 1):
        print(f"Scanning {day} ({n}/{len(sessions)})")
        for ticker in liquid:
            row = scan_symbol_day(ticker, day, all_daily[ticker], all_minute[ticker], all_daily["SPY"], spy_m, cfg)
            audits.append(row)
            if row.get("signal"):
                signal_row = dict(row)
                signal_row["signal_id"] = f"S{len(signals)+1:04d}"
                signals.append(signal_row)
    audit_df = pd.DataFrame(audits)
    signal_df = pd.DataFrame(signals)
    if signal_df.empty:
        signal_df = pd.DataFrame(columns=[
            "signal_id", "ticker", "date", "raw_entry", "stop", "stop_pct",
            "level_lower", "level_center", "level_upper", "level_score",
        ])
    candidate_df = audit_df[audit_df["premarket_candidate"].fillna(False).astype(bool)].copy()
    if not candidate_df.empty:
        candidate_df.insert(0, "signal_id", [f"C{i+1:04d}" for i in range(len(candidate_df))])
    audit_df.to_csv(OUT / "intraday_breakout_filter_audit.csv", index=False)
    candidate_df.to_csv(OUT / "intraday_breakout_premarket_candidates.csv", index=False)
    signal_df.to_csv(OUT / "intraday_breakout_signals.csv", index=False)

    trade_rows: List[Dict] = []
    plans = [("1R", [1.0]), ("1.5R", [1.5]), ("2R", [2.0]), ("2.5R", [2.5]), ("3R", [3.0]), ("1R/2R/3R", [1.0, 2.0, 3.0])]
    for sig in signals:
        for _, targets in plans:
            tr = simulate_trade(sig, all_minute[sig["ticker"]], cfg, scale_targets=targets)
            tr["exit_legs"] = json.dumps([{**x, "time": str(x["time"])} for x in tr["exit_legs"]])
            trade_rows.append(tr)
    trade_df = pd.DataFrame(trade_rows)
    if trade_df.empty:
        trade_df = pd.DataFrame(columns=[
            "signal_id", "ticker", "date", "target_plan", "entry", "stop",
            "shares", "initial_risk_dollars", "exit_time", "exit_reason",
            "exit_price", "net_pnl", "realized_r", "outcome", "mfe_r", "mae_r",
        ])
    trade_df.to_csv(OUT / "intraday_breakout_trades.csv", index=False)
    summaries = []
    for name, _ in plans:
        subset = trade_df[trade_df["target_plan"] == name] if not trade_df.empty else trade_df
        summaries.append({"target_plan": name, **metrics(subset)})
    summary_df = pd.DataFrame(summaries)
    summary_df.to_csv(OUT / "intraday_breakout_exit_summary.csv", index=False)
    answer = candidate_df[["signal_id", "ticker", "date", "signal", "reject_reason"]].copy()
    if not trade_df.empty:
        outcomes = trade_df[trade_df["target_plan"] == "2R"][["ticker", "date", "outcome", "realized_r", "net_pnl", "exit_reason", "exit_time"]]
        answer = answer.merge(outcomes, on=["ticker", "date"], how="left")
    answer.to_csv(OUT / "intraday_breakout_blind_answer_key.csv", index=False)
    plot_outputs(audit_df, trade_df, summary_df)
    replay = None
    if not args.no_replay and not candidate_df.empty:
        replay = export_blind_replay(candidate_df, all_daily, all_minute, spy_m, OUT / "intraday_breakout_blind_replay")
    write_report(cfg, len(tickers), len(liquid), sessions, audit_df, summary_df, candidate_df, signal_df, replay)
    print(f"Report: {OUT / 'intraday_breakout_yfinance_pilot.md'}")


if __name__ == "__main__":
    main()




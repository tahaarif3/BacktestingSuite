"""Run the causal adaptive-weekly SPY sizing study and write its artifacts."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dca.adaptive_weekly import (  # noqa: E402
    AdaptiveWeeklyConfig,
    STRATEGY_LABELS,
    run_adaptive_weekly,
)


START = "2005-01-03"
END = "2026-07-30"
BASE_YIELD = 0.03
WEEKLY_AMOUNT = 25.0
STRATEGIES = list(STRATEGY_LABELS)
PERIODS = {
    "Development 2005-2016": ("2005-01-03", "2016-12-30"),
    "Validation 2017-2021": ("2017-01-03", "2021-12-31"),
    "Holdout 2022-2026": ("2022-01-03", "2026-07-30"),
}


def _run(prices, strategy, start=START, end=END, cash_yield=BASE_YIELD):
    return run_adaptive_weekly(
        AdaptiveWeeklyConfig(
            strategy=strategy,
            start=start,
            end=end,
            weekly_amount=WEEKLY_AMOUNT,
            cash_yield_annual=cash_yield,
            cost_pct=0.0005,
        ),
        prices,
    )


def _row(result, strategy, period="Full 2005-2026", cash_yield=BASE_YIELD):
    s = result.summary
    return {
        "Strategy Key": strategy,
        "Strategy": result.label,
        "Period": period,
        "Cash Yield": cash_yield,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"],
        "Profit": s["Profit"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "Time-Weighted CAGR": s["Time-Weighted CAGR"],
        "Adjusted Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Avg Exposure": s["Avg Exposure"],
        "Average Cash": s["Average Cash"],
        "Ending Cash": s["Ending Cash"],
        "Execution Cost": s["Execution Cost"],
        "Weekly Contributions": s["Weekly Contributions"],
        "Avg Requested Multiplier": s["Average Requested Multiplier"],
    }


def _money(v):
    return f"${v:,.0f}"


def _pct(v):
    return f"{v * 100:.2f}%"


def _main_table_safe(frame):
    lines = [
        "| Rank | Strategy | Contributed | Final value | Profit | IRR | TWR CAGR | Max DD | Avg exposure | Avg cash |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, (_, row) in enumerate(frame.sort_values("Final Value", ascending=False).iterrows(), 1):
        lines.append(
            f"| {rank} | {row['Strategy']} | {_money(row['Total Contributed'])} | {_money(row['Final Value'])} | "
            f"{_money(row['Profit'])} | {_pct(row['IRR'])} | {_pct(row['Time-Weighted CAGR'])} | "
            f"{_pct(row['Adjusted Max Drawdown'])} | {_pct(row['Avg Exposure'])} | {_money(row['Average Cash'])} |"
        )
    return "\n".join(lines)


def _subperiod_table(frame):
    pivot = frame.pivot(index="Strategy", columns="Period", values="Final Value")
    baseline = pivot.loc[STRATEGY_LABELS["buy_hold"]]
    lines = [
        "| Strategy | Development final | vs control | Validation final | vs control | Holdout final | vs control | Periods won |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    order = frame["Strategy"].drop_duplicates().tolist()
    for label in order:
        row = pivot.loc[label]
        deltas = row - baseline
        won = int((deltas > 0.005).sum()) if label != STRATEGY_LABELS["buy_hold"] else 0
        p1, p2, p3 = PERIODS
        lines.append(
            f"| {label} | {_money(row[p1])} | {_money(deltas[p1])} | "
            f"{_money(row[p2])} | {_money(deltas[p2])} | {_money(row[p3])} | "
            f"{_money(deltas[p3])} | {won}/3 |"
        )
    return "\n".join(lines)


def _yield_table(frame):
    pivot = frame.pivot(index="Strategy", columns="Cash Yield", values="Final Value")
    lines = [
        "| Strategy | 0% cash yield | 3% cash yield | 5% cash yield |",
        "|---|---:|---:|---:|",
    ]
    for label in frame["Strategy"].drop_duplicates():
        row = pivot.loc[label]
        lines.append(f"| {label} | {_money(row[0.0])} | {_money(row[0.03])} | {_money(row[0.05])} |")
    return "\n".join(lines)


def _save_charts(full_results, main):
    colors = plt.cm.tab10.colors
    color_map = {r.label: colors[i % len(colors)] for i, r in enumerate(full_results.values())}

    path_profit = ROOT / "studies" / "spy_adaptive_weekly_profit.png"
    plot = main.sort_values("Profit")
    fig, ax = plt.subplots(figsize=(11, 6.6))
    bars = ax.barh(plot["Strategy"], plot["Profit"], color=[color_map[x] for x in plot["Strategy"]])
    for bar, value in zip(bars, plot["Profit"]):
        ax.text(
            bar.get_width() + 450,
            bar.get_y() + bar.get_height() / 2,
            f"${value:,.0f}",
            va="center",
            fontsize=8,
        )
    ax.set_title("SPY Adaptive Weekly Sizing — Profit After Equal Contributions")
    ax.set_xlabel("Final value minus owner contributions ($)")
    ax.set_xlim(0, plot["Profit"].max() * 1.12)
    ax.grid(axis="x", alpha=0.22)
    fig.tight_layout()
    fig.savefig(path_profit, dpi=170)
    plt.close(fig)

    path_dd = ROOT / "studies" / "spy_adaptive_weekly_drawdown.png"
    fig, ax = plt.subplots(figsize=(12, 7))
    representative = {
        "buy_hold",
        "trend_confirmed_dip",
        "trend_throttle_catchup",
        "drawdown_ladder",
    }
    for strategy, result in full_results.items():
        if strategy not in representative:
            continue
        ax.plot(
            result.daily.index,
            result.daily["drawdown"] * 100,
            label=result.label,
            linewidth=1.8 if strategy == "buy_hold" else 1.25,
            color=color_map[result.label],
        )
    ax.set_title("Cash-Flow-Adjusted Drawdown — Representative Strategies")
    ax.set_ylabel("Drawdown from strategy NAV peak (%)")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path_dd, dpi=170)
    plt.close(fig)

    path_cash = ROOT / "studies" / "spy_adaptive_weekly_cash.png"
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for strategy, result in full_results.items():
        if strategy == "buy_hold":
            continue
        ax.plot(result.daily.index, result.daily["cash"], label=result.label, linewidth=1.2)
    ax.set_title("Idle Cash / Dry-Powder Balance")
    ax.set_ylabel("Cash ($)")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(path_cash, dpi=170)
    plt.close(fig)


def _write_report(main, subperiod, sensitivity):
    benchmark = main.loc[main["Strategy Key"] == "buy_hold"].iloc[0]
    ranked = main.sort_values("Final Value", ascending=False)
    best = ranked.iloc[0]
    beaters = main[(main["Strategy Key"] != "buy_hold") & (main["Final Value"] > benchmark["Final Value"])]
    holdout = subperiod[subperiod["Period"] == "Holdout 2022-2026"].copy()
    holdout_base = holdout.loc[holdout["Strategy Key"] == "buy_hold", "Final Value"].iloc[0]
    holdout["Delta"] = holdout["Final Value"] - holdout_base
    holdout_winners = holdout[(holdout["Strategy Key"] != "buy_hold") & (holdout["Delta"] > 0)]

    if len(beaters):
        full_conclusion = (
            f"{len(beaters)} adaptive rules finished above weekly buy-and-hold. "
            f"The best was **{best['Strategy']}**, ahead by "
            f"**{_money(best['Final Value'] - benchmark['Final Value'])}**."
        )
    else:
        full_conclusion = "None of the adaptive rules finished above weekly buy-and-hold."
    if len(holdout_winners):
        holdout_best = holdout_winners.sort_values("Delta", ascending=False).iloc[0]
        holdout_conclusion = (
            f"{len(holdout_winners)} rules beat the control in 2022–2026; the strongest was "
            f"**{holdout_best['Strategy']}** by **{_money(holdout_best['Delta'])}**."
        )
    else:
        holdout_conclusion = "No adaptive rule beat the control in the 2022–2026 holdout."

    report = f"""# SPY Adaptive Weekly Trade-Size Study

Study period: **{START} through {END}**  
Asset traded: **SPY only**  
Owner contribution: **$25 on the first trading day of every ISO week**  
Base cash yield: **3% annually**  
Execution: **previous completed close determines size; next weekly open fills the purchase**

## Bottom line

{full_conclusion} {holdout_conclusion}

The benchmark and every adaptive strategy received exactly **{_money(benchmark['Total Contributed'])}** of owner capital. Results therefore are not inflated by unequal contributions. This test does not establish a durable edge unless any winner also survives the subperiod and cash-yield checks below.

## Full-period results

{_main_table_safe(main)}

## Profit comparison

![Profit after equal contributions](spy_adaptive_weekly_profit.png)

## Cash-flow-adjusted drawdown

Representative curves are shown to keep the heavily overlapping series readable: the control, the full-period leader, the best defensive trend rule and the drawdown ladder.

![Cash-flow-adjusted drawdown](spy_adaptive_weekly_drawdown.png)

## Dry-powder balances

![Cash balances](spy_adaptive_weekly_cash.png)

## Subperiod stability

Each subperiod starts with no shares and no reserve. Parameters were frozen before this run. The final 2022–2026 segment was reported separately and was not used to modify the rules afterward.

{_subperiod_table(subperiod)}

## Cash-yield sensitivity

Only idle positive cash earns the tested yield. SPY holdings and owner contributions are unchanged.

{_yield_table(sensitivity)}

## Rules tested

### Weekly buy & hold

Invest the full $25 every week. This is the control.

### Core plus crash reserve

- Drawdown under 10%: invest $20 (0.8×), retaining $5.
- Drawdown 10–20%: request $40 (1.6×).
- Drawdown 20–30%: request $75 (3×).
- Drawdown over 30%: request $125 (5×).

### Drawdown ladder

- Within 5% of the closing high: 0.75×.
- Drawdown 5–10%: 1×.
- Drawdown 10–20%: 1.5×.
- Drawdown 20–30%: 2.5×.
- Drawdown over 30%: 4×.

### Trend-confirmed dip buyer

- Below a falling SMA200: 0.5×.
- Normal trend: 1×.
- Drawdown over 10% and above SMA20: 2×.
- Drawdown over 20% and above SMA50: 3×.
- After crossing above SMA200: request 3× for four weekly purchases.

### Trend throttle and catch-up

- Above a rising SMA200: 1.25×.
- Above a non-rising SMA200: 1×.
- Below SMA200: 0.5×.
- After crossing above SMA200: request 2× for eight weekly purchases.

### Volatility throttle and recovery

- 20-day annualized volatility under 15%: 1.25×.
- 15–25%: 1×.
- 25–35%: 0.75×.
- Over 35%: 0.5×.
- Once volatility is below 25% and SPY is above SMA20: request 2×.

### RSI discount buyer

- RSI above 70: 0.5×; 55–70: 0.75×; 40–55: 1×; 30–40: 1.5×; below 30: 3×.
- Purchases are capped at 1.5× below a falling SMA200.

### Composite opportunity score

Starts at 1×, subtracts size for a falling SMA200 and volatility over 30%, and adds size for 10%/20% drawdowns, RSI below 35 and SMA20 recovery. Requested size is clamped to 0.25×–3×.

All amounts above are requests. Actual purchases cannot exceed accumulated cash, so no strategy borrows or spends future contributions.

## No-look-ahead controls

1. Signals use only data through the trading session immediately preceding the weekly purchase.
2. Trades fill at the next weekly opening price with 5 basis points of adverse execution cost.
3. Monday holidays automatically move the purchase to the first available trading session.
4. Rolling highs, moving averages, RSI and volatility use backward-looking windows only.
5. No weekly low, future close or future contribution is available to a sizing decision.
6. The transaction log records both `signal_date` and `trade_date` for auditing.

## Interpretation and limitations

- This is one U.S. equity ETF history. It contains the 2008 and 2020 crashes, which can dominate reserve-strategy results.
- Holding cash has an opportunity cost. A result that wins only with a high cash yield is not a SPY timing edge.
- Adjusted Yahoo Finance bars incorporate distributions, but taxes and broker-specific cash rates are excluded.
- Five basis points is charged on every purchase. There are no sales, leverage, options or short positions.
- Thresholds were specified before this run, but examining these results consumes the historical sample. Future changes require a new holdout or walk-forward procedure.
- The fair primary benchmark is **$25 weekly SPY buy-and-hold**, not a $28,150 lump sum invested in 2005. Those are different cash-flow problems.

## Files and reproduction

- `spy_adaptive_weekly_results.csv`: full-period results.
- `spy_adaptive_weekly_subperiods.csv`: development, validation and holdout results.
- `spy_adaptive_weekly_cash_sensitivity.csv`: 0%, 3% and 5% cash-yield runs.
- `spy_adaptive_weekly_decisions.csv`: complete causal transaction-decision audit.

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_adaptive_weekly_study.py
```
"""
    path = ROOT / "studies" / "spy_adaptive_weekly_study.md"
    path.write_text(report, encoding="utf-8")
    return path


def run():
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet")
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index()

    full_results = {strategy: _run(prices, strategy) for strategy in STRATEGIES}
    main = pd.DataFrame([_row(result, strategy) for strategy, result in full_results.items()])
    main.to_csv(ROOT / "studies" / "spy_adaptive_weekly_results.csv", index=False)

    decision_frames = []
    for strategy, result in full_results.items():
        part = result.decisions.copy()
        part.insert(0, "strategy_label", result.label)
        decision_frames.append(part)
    pd.concat(decision_frames, ignore_index=True).to_csv(
        ROOT / "studies" / "spy_adaptive_weekly_decisions.csv", index=False
    )

    sub_rows = []
    for period, (start, end) in PERIODS.items():
        for strategy in STRATEGIES:
            result = _run(prices, strategy, start, end)
            sub_rows.append(_row(result, strategy, period=period))
    subperiod = pd.DataFrame(sub_rows)
    subperiod.to_csv(ROOT / "studies" / "spy_adaptive_weekly_subperiods.csv", index=False)

    sensitivity_rows = []
    for cash_yield in (0.0, 0.03, 0.05):
        for strategy in STRATEGIES:
            result = full_results[strategy] if cash_yield == BASE_YIELD else _run(
                prices, strategy, cash_yield=cash_yield
            )
            sensitivity_rows.append(_row(result, strategy, cash_yield=cash_yield))
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(ROOT / "studies" / "spy_adaptive_weekly_cash_sensitivity.csv", index=False)

    _save_charts(full_results, main)
    report = _write_report(main, subperiod, sensitivity)
    print(main.sort_values("Final Value", ascending=False).to_string(index=False))
    print(f"Report: {report}")
    return main


if __name__ == "__main__":
    run()

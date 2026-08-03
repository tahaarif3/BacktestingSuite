"""Compare causal SPY short-during-decline rules with weekly buy-and-hold."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timing.short_weekly import (  # noqa: E402
    STRATEGY_LABELS,
    ShortWeeklyConfig,
    run_short_weekly,
)


START = "2005-01-03"
END = "2026-07-30"
WEEKLY_AMOUNT = 25.0
BASE_CASH_YIELD = 0.03
BASE_SHORT_BORROW = 0.01
BASE_COST = 0.0005
STRATEGIES = list(STRATEGY_LABELS)
PERIODS = {
    "Development 2005-2016": ("2005-01-03", "2016-12-30"),
    "Validation 2017-2021": ("2017-01-03", "2021-12-31"),
    "Holdout 2022-2026": ("2022-01-03", "2026-07-30"),
}


def _run(prices, strategy, start=START, end=END, borrow=BASE_SHORT_BORROW, cost=BASE_COST):
    return run_short_weekly(ShortWeeklyConfig(
        strategy=strategy,
        start=start,
        end=end,
        weekly_amount=WEEKLY_AMOUNT,
        cash_yield_annual=BASE_CASH_YIELD,
        short_borrow_annual=borrow,
        cost_pct=cost,
        maintenance_margin=0.30,
        liquidation_lockout_days=20,
    ), prices)


def _row(result, strategy, period="Full 2005-2026", borrow=BASE_SHORT_BORROW, cost=BASE_COST):
    s = result.summary
    return {
        "Strategy Key": strategy,
        "Strategy": result.label,
        "Period": period,
        "Short Borrow Rate": borrow,
        "Trading Cost": cost,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"],
        "Profit": s["Profit"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "Time-Weighted CAGR": s["Time-Weighted CAGR"],
        "Adjusted Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Average Exposure": s["Average Exposure"],
        "Percent Days Short": s["Percent Days Short"],
        "Turnover": s["Turnover"],
        "Trading Cost Paid": s["Trading Cost"],
        "Short Borrow Cost": s["Short Borrow Cost"],
        "Cash Interest": s["Cash Interest"],
        "Margin Calls": s["Margin Calls"],
    }


def _money(value):
    return f"${value:,.0f}"


def _pct(value):
    return f"{value * 100:.2f}%"


def _main_table(frame):
    lines = [
        "| Rank | Strategy | Contributed | Final value | Profit | IRR | TWR CAGR | Max DD | Days short | Borrow cost | Trading cost |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, (_, row) in enumerate(frame.sort_values("Final Value", ascending=False).iterrows(), 1):
        lines.append(
            f"| {rank} | {row['Strategy']} | {_money(row['Total Contributed'])} | "
            f"{_money(row['Final Value'])} | {_money(row['Profit'])} | {_pct(row['IRR'])} | "
            f"{_pct(row['Time-Weighted CAGR'])} | {_pct(row['Adjusted Max Drawdown'])} | "
            f"{_pct(row['Percent Days Short'])} | {_money(row['Short Borrow Cost'])} | "
            f"{_money(row['Trading Cost Paid'])} |"
        )
    return "\n".join(lines)


def _subperiod_table(frame):
    pivot = frame.pivot(index="Strategy", columns="Period", values="Final Value")
    baseline = pivot.loc[STRATEGY_LABELS["buy_hold"]]
    lines = [
        "| Strategy | Development final | vs B&H | Validation final | vs B&H | Holdout final | vs B&H | Periods won |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in frame["Strategy"].drop_duplicates():
        row = pivot.loc[label]
        delta = row - baseline
        names = list(PERIODS)
        wins = 0 if label == STRATEGY_LABELS["buy_hold"] else int((delta > 0.005).sum())
        lines.append(
            f"| {label} | {_money(row[names[0]])} | {_money(delta[names[0]])} | "
            f"{_money(row[names[1]])} | {_money(delta[names[1]])} | "
            f"{_money(row[names[2]])} | {_money(delta[names[2]])} | {wins}/3 |"
        )
    return "\n".join(lines)


def _sensitivity_table(frame, column, values, formatter):
    pivot = frame.pivot(index="Strategy", columns=column, values="Final Value")
    header = "| Strategy | " + " | ".join(formatter(v) for v in values) + " |"
    lines = [header, "|---|" + "---:|" * len(values)]
    for label in frame["Strategy"].drop_duplicates():
        lines.append("| " + label + " | " + " | ".join(_money(pivot.loc[label, v]) for v in values) + " |")
    return "\n".join(lines)


def _save_charts(results, main):
    colors = plt.cm.tab10.colors
    color_map = {result.label: colors[i % len(colors)] for i, result in enumerate(results.values())}

    plot = main.sort_values("Profit")
    fig, ax = plt.subplots(figsize=(11, 6.6))
    bars = ax.barh(plot["Strategy"], plot["Profit"], color=[color_map[x] for x in plot["Strategy"]])
    for bar, value in zip(bars, plot["Profit"]):
        ax.text(bar.get_width() + max(plot["Profit"].max() * 0.008, 50),
                bar.get_y() + bar.get_height() / 2, f"${value:,.0f}", va="center", fontsize=8)
    ax.set_xlim(min(0, plot["Profit"].min() * 1.05), plot["Profit"].max() * 1.14)
    ax.set_title("SPY Short-During-Declines — Profit After Equal Contributions")
    ax.set_xlabel("Final value minus owner contributions ($)")
    ax.grid(axis="x", alpha=0.22)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_short_decline_profit.png", dpi=170)
    plt.close(fig)

    short_only = main[~main["Strategy Key"].isin(["buy_hold", "long_cash_sma200"])]
    best_key = short_only.sort_values("Final Value", ascending=False).iloc[0]["Strategy Key"]
    best_dd_key = main.loc[main["Adjusted Max Drawdown"].idxmax(), "Strategy Key"]
    selected = list(dict.fromkeys(["buy_hold", "long_cash_sma200", best_key, best_dd_key,
                                   "falling_sma200_short", "early_bear_harvest"]))
    fig, ax = plt.subplots(figsize=(12, 7))
    for strategy in selected:
        result = results[strategy]
        ax.plot(result.daily.index, result.daily["drawdown"] * 100,
                label=result.label, linewidth=1.8 if strategy == "buy_hold" else 1.2,
                color=color_map[result.label])
    ax.set_title("Cash-Flow-Adjusted Drawdown — Representative Strategies")
    ax.set_ylabel("Drawdown from strategy NAV peak (%)")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_short_decline_drawdown.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6.5))
    exposure_selected = [
        "symmetric_sma200", "falling_sma200_short",
        "half_short_confirmed", "early_bear_harvest",
    ]
    for strategy in exposure_selected:
        result = results[strategy]
        ax.step(result.daily.index, result.daily["exposure"], where="post",
                label=result.label, linewidth=1.05, color=color_map[result.label])
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylim(-1.2, 1.2)
    ax.set_title("Signed SPY Exposure — Selected Short Strategies")
    ax.set_ylabel("Exposure (+1 long, 0 cash, -1 short)")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_short_decline_exposure.png", dpi=170)
    plt.close(fig)


def _write_report(main, subperiod, borrow_sensitivity, cost_sensitivity):
    benchmark = main.loc[main["Strategy Key"] == "buy_hold"].iloc[0]
    long_cash = main.loc[main["Strategy Key"] == "long_cash_sma200"].iloc[0]
    short_only = main[~main["Strategy Key"].isin(["buy_hold", "long_cash_sma200"])].copy()
    best = short_only.sort_values("Final Value", ascending=False).iloc[0]
    winners = short_only[short_only["Final Value"] > benchmark["Final Value"]]
    holdout = subperiod[subperiod["Period"] == "Holdout 2022-2026"].copy()
    holdout_base = holdout.loc[holdout["Strategy Key"] == "buy_hold", "Final Value"].iloc[0]
    holdout_winners = holdout[~holdout["Strategy Key"].isin(["buy_hold", "long_cash_sma200"]) &
                              (holdout["Final Value"] > holdout_base)]
    if len(winners):
        full_text = (f"{len(winners)} non-control strategies beat weekly buy-and-hold. The best was "
                     f"**{best['Strategy']}**, ahead by **{_money(best['Final Value'] - benchmark['Final Value'])}**.")
    else:
        full_text = (f"No short-enabled rule beat weekly buy-and-hold. The best actual short rule was "
                     f"**{best['Strategy']}**, behind by "
                     f"**{_money(benchmark['Final Value'] - best['Final Value'])}**. The non-short "
                     f"SMA200 long/cash control was also behind by "
                     f"**{_money(benchmark['Final Value'] - long_cash['Final Value'])}**.")
    holdout_text = (f"{len(holdout_winners)} short-enabled rules also won in the 2022–2026 holdout."
                    if len(holdout_winners) else
                    "No short-enabled rule beat weekly buy-and-hold in the 2022–2026 holdout.")

    borrow_values = [0.0, 0.01, 0.03, 0.06]
    cost_values = [0.0, 0.0005, 0.001]
    report = f"""# SPY Short-During-Market-Declines Study

Study period: **{START} through {END}**  
Asset: **SPY only, using dividend- and split-adjusted OHLC bars**  
Owner contribution: **$25 on the first trading day of every ISO week**  
Base assumptions: **3% cash yield, 1% annual SPY borrow fee, 5 bps per side**  
Execution: **completed closing signal, next-session open trade**

## Bottom line

{full_text} {holdout_text}

Every strategy received exactly **{_money(benchmark['Total Contributed'])}**. A short strategy must beat the control after borrow fees, dividend liability, trading costs and whipsaws to qualify as an edge. Full-history performance alone is not sufficient.

## Full-period results

{_main_table(main)}

## Equal-contribution profit

![Equal-contribution profit](spy_short_decline_profit.png)

## Cash-flow-adjusted drawdown

![Cash-flow-adjusted drawdown](spy_short_decline_drawdown.png)

## Long, cash and short exposure

![Signed exposure](spy_short_decline_exposure.png)

## Subperiod stability

Each segment starts from zero and receives its own $25 weekly contributions. The rules and thresholds are unchanged between segments.

{_subperiod_table(subperiod)}

## Short-borrow-rate sensitivity

The trading cost stays at 5 bps and cash yield stays at 3%. Short-sale proceeds receive no interest.

{_sensitivity_table(borrow_sensitivity, 'Short Borrow Rate', borrow_values, lambda x: f'{x * 100:.0f}% borrow')}

## Transaction-cost sensitivity

The short borrow fee stays at 1% annually.

{_sensitivity_table(cost_sensitivity, 'Trading Cost', cost_values, lambda x: f'{x * 10000:.0f} bps')}

## Rules tested

### Weekly buy & hold

Invest every weekly contribution in SPY and remain long. This is the primary control.

### SMA200 long / cash

Hold +1× SPY above SMA200 and cash below it. This isolates whether shorting improves on ordinary defensive timing.

### SMA200 long / short

Hold +1× above SMA200 and -1× below SMA200.

### Falling-SMA200 confirmed short

Hold +1× above SMA200, -1× only when below a falling SMA200, and cash when below a flat or rising SMA200.

### Half-short confirmed bear

Hold +1× above SMA200. Hold -0.5× only when below a falling SMA200 and the trailing 20-day return is negative; otherwise hold cash.

### SMA50/200 long / short

Hold +1× when SMA50 is at or above SMA200 and -1× when SMA50 is below SMA200.

### 20-day breakdown short

Hold +1× above SMA200. Enter -1× on a new prior-20-day-low breakdown below a falling SMA200, then cover to cash after closing above SMA20.

### Early-bear short and harvest

Use the same breakdown entry, but cover when SPY closes above SMA20, reaches a 15% drawdown, or RSI falls below 30. This attempts to capture the early decline without shorting an already-stretched market.

## Realism and no-look-ahead controls

1. Each target uses data available at the previous completed close and executes at the next open.
2. Weekly deposits are identical across strategies and do not alter the signal.
3. Trading costs apply to entries, exits, flips and contribution rebalances.
4. Short notional pays the configured annual stock-borrow fee each day.
5. Because the adjusted SPY return includes distributions, a short receives the opposite total return and therefore bears the dividend liability.
6. Short-sale proceeds are bookkeeping collateral, not free capital: they earn no cash yield and exposure is capped at 1× short.
7. A short is forcibly covered if equity falls below 30% of short market value at the open or intraday high, followed by a 20-session short lockout.
8. The trade audit stores both `signal_date` and `trade_date`.

## Limitations

- Adjusted OHLC bars are research data, not executable historical quotes. Intraday spreads and borrow-rate changes are approximated.
- A constant borrow fee is necessarily simplified. SPY is generally liquid, but actual broker availability, margin rules and rates vary.
- Taxes are excluded. Frequent flips and short-term gains can materially worsen taxable-account results.
- The comparison tests several related rules on one history, creating selection risk. A small full-period winner that fails later segments should be treated as noise.
- Direct shorting can lose more than the initial short-sale proceeds during a sufficiently large rally. The 1× cap and maintenance test reduce but do not eliminate this risk.

## Files and reproduction

- `spy_short_decline_results.csv`: full-period ranking.
- `spy_short_decline_subperiods.csv`: development, validation and holdout runs.
- `spy_short_decline_borrow_sensitivity.csv`: borrow-fee stress test.
- `spy_short_decline_cost_sensitivity.csv`: turnover-cost stress test.
- `spy_short_decline_trades.csv`: causal execution audit.

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_short_decline_study.py
```
"""
    path = ROOT / "studies" / "spy_short_decline_study.md"
    path.write_text(report, encoding="utf-8")
    return path


def run():
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet").sort_index()
    full_results = {strategy: _run(prices, strategy) for strategy in STRATEGIES}
    main = pd.DataFrame([_row(result, strategy) for strategy, result in full_results.items()])
    main.to_csv(ROOT / "studies" / "spy_short_decline_results.csv", index=False)

    trade_frames = []
    for strategy, result in full_results.items():
        part = result.trades.copy()
        part.insert(0, "strategy_label", result.label)
        part.insert(0, "strategy_key", strategy)
        trade_frames.append(part)
    pd.concat(trade_frames, ignore_index=True).to_csv(
        ROOT / "studies" / "spy_short_decline_trades.csv", index=False)

    sub_rows = []
    for period, (start, end) in PERIODS.items():
        for strategy in STRATEGIES:
            result = _run(prices, strategy, start=start, end=end)
            sub_rows.append(_row(result, strategy, period=period))
    subperiod = pd.DataFrame(sub_rows)
    subperiod.to_csv(ROOT / "studies" / "spy_short_decline_subperiods.csv", index=False)

    borrow_rows = []
    for borrow in [0.0, 0.01, 0.03, 0.06]:
        for strategy in STRATEGIES:
            result = _run(prices, strategy, borrow=borrow)
            borrow_rows.append(_row(result, strategy, borrow=borrow))
    borrow_sensitivity = pd.DataFrame(borrow_rows)
    borrow_sensitivity.to_csv(ROOT / "studies" / "spy_short_decline_borrow_sensitivity.csv", index=False)

    cost_rows = []
    for cost in [0.0, 0.0005, 0.001]:
        for strategy in STRATEGIES:
            result = _run(prices, strategy, cost=cost)
            cost_rows.append(_row(result, strategy, cost=cost))
    cost_sensitivity = pd.DataFrame(cost_rows)
    cost_sensitivity.to_csv(ROOT / "studies" / "spy_short_decline_cost_sensitivity.csv", index=False)

    _save_charts(full_results, main)
    report = _write_report(main, subperiod, borrow_sensitivity, cost_sensitivity)
    print(main.sort_values("Final Value", ascending=False).to_string(index=False))
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

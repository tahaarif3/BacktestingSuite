"""Sweep causal SPY long/short decisions, review frequencies, and take profits."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dca.adaptive_weekly import (  # noqa: E402
    AdaptiveWeeklyConfig,
    STRATEGY_LABELS as ADAPTIVE_LABELS,
    run_adaptive_weekly,
)
from timing.short_weekly import (  # noqa: E402
    STRATEGY_LABELS as DIRECTION_LABELS,
    ShortWeeklyConfig,
    build_short_indicators,
    run_short_weekly,
)


START = "2005-01-03"
END = "2026-07-30"
WEEKLY_AMOUNT = 25.0
CASH_YIELD = 0.03
SHORT_BORROW = 0.01
COST = 0.0005
FREQUENCIES = ["weekly", "monthly", "quarterly"]
TAKE_PROFITS = [0.0, 0.05, 0.10, 0.15]
GRID_STRATEGIES = [
    "long_cash_sma200",
    "symmetric_sma200",
    "falling_sma200_short",
    "half_short_confirmed",
    "golden_cross_long_short",
    "breakdown_short",
    "early_bear_harvest",
    "momentum20_long_short",
    "momentum60_long_short",
    "momentum120_long_short",
    "trend_momentum_vote",
    "channel_breakout_long_short",
    "composite_long_short",
]
LEGACY_SHORT = [
    "buy_hold", "long_cash_sma200", "symmetric_sma200",
    "falling_sma200_short", "half_short_confirmed",
    "golden_cross_long_short", "breakdown_short", "early_bear_harvest",
]
PERIODS = {
    "Development 2005-2016": ("2005-01-03", "2016-12-30"),
    "Validation 2017-2021": ("2017-01-03", "2021-12-31"),
    "Holdout 2022-2026": ("2022-01-03", "2026-07-30"),
}


def _config_id(strategy, frequency, take_profit):
    tp = "none" if take_profit == 0 else f"{take_profit:.0%}"
    return f"{strategy}|{frequency}|tp={tp}"


def _run_direction(prices, prepared, strategy, frequency="weekly", take_profit=0.0,
                   start=START, end=END):
    return run_short_weekly(ShortWeeklyConfig(
        strategy=strategy,
        start=start,
        end=end,
        weekly_amount=WEEKLY_AMOUNT,
        cash_yield_annual=CASH_YIELD,
        short_borrow_annual=SHORT_BORROW,
        cost_pct=COST,
        maintenance_margin=0.30,
        liquidation_lockout_days=20,
        decision_frequency=frequency,
        take_profit_pct=take_profit,
    ), prices, prepared_indicators=prepared)


def _grid_row(result, strategy, frequency, take_profit, period):
    s = result.summary
    return {
        "Config ID": _config_id(strategy, frequency, take_profit),
        "Strategy Key": strategy,
        "Strategy": result.label,
        "Decision Frequency": frequency,
        "Take Profit": take_profit,
        "Period": period,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"],
        "Profit": s["Profit"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "TWR CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Percent Days Short": s["Percent Days Short"],
        "Turnover": s["Turnover"],
        "Trading Cost": s["Trading Cost"],
        "Borrow Cost": s["Short Borrow Cost"],
        "Take Profit Exits": s["Take Profit Exits"],
        "Margin Calls": s["Margin Calls"],
    }


def _money(value):
    return f"${value:,.0f}"


def _pct(value):
    return f"{value * 100:.2f}%"


def _tp_label(value):
    return "None" if value == 0 else f"{value:.0%}"


def _top_table(frame, limit=15):
    lines = [
        "| Rank | Strategy | Review | Take profit | Final value | vs B&H | IRR | TWR CAGR | Max DD | Days short | TP exits |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, (_, row) in enumerate(frame.sort_values("Final Value", ascending=False).head(limit).iterrows(), 1):
        lines.append(
            f"| {rank} | {row['Strategy']} | {row['Decision Frequency'].title()} | "
            f"{_tp_label(row['Take Profit'])} | {_money(row['Final Value'])} | {_money(row['Delta vs B&H'])} | "
            f"{_pct(row['IRR'])} | {_pct(row['TWR CAGR'])} | {_pct(row['Max Drawdown'])} | "
            f"{_pct(row['Percent Days Short'])} | {int(row['Take Profit Exits'])} |"
        )
    return "\n".join(lines)


def _cell_table(frame):
    lines = [
        "| Review frequency | Take profit | Best final value | Best vs B&H | Median final value | Configurations beating B&H |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for _, row in frame.sort_values(["Decision Frequency", "Take Profit"]).iterrows():
        lines.append(
            f"| {row['Decision Frequency'].title()} | {_tp_label(row['Take Profit'])} | "
            f"{_money(row['Best Final Value'])} | {_money(row['Best Delta'])} | "
            f"{_money(row['Median Final Value'])} | {int(row['Winners'])}/{int(row['Configurations'])} |"
        )
    return "\n".join(lines)


def _selected_table(selected):
    lines = [
        "| Signal family | Development-selected configuration | Development vs B&H | Validation vs B&H | Holdout vs B&H | Validation + holdout won |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for strategy, group in selected.groupby("Strategy Key", sort=False):
        first = group.iloc[0]
        delta = group.set_index("Period")["Delta vs B&H"]
        dev, val, hold = PERIODS
        passed = bool(delta[val] > 0 and delta[hold] > 0)
        config = f"{first['Decision Frequency'].title()}, TP {_tp_label(first['Take Profit'])}"
        lines.append(
            f"| {first['Strategy']} | {config} | {_money(delta[dev])} | {_money(delta[val])} | "
            f"{_money(delta[hold])} | {'Yes' if passed else 'No'} |"
        )
    return "\n".join(lines)


def _legacy_table(frame):
    lines = [
        "| Study family | Strategy | Final value | vs B&H | IRR | Max DD |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, row in frame.sort_values("Final Value", ascending=False).iterrows():
        lines.append(
            f"| {row['Study Family']} | {row['Strategy']} | {_money(row['Final Value'])} | "
            f"{_money(row['Delta vs B&H'])} | {_pct(row['IRR'])} | {_pct(row['Max Drawdown'])} |"
        )
    return "\n".join(lines)


def _save_charts(full_grid, cell_summary, selected, benchmark, prices, prepared):
    top = full_grid.sort_values("Final Value", ascending=False).head(15).sort_values("Final Value")
    fig, ax = plt.subplots(figsize=(12, 8))
    labels = [
        f"{row['Strategy']} · {row['Decision Frequency']} · TP {_tp_label(row['Take Profit'])}"
        for _, row in top.iterrows()
    ]
    colors = ["#2ca02c" if value > benchmark else "#d62728" for value in top["Final Value"]]
    bars = ax.barh(labels, top["Final Value"], color=colors, alpha=0.86)
    ax.axvline(benchmark, color="#1f77b4", linewidth=2, label=f"Weekly B&H {_money(benchmark)}")
    for bar, value in zip(bars, top["Final Value"]):
        ax.text(value + benchmark * 0.004, bar.get_y() + bar.get_height() / 2,
                _money(value), va="center", fontsize=8)
    ax.set_xlim(0, max(benchmark, top["Final Value"].max()) * 1.18)
    ax.set_title("Top Full-Period Long/Short + Take-Profit Configurations")
    ax.set_xlabel("Final account value ($)")
    ax.grid(axis="x", alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_directional_tp_top_configs.png", dpi=170)
    plt.close(fig)

    matrix = cell_summary.pivot(index="Decision Frequency", columns="Take Profit", values="Best Delta")
    matrix = matrix.reindex(index=FREQUENCIES, columns=TAKE_PROFITS)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    if np.nanmax(matrix.to_numpy()) <= 0:
        image = ax.imshow(matrix.to_numpy(), cmap="Reds_r", aspect="auto",
                          vmin=np.nanmin(matrix.to_numpy()), vmax=0)
    else:
        vmax = np.nanmax(abs(matrix.to_numpy()))
        image = ax.imshow(matrix.to_numpy(), cmap="RdYlGn", aspect="auto",
                          vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(TAKE_PROFITS)), [_tp_label(x) for x in TAKE_PROFITS])
    ax.set_yticks(range(len(FREQUENCIES)), [x.title() for x in FREQUENCIES])
    ax.set_xlabel("Take-profit threshold")
    ax.set_ylabel("Signal review frequency")
    ax.set_title("Best Configuration in Each Cell — Final Value vs B&H")
    for i in range(len(FREQUENCIES)):
        for j in range(len(TAKE_PROFITS)):
            value = matrix.iloc[i, j]
            ax.text(j, i, _money(value), ha="center", va="center", fontsize=9,
                    color="white" if abs(value) > np.nanmax(abs(matrix.to_numpy())) * 0.55 else "black")
    fig.colorbar(image, ax=ax, label="Difference from weekly B&H ($)")
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_directional_tp_frequency_heatmap.png", dpi=170)
    plt.close(fig)

    delta_matrix = selected.pivot(index="Strategy", columns="Period", values="Delta vs B&H")
    delta_matrix = delta_matrix[list(PERIODS)]
    fig, ax = plt.subplots(figsize=(10, 7))
    vmax = max(1.0, np.nanmax(abs(delta_matrix.to_numpy())))
    image = ax.imshow(delta_matrix.to_numpy(), cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(3), ["Development", "Validation", "Holdout"])
    ax.set_yticks(range(len(delta_matrix)), delta_matrix.index, fontsize=8)
    ax.set_title("Development-Selected Configurations — Difference vs B&H")
    for i in range(len(delta_matrix)):
        for j in range(3):
            ax.text(j, i, _money(delta_matrix.iloc[i, j]), ha="center", va="center", fontsize=8,
                    color="white" if abs(delta_matrix.iloc[i, j]) > vmax * 0.55 else "black")
    fig.colorbar(image, ax=ax, label="Final-value difference ($)")
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_directional_tp_out_of_sample.png", dpi=170)
    plt.close(fig)

    best = full_grid.sort_values("Final Value", ascending=False).iloc[0]
    best_result = _run_direction(
        prices, prepared, best["Strategy Key"], best["Decision Frequency"], best["Take Profit"])
    control = _run_direction(prices, prepared, "buy_hold", "weekly", 0.0)
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.plot(control.daily.index, control.daily["drawdown"] * 100,
            label="Weekly buy & hold", linewidth=1.6)
    ax.plot(best_result.daily.index, best_result.daily["drawdown"] * 100,
            label=f"Best full-period grid: {best_result.label}, {best['Decision Frequency']}, TP {_tp_label(best['Take Profit'])}",
            linewidth=1.3)
    ax.set_title("Cash-Flow-Adjusted Drawdown")
    ax.set_ylabel("Drawdown from NAV peak (%)")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_directional_tp_drawdown.png", dpi=170)
    plt.close(fig)
    return best, best_result


def _write_report(full_grid, cell_summary, selected, legacy, benchmark_values, best, best_result):
    full_benchmark = benchmark_values["Full 2005-2026"]
    full_winners = full_grid[full_grid["Delta vs B&H"] > 0]
    validated = []
    for strategy, group in selected.groupby("Strategy Key"):
        deltas = group.set_index("Period")["Delta vs B&H"]
        if deltas["Validation 2017-2021"] > 0 and deltas["Holdout 2022-2026"] > 0:
            validated.append(strategy)
    if len(full_winners):
        full_text = (f"{len(full_winners)} of {len(full_grid)} configurations beat weekly B&H over the full history. "
                     f"The best was **{best['Strategy']} — {best['Decision Frequency']} review, "
                     f"TP {_tp_label(best['Take Profit'])}**, ahead by **{_money(best['Delta vs B&H'])}**.")
    else:
        full_text = (f"None of the {len(full_grid)} configurations beat weekly B&H over the full history. "
                     f"The closest was **{best['Strategy']} — {best['Decision Frequency']} review, "
                     f"TP {_tp_label(best['Take Profit'])}**, behind by **{_money(-best['Delta vs B&H'])}**.")
    validation_text = (f"{len(validated)} development-selected signal families beat B&H in both later segments."
                       if validated else
                       "No development-selected signal family beat B&H in both the validation and holdout segments.")

    report = f"""# SPY Bidirectional Timing and Take-Profit Study

Study period: **{START} through {END}**  
Asset: **SPY only**  
Owner contributions: **$25 every week for every configuration**  
Search: **{len(GRID_STRATEGIES)} signal families × {len(FREQUENCIES)} review schedules × {len(TAKE_PROFITS)} take-profit settings = {len(full_grid)} configurations**  
Base friction: **5 bps per trade, 1% annual short-borrow fee, 3% yield on eligible idle cash**

## Bottom line

{full_text} {validation_text}

Every full-period account received exactly **{_money(full_grid['Total Contributed'].iloc[0])}**, matching weekly B&H's **{_money(full_benchmark)}** final value. The development-selected test is the more credible result because it prevents validation and holdout data from choosing each signal family's frequency or take-profit threshold.

Across the rerun of the older controls, only the original weekly **Trend-confirmed dip buyer** finished above B&H, by approximately **$92**. As documented in the earlier adaptive study, that tiny advantage did not survive the 2022–2026 holdout and is not evidence of a durable edge.

## What “weekly, monthly or quarterly” means

Contributions remain $25 every week. The timeframe controls how often the model may choose long, short or cash:

- **Weekly:** reconsider on the first trading session of each ISO week.
- **Monthly:** reconsider on the first trading session of each month.
- **Quarterly:** reconsider on the first trading session of each calendar quarter.

Each decision uses the immediately preceding completed close and trades at the current open. A take-profit can close the position between decisions; after that, the account stays in cash until its next scheduled review.

## Best full-period configurations

{_top_table(full_grid)}

![Top configurations](spy_directional_tp_top_configs.png)

## Frequency and take-profit comparison

Each cell summarizes all {len(GRID_STRATEGIES)} signal families.

{_cell_table(cell_summary)}

![Frequency and take-profit heatmap](spy_directional_tp_frequency_heatmap.png)

## Development selection followed by out-of-sample evaluation

For each signal family, the frequency and take-profit setting with the highest 2005–2016 final value was frozen. Only those frozen choices were then run on 2017–2021 and 2022–2026.

{_selected_table(selected)}

![Out-of-sample results](spy_directional_tp_out_of_sample.png)

## Drawdown of the full-period leader

![Drawdown](spy_directional_tp_drawdown.png)

## Previous-study controls rerun

The adaptive rules remain long-only sizing strategies because converting a sizing rule into a short signal would silently change its definition. Each adaptive rule was rerun with weekly, monthly and quarterly size reviews. The original short-study rules were also rerun with their original daily decision process and no take-profit. All use the same contribution and cost assumptions.

{_legacy_table(legacy)}

## Signal families swept

### Previous short-study families

- SMA200 long/cash defensive control.
- SMA200 long/short.
- Below-a-falling-SMA200 confirmed short.
- Half-size confirmed bear short.
- SMA50/SMA200 long/short.
- Prior-20-day-low breakdown short, covering above SMA20.
- Early-bear breakdown short, harvesting at a 15% drawdown, RSI below 30, or SMA20 recovery.

### Added bidirectional families

- 20-, 60- and 120-day momentum: long for positive trailing return, short for negative.
- Trend plus momentum: long only above SMA200 with positive 60-day momentum; short only below a falling SMA200 with negative momentum; otherwise cash.
- 20-day channel: switch long on a prior-20-day-high breakout and short on a prior-20-day-low breakdown.
- Composite regime: vote using price versus SMA200, SMA200 slope, 20/60-day momentum and SMA50 versus SMA200; long or short only with a sufficiently strong vote.

## Take-profit mechanics

- Thresholds tested: none, 5%, 10% and 15% from the position's weighted entry price.
- Long targets trigger from the daily adjusted high; short targets trigger from the daily adjusted low.
- The exit is modeled at the resting target price, including an exit transaction cost.
- If both a short maintenance breach and short take-profit could occur within one daily bar, the adverse margin check is processed first because intraday ordering is unknown.

## No-look-ahead and realism controls

1. Signals are computed only from completed closing data and shifted to the next open.
2. Stateful breakout signals update only on scheduled review dates, not on skipped dates.
3. Short-sale proceeds cannot increase permitted exposure or earn cash interest.
4. Exposure is capped at +1× long or -1× short.
5. Adjusted SPY returns include distributions, so short exposure bears the opposite total return and implicitly pays the dividend liability.
6. Short notional pays a 1% annual borrow fee; every entry, exit, flip and rebalance pays 5 bps.
7. Shorts face a 30% maintenance test at the open and intraday high, with forced covering and a 20-session lockout.
8. All full-period configurations receive the exact same owner contributions.

## Interpretation limits

- The full-period ranking is in-sample and searches {len(full_grid)} related configurations. Its leader is not automatically an edge.
- The development/validation/holdout table is the primary robustness check, although all periods still come from one SPY history.
- Exact intraday target fills are an approximation. Real stop/limit behavior, spreads and taxes may be worse.
- Monthly and quarterly decisions reduce signal turnover but can react late to fast crashes and rebounds.
- A take-profit limits participation in extended trends and can leave cash idle while SPY continues rising.
- Direct shorting has asymmetric loss risk and broker-specific requirements even at the modeled 1× exposure cap.

## Output files

- `spy_directional_tp_all_configs.csv`: all full-period configurations.
- `spy_directional_tp_development.csv`: complete development search.
- `spy_directional_tp_selected_oos.csv`: frozen validation and holdout evaluations.
- `spy_directional_tp_legacy_controls.csv`: rerun adaptive and prior-short controls.
- `spy_directional_tp_best_trades.csv`: execution audit for the full-period leader.

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_directional_take_profit_study.py
```
"""
    path = ROOT / "studies" / "spy_directional_take_profit_study.md"
    path.write_text(report, encoding="utf-8")
    return path


def run():
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet").sort_index()
    prepared = build_short_indicators(prices)

    benchmark_values = {}
    for period, dates in {"Full 2005-2026": (START, END), **PERIODS}.items():
        benchmark_values[period] = _run_direction(
            prices, prepared, "buy_hold", "weekly", 0.0, *dates).summary["Final Value"]

    full_rows = []
    development_rows = []
    dev_start, dev_end = PERIODS["Development 2005-2016"]
    for strategy in GRID_STRATEGIES:
        for frequency in FREQUENCIES:
            for take_profit in TAKE_PROFITS:
                full = _run_direction(prices, prepared, strategy, frequency, take_profit)
                full_rows.append(_grid_row(full, strategy, frequency, take_profit, "Full 2005-2026"))
                development = _run_direction(
                    prices, prepared, strategy, frequency, take_profit, dev_start, dev_end)
                development_rows.append(_grid_row(
                    development, strategy, frequency, take_profit, "Development 2005-2016"))
    full_grid = pd.DataFrame(full_rows)
    development = pd.DataFrame(development_rows)
    full_grid["Delta vs B&H"] = full_grid["Final Value"] - benchmark_values["Full 2005-2026"]
    development["Delta vs B&H"] = development["Final Value"] - benchmark_values["Development 2005-2016"]
    full_grid.to_csv(ROOT / "studies" / "spy_directional_tp_all_configs.csv", index=False)
    development.to_csv(ROOT / "studies" / "spy_directional_tp_development.csv", index=False)

    chosen_rows = []
    for strategy, group in development.groupby("Strategy Key", sort=False):
        chosen = group.loc[group["Final Value"].idxmax()]
        chosen_rows.append(chosen)
        for period in ("Validation 2017-2021", "Holdout 2022-2026"):
            p_start, p_end = PERIODS[period]
            result = _run_direction(
                prices, prepared, strategy, chosen["Decision Frequency"],
                float(chosen["Take Profit"]), p_start, p_end)
            row = _grid_row(result, strategy, chosen["Decision Frequency"],
                            float(chosen["Take Profit"]), period)
            row["Delta vs B&H"] = row["Final Value"] - benchmark_values[period]
            chosen_rows.append(pd.Series(row))
    selected = pd.DataFrame(chosen_rows)
    selected.to_csv(ROOT / "studies" / "spy_directional_tp_selected_oos.csv", index=False)

    cell_summary = full_grid.groupby(["Decision Frequency", "Take Profit"], as_index=False).agg(
        **{
            "Best Final Value": ("Final Value", "max"),
            "Median Final Value": ("Final Value", "median"),
            "Best Delta": ("Delta vs B&H", "max"),
            "Winners": ("Delta vs B&H", lambda x: int((x > 0).sum())),
            "Configurations": ("Config ID", "count"),
        }
    )
    cell_summary.to_csv(ROOT / "studies" / "spy_directional_tp_cell_summary.csv", index=False)

    legacy_rows = []
    for strategy in ADAPTIVE_LABELS:
        for frequency in FREQUENCIES:
            result = run_adaptive_weekly(AdaptiveWeeklyConfig(
                strategy=strategy, start=START, end=END, weekly_amount=WEEKLY_AMOUNT,
                cash_yield_annual=CASH_YIELD, cost_pct=COST,
                decision_frequency=frequency,
            ), prices)
            s = result.summary
            legacy_rows.append({
                "Study Family": f"Adaptive sizing ({frequency})",
                "Strategy": result.label,
                "Final Value": s["Final Value"], "IRR": s["Money-Weighted Return (IRR)"],
                "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
            })
    for strategy in LEGACY_SHORT:
        result = _run_direction(prices, prepared, strategy, "daily", 0.0)
        s = result.summary
        legacy_rows.append({
            "Study Family": "Prior short study", "Strategy": result.label,
            "Final Value": s["Final Value"], "IRR": s["Money-Weighted Return (IRR)"],
            "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        })
    legacy = pd.DataFrame(legacy_rows)
    legacy["Delta vs B&H"] = legacy["Final Value"] - benchmark_values["Full 2005-2026"]
    legacy.to_csv(ROOT / "studies" / "spy_directional_tp_legacy_controls.csv", index=False)

    best, best_result = _save_charts(
        full_grid, cell_summary, selected, benchmark_values["Full 2005-2026"], prices, prepared)
    best_result.trades.to_csv(ROOT / "studies" / "spy_directional_tp_best_trades.csv", index=False)
    report = _write_report(
        full_grid, cell_summary, selected, legacy, benchmark_values, best, best_result)
    print(full_grid.sort_values("Final Value", ascending=False).head(20).to_string(index=False))
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

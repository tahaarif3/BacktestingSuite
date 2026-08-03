"""Study small temporary SPY short overlays and equivalent cash de-risking."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timing.short_weekly import build_short_indicators  # noqa: E402
from timing.temporary_hedge import (  # noqa: E402
    EXIT_LABELS,
    STRATEGY_LABELS,
    HedgeConfig,
    run_temporary_hedge,
)


START = "2005-01-03"
END = "2026-07-30"
STRATEGIES = list(STRATEGY_LABELS)
HEDGE_SIZES = [0.25, 0.50]
FREQUENCIES = ["daily", "weekly", "monthly"]
EXIT_PLANS = list(EXIT_LABELS)
PERIODS = {
    "Development 2005-2016": ("2005-01-03", "2016-12-30"),
    "Validation 2017-2021": ("2017-01-03", "2021-12-31"),
    "Holdout 2022-2026": ("2022-01-03", "2026-07-30"),
}


def _config_id(strategy, size, frequency, exit_plan, vehicle):
    return f"{strategy}|{size:.0%}|{frequency}|{exit_plan}|{vehicle}"


def _run(prices, prepared, strategy, size, frequency, exit_plan,
         vehicle="short_overlay", start=START, end=END, borrow=0.01):
    return run_temporary_hedge(HedgeConfig(
        strategy=strategy,
        vehicle=vehicle,
        hedge_fraction=size,
        decision_frequency=frequency,
        exit_plan=exit_plan,
        weekly_amount=25.0,
        start=start,
        end=end,
        cash_yield_annual=0.03,
        short_borrow_annual=borrow,
        cost_pct=0.0005,
        maintenance_margin=0.30,
    ), prices, prepared)


def _row(result, strategy, size, frequency, exit_plan, vehicle, period):
    s = result.summary
    return {
        "Config ID": _config_id(strategy, size, frequency, exit_plan, vehicle),
        "Strategy Key": strategy,
        "Strategy": STRATEGY_LABELS[strategy],
        "Hedge Size": size,
        "Decision Frequency": frequency,
        "Exit Plan": exit_plan,
        "Exit Label": EXIT_LABELS[exit_plan],
        "Vehicle": vehicle,
        "Period": period,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"],
        "Profit": s["Profit"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "TWR CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Average Net Exposure": s["Average Net Exposure"],
        "Average Gross Exposure": s["Average Gross Exposure"],
        "Percent Days Hedged": s["Percent Days Hedged"],
        "Hedge Entries": s["Hedge Entries"],
        "Hedge Exits": s["Hedge Exits"],
        "Turnover": s["Turnover"],
        "Trading Cost": s["Trading Cost"],
        "Borrow Cost": s["Short Borrow Cost"],
        "Cash Interest": s["Cash Interest"],
        "Margin Calls": s["Margin Calls"],
    }


def _money(value):
    return f"${value:,.0f}"


def _pct(value):
    return f"{value * 100:.2f}%"


def _top_table(frame, limit=15):
    lines = [
        "| Rank | Trigger | Hedge | Review | Exit | Final value | vs B&H | IRR | Max DD | Days hedged | Borrow cost |",
        "|---:|---|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, (_, row) in enumerate(frame.sort_values("Final Value", ascending=False).head(limit).iterrows(), 1):
        lines.append(
            f"| {rank} | {row['Strategy']} | {_pct(row['Hedge Size'])} | "
            f"{row['Decision Frequency'].title()} | {row['Exit Label']} | {_money(row['Final Value'])} | "
            f"{_money(row['Delta vs B&H'])} | {_pct(row['IRR'])} | {_pct(row['Max Drawdown'])} | "
            f"{_pct(row['Percent Days Hedged'])} | {_money(row['Borrow Cost'])} |"
        )
    return "\n".join(lines)


def _paired_table(pairs):
    summary = pairs.groupby(["Hedge Size", "Decision Frequency"], as_index=False).agg(
        **{
            "Best Overlay": ("Overlay Final", "max"),
            "Best Cash": ("Cash Final", "max"),
            "Median Overlay Minus Cash": ("Overlay Minus Cash", "median"),
            "Overlay Wins": ("Overlay Minus Cash", lambda x: int((x > 0).sum())),
            "Pairs": ("Config ID", "count"),
        }
    )
    lines = [
        "| Hedge size | Review | Best short-overlay final | Best cash-de-risk final | Median overlay minus cash | Overlay wins |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"| {_pct(row['Hedge Size'])} | {row['Decision Frequency'].title()} | "
            f"{_money(row['Best Overlay'])} | {_money(row['Best Cash'])} | "
            f"{_money(row['Median Overlay Minus Cash'])} | {int(row['Overlay Wins'])}/{int(row['Pairs'])} |"
        )
    return "\n".join(lines)


def _selected_table(selected):
    lines = [
        "| Trigger / hedge size | Development-selected review and exit | Development vs B&H | Validation vs B&H | Holdout vs B&H | Won both later periods |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for (_, _), group in selected.groupby(["Strategy Key", "Hedge Size"], sort=False):
        first = group.iloc[0]
        delta = group.set_index("Period")["Delta vs B&H"]
        names = list(PERIODS)
        passed = delta[names[1]] > 0 and delta[names[2]] > 0
        lines.append(
            f"| {first['Strategy']} / {_pct(first['Hedge Size'])} | "
            f"{first['Decision Frequency'].title()}, {first['Exit Label']} | "
            f"{_money(delta[names[0]])} | {_money(delta[names[1]])} | {_money(delta[names[2]])} | "
            f"{'Yes' if passed else 'No'} |"
        )
    return "\n".join(lines)


def _borrow_table(frame):
    lines = [
        "| Annual borrow fee | Final value | vs B&H | Total borrow cost |",
        "|---:|---:|---:|---:|",
    ]
    for _, row in frame.sort_values("Borrow Rate").iterrows():
        lines.append(
            f"| {_pct(row['Borrow Rate'])} | {_money(row['Final Value'])} | "
            f"{_money(row['Delta vs B&H'])} | {_money(row['Borrow Cost'])} |"
        )
    return "\n".join(lines)


def _episode_table(result):
    trades = result.trades[result.trades["action"].isin(["enter_hedge", "exit_hedge"])]
    episodes = [
        ("Financial crisis", "2007-01-01", "2010-12-31"),
        ("COVID crash", "2019-01-01", "2021-12-31"),
    ]
    lines = [
        "| Episode | Trade date | Action | SPY price | Reason |",
        "|---|---:|---|---:|---|",
    ]
    for episode, start, end in episodes:
        part = trades[(trades["trade_date"] >= start) & (trades["trade_date"] <= end)]
        for _, row in part.iterrows():
            lines.append(
                f"| {episode} | {row['trade_date']:%Y-%m-%d} | "
                f"{'Enter 50% hedge' if row['action'] == 'enter_hedge' else 'Cover hedge'} | "
                f"${row['price']:.2f} | {row['reason']} |"
            )
    return "\n".join(lines)


def _save_charts(overlay, pairs, selected, benchmark, benchmark_result,
                 best_result, defensive_result):
    top = overlay.sort_values("Final Value", ascending=False).head(15).sort_values("Final Value")
    labels = [
        f"{row['Strategy']} · {row['Hedge Size']:.0%} · {row['Decision Frequency']} · {row['Exit Label']}"
        for _, row in top.iterrows()
    ]
    fig, ax = plt.subplots(figsize=(12, 8))
    bars = ax.barh(labels, top["Final Value"], color="#d62728", alpha=0.84)
    ax.axvline(benchmark, color="#1f77b4", linewidth=2, label=f"Weekly B&H {_money(benchmark)}")
    for bar, value in zip(bars, top["Final Value"]):
        ax.text(value + benchmark * 0.003, bar.get_y() + bar.get_height() / 2,
                _money(value), va="center", fontsize=8)
    ax.set_xlim(0, benchmark * 1.16)
    ax.set_title("Top Temporary SPY Short-Overlay Configurations")
    ax.set_xlabel("Final account value ($)")
    ax.grid(axis="x", alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_temporary_hedge_top.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 6.5))
    ax.scatter(pairs["Cash Final"], pairs["Overlay Final"], alpha=0.45, s=22)
    lo = min(pairs["Cash Final"].min(), pairs["Overlay Final"].min())
    hi = max(pairs["Cash Final"].max(), pairs["Overlay Final"].max())
    ax.plot([lo, hi], [lo, hi], linestyle="--", color="black", linewidth=1,
            label="Equal result before implementation differences")
    ax.set_xlabel("Partial sale / cash final value ($)")
    ax.set_ylabel("Explicit SPY short-overlay final value ($)")
    ax.set_title("Same Net Exposure: Short Overlay vs Partial Sale")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_temporary_hedge_overlay_vs_cash.png", dpi=170)
    plt.close(fig)

    matrix = selected.pivot_table(
        index=["Strategy", "Hedge Size"], columns="Period", values="Delta vs B&H")
    matrix = matrix[list(PERIODS)]
    vmax = max(1.0, np.nanmax(abs(matrix.to_numpy())))
    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(matrix.to_numpy(), cmap="RdYlGn", vmin=-vmax, vmax=vmax, aspect="auto")
    ax.set_xticks(range(3), ["Development", "Validation", "Holdout"])
    ax.set_yticks(range(len(matrix)),
                  [f"{name} · {size:.0%}" for name, size in matrix.index], fontsize=8)
    ax.set_title("Development-Selected Temporary Hedges — Difference vs B&H")
    for i in range(len(matrix)):
        for j in range(3):
            value = matrix.iloc[i, j]
            ax.text(j, i, _money(value), ha="center", va="center", fontsize=8,
                    color="white" if abs(value) > vmax * 0.55 else "black")
    fig.colorbar(image, ax=ax, label="Final-value difference ($)")
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_temporary_hedge_oos.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 6.5))
    for result, label, width in [
        (benchmark_result, "Weekly buy & hold", 1.6),
        (best_result, "Best-ending hedge", 1.35),
        (defensive_result, "Shallowest-drawdown hedge", 1.25),
    ]:
        ax.plot(result.daily.index, result.daily["drawdown"] * 100,
                label=label, linewidth=width)
    ax.set_title("Cash-Flow-Adjusted Drawdown of Selected Hedge Configurations")
    ax.set_ylabel("Drawdown from NAV peak (%)")
    ax.grid(alpha=0.22)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_temporary_hedge_drawdown.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.step(best_result.daily.index, best_result.daily["net_exposure"], where="post",
            label="Best-ending hedge net exposure", linewidth=1.1)
    ax.step(defensive_result.daily.index, defensive_result.daily["net_exposure"], where="post",
            label="Shallowest-drawdown hedge net exposure", linewidth=1.0, alpha=0.8)
    ax.set_ylim(0.35, 1.05)
    ax.set_ylabel("Net SPY exposure")
    ax.set_title("When the Temporary Hedges Reduced Market Exposure")
    ax.grid(alpha=0.22)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_temporary_hedge_exposure.png", dpi=170)
    plt.close(fig)


def _write_report(overlay, pairs, selected, borrow, benchmark, best, defensive, best_result):
    winners = overlay[overlay["Delta vs B&H"] > 0]
    validated = []
    for key, group in selected.groupby(["Strategy Key", "Hedge Size"]):
        d = group.set_index("Period")["Delta vs B&H"]
        if d["Validation 2017-2021"] > 0 and d["Holdout 2022-2026"] > 0:
            validated.append(key)
    if len(winners):
        conclusion = (f"{len(winners)} of {len(overlay)} explicit short-overlay configurations beat weekly B&H over the full history. "
                      f"The best was **{best['Strategy']}**, {_pct(best['Hedge Size'])} hedge, "
                      f"{best['Decision Frequency']} review, {best['Exit Label']}, ahead by "
                      f"**{_money(best['Delta vs B&H'])}**.")
    else:
        conclusion = (f"None of the {len(overlay)} explicit short-overlay configurations beat weekly B&H over the full history. "
                      f"The closest was **{best['Strategy']}**, {_pct(best['Hedge Size'])} hedge, "
                      f"{best['Decision Frequency']} review, {best['Exit Label']}, behind by "
                      f"**{_money(-best['Delta vs B&H'])}**.")
    robustness = (f"{len(validated)} development-selected hedge families won in both later periods."
                  if validated else
                  "No development-selected hedge configuration beat B&H in both validation and holdout.")
    best_cash = float(pairs["Cash Final"].max())
    overlay_pair_wins = int((pairs["Overlay Minus Cash"] > 0).sum())

    report = f"""# SPY Temporary Short-Hedge Study

Study period: **{START} through {END}**  
Portfolio: **1× long SPY core with a temporary 25% or 50% SPY short overlay**  
Owner contribution: **$25 every week for every configuration**  
Search: **{len(overlay)} short-overlay configurations plus {len(pairs)} economically equivalent partial-sale controls**  
Costs: **5 bps per trade, 1% annual SPY borrow fee, 3% eligible cash yield**

## Bottom line

{conclusion} {robustness}

Every full-period account received exactly **{_money(overlay['Total Contributed'].iloc[0])}**. Weekly B&H finished at **{_money(benchmark)}**.

The most important structural finding is that shorting SPY while already long SPY does not create a new source of market return. A 1× long core plus a 0.25× SPY short has **0.75× net SPY exposure**, economically similar to selling 25% of the long position. The explicit overlay then adds borrow fees, gross exposure and additional execution complexity.

The best equivalent partial-sale version finished at **{_money(best_cash)}**, **{_money(best_cash - benchmark)} above B&H**. The explicit short overlay beat its paired cash implementation in **{overlay_pair_wins} of {len(pairs)}** comparisons.

## Best full-period explicit hedges

{_top_table(overlay)}

![Top hedge configurations](spy_temporary_hedge_top.png)

## What the leading hedge did in 2008 and 2020

{_episode_table(best_result)}

The winning historical pattern was not a perfect top-to-bottom short. It captured an early 10% decline with a half-sized hedge, covered, and restored full long exposure. The core SPY position remained invested throughout, allowing participation in the eventual rebound.

## Explicit short overlay versus partial sale

Each dot uses the same trigger, hedge size, review schedule and exit. Before costs and cash yield, paired implementations have the same net SPY exposure.

{_paired_table(pairs)}

![Short overlay versus cash de-risking](spy_temporary_hedge_overlay_vs_cash.png)

## Development selection and later-period evaluation

For each trigger and hedge size, the review schedule and exit with the highest 2005–2016 final value was frozen. Those choices were then evaluated separately on 2017–2021 and 2022–2026.

{_selected_table(selected)}

![Out-of-sample hedge results](spy_temporary_hedge_oos.png)

## Drawdown and hedge timing

The shallowest-drawdown configuration was **{defensive['Strategy']}**, {_pct(defensive['Hedge Size'])}, {defensive['Decision Frequency']} review with **{defensive['Exit Label']}**. It produced a **{_pct(defensive['Max Drawdown'])}** maximum drawdown and **{_money(defensive['Final Value'])}** final value.

![Selected hedge drawdowns](spy_temporary_hedge_drawdown.png)

![Selected hedge exposure](spy_temporary_hedge_exposure.png)

## Borrow-cost sensitivity of the full-period leader

{_borrow_table(borrow)}

## Hedge-entry triggers

- **Below SMA200:** hedge whenever the scheduled prior close is below SMA200.
- **Falling SMA200:** require both price below SMA200 and SMA200 lower than 20 sessions earlier.
- **20-day breakdown:** require a new prior-20-day low below a falling SMA200.
- **Volatility breakdown:** require price below SMA200, negative 20-day momentum and annualized 20-day volatility above 30%.
- **Drawdown plus momentum:** require at least a 10% closing drawdown and negative 20-day return.
- **Fast crash:** require price below SMA50, an 8% or worse 20-day return and annualized volatility above 25%.

Entry signals are reviewed daily, weekly or monthly depending on the configuration. Weekly contributions do not force a new signal decision.

## Hedge exits

- **Trigger clears:** restore the full long core when the entry condition is false at the prior close.
- **SMA20 bullish reversal:** restore full long exposure after a completed close above SMA20.
- **6% rebound trail or SMA20:** track the lowest completed close during the hedge and cover if SPY rebounds 6%, or after an SMA20 recovery.
- **10% hedge profit or SMA20:** cover after SPY falls 10% from hedge entry, or after an SMA20 recovery.

After a hedge exits, its trigger must clear before another hedge can be armed. This prevents taking a profit and mechanically re-shorting the same uninterrupted decline every week.

## No-look-ahead and accounting controls

1. Entry and closing-signal exits use the previous completed close and trade at the next open.
2. The rebound trail uses the lowest **completed close** observed before the current session. A gap beyond the cover stop fills at the less favorable opening price.
3. Fixed hedge-profit orders can execute from adjusted daily lows at a resting target price.
4. The explicit overlay keeps a 1× long book and a separate short book capped at 0.50×; it cannot reinvest short-sale proceeds as added long exposure.
5. Short notional pays borrow daily and adjusted SPY returns impose the dividend liability.
6. Both long and short trades pay transaction costs, including weekly contribution rebalancing.
7. Cash de-risking earns the assumed cash yield; restricted short collateral does not.
8. Trade logs retain `signal_date` and `trade_date` for causal auditing.

## Limitations

- Long and short positions in the identical security may be netted by a broker rather than maintained as separate books. The overlay is best interpreted as the economics of a separate hedge vehicle.
- Taxes, varying borrow rates, inverse-ETF decay, options pricing and broker-specific margin rules are excluded.
- Adjusted OHLC bars are research data rather than executable quotes.
- The full ranking searches many related configurations. The development-selected validation and holdout results are the primary evidence.
- A hedge can reduce crash damage but will normally sacrifice return during false alarms and rapid V-shaped recoveries.

## Output files

- `spy_temporary_hedge_overlays.csv`: all explicit short-overlay results.
- `spy_temporary_hedge_derisk.csv`: paired partial-sale/cash results.
- `spy_temporary_hedge_pairs.csv`: direct implementation comparison.
- `spy_temporary_hedge_selected_oos.csv`: development-selected later-period results.
- `spy_temporary_hedge_best_trades.csv`: full-period leader audit.

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_temporary_hedge_study.py
```
"""
    path = ROOT / "studies" / "spy_temporary_hedge_study.md"
    path.write_text(report, encoding="utf-8")
    return path


def run():
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet").sort_index()
    prepared = build_short_indicators(prices)
    benchmark_result = run_temporary_hedge(HedgeConfig(
        strategy="sma200", vehicle="derisk_cash", hedge_fraction=0.0,
        decision_frequency="weekly", exit_plan="signal_clear",
        start=START, end=END, weekly_amount=25, cash_yield_annual=0.03,
        short_borrow_annual=0.01, cost_pct=0.0005,
    ), prices, prepared)
    benchmark = benchmark_result.summary["Final Value"]

    overlay_rows = []
    derisk_rows = []
    development_rows = []
    dev_start, dev_end = PERIODS["Development 2005-2016"]
    for strategy in STRATEGIES:
        for size in HEDGE_SIZES:
            for frequency in FREQUENCIES:
                for exit_plan in EXIT_PLANS:
                    overlay_result = _run(prices, prepared, strategy, size, frequency, exit_plan)
                    overlay_rows.append(_row(overlay_result, strategy, size, frequency,
                                             exit_plan, "short_overlay", "Full 2005-2026"))
                    cash_result = _run(prices, prepared, strategy, size, frequency, exit_plan,
                                       vehicle="derisk_cash")
                    derisk_rows.append(_row(cash_result, strategy, size, frequency,
                                            exit_plan, "derisk_cash", "Full 2005-2026"))
                    dev_result = _run(prices, prepared, strategy, size, frequency, exit_plan,
                                      start=dev_start, end=dev_end)
                    development_rows.append(_row(dev_result, strategy, size, frequency,
                                                  exit_plan, "short_overlay", "Development 2005-2016"))

    overlay = pd.DataFrame(overlay_rows)
    derisk = pd.DataFrame(derisk_rows)
    development = pd.DataFrame(development_rows)
    for frame in (overlay, derisk):
        frame["Delta vs B&H"] = frame["Final Value"] - benchmark
    development_benchmark = run_temporary_hedge(HedgeConfig(
        strategy="sma200", vehicle="derisk_cash", hedge_fraction=0.0,
        start=dev_start, end=dev_end, decision_frequency="weekly", exit_plan="signal_clear",
    ), prices, prepared).summary["Final Value"]
    development["Delta vs B&H"] = development["Final Value"] - development_benchmark
    overlay.to_csv(ROOT / "studies" / "spy_temporary_hedge_overlays.csv", index=False)
    derisk.to_csv(ROOT / "studies" / "spy_temporary_hedge_derisk.csv", index=False)
    development.to_csv(ROOT / "studies" / "spy_temporary_hedge_development.csv", index=False)

    pairs = overlay[["Config ID", "Strategy Key", "Hedge Size", "Decision Frequency", "Exit Plan",
                     "Final Value"]].rename(columns={"Final Value": "Overlay Final"})
    cash_pairs = derisk[["Strategy Key", "Hedge Size", "Decision Frequency", "Exit Plan",
                         "Final Value"]].rename(columns={"Final Value": "Cash Final"})
    pairs = pairs.merge(cash_pairs, on=["Strategy Key", "Hedge Size", "Decision Frequency", "Exit Plan"])
    pairs["Overlay Minus Cash"] = pairs["Overlay Final"] - pairs["Cash Final"]
    pairs.to_csv(ROOT / "studies" / "spy_temporary_hedge_pairs.csv", index=False)

    period_benchmarks = {"Development 2005-2016": development_benchmark}
    for period in ("Validation 2017-2021", "Holdout 2022-2026"):
        p_start, p_end = PERIODS[period]
        period_benchmarks[period] = run_temporary_hedge(HedgeConfig(
            strategy="sma200", vehicle="derisk_cash", hedge_fraction=0.0,
            start=p_start, end=p_end, decision_frequency="weekly", exit_plan="signal_clear",
        ), prices, prepared).summary["Final Value"]

    chosen_rows = []
    for (strategy, size), group in development.groupby(["Strategy Key", "Hedge Size"], sort=False):
        chosen = group.loc[group["Final Value"].idxmax()]
        chosen_rows.append(chosen)
        for period in ("Validation 2017-2021", "Holdout 2022-2026"):
            p_start, p_end = PERIODS[period]
            result = _run(prices, prepared, strategy, size,
                          chosen["Decision Frequency"], chosen["Exit Plan"],
                          start=p_start, end=p_end)
            row = _row(result, strategy, size, chosen["Decision Frequency"],
                       chosen["Exit Plan"], "short_overlay", period)
            row["Delta vs B&H"] = row["Final Value"] - period_benchmarks[period]
            chosen_rows.append(pd.Series(row))
    selected = pd.DataFrame(chosen_rows)
    selected.to_csv(ROOT / "studies" / "spy_temporary_hedge_selected_oos.csv", index=False)

    best = overlay.loc[overlay["Final Value"].idxmax()]
    defensive_pool = overlay[overlay["Final Value"] >= benchmark * 0.75]
    defensive = defensive_pool.loc[defensive_pool["Max Drawdown"].idxmax()]
    best_result = _run(prices, prepared, best["Strategy Key"], best["Hedge Size"],
                       best["Decision Frequency"], best["Exit Plan"])
    defensive_result = _run(prices, prepared, defensive["Strategy Key"], defensive["Hedge Size"],
                            defensive["Decision Frequency"], defensive["Exit Plan"])
    best_result.trades.to_csv(ROOT / "studies" / "spy_temporary_hedge_best_trades.csv", index=False)

    borrow_rows = []
    for rate in [0.0, 0.01, 0.03, 0.06]:
        result = _run(prices, prepared, best["Strategy Key"], best["Hedge Size"],
                      best["Decision Frequency"], best["Exit Plan"], borrow=rate)
        borrow_rows.append({
            "Borrow Rate": rate, "Final Value": result.summary["Final Value"],
            "Delta vs B&H": result.summary["Final Value"] - benchmark,
            "Borrow Cost": result.summary["Short Borrow Cost"],
        })
    borrow = pd.DataFrame(borrow_rows)
    borrow.to_csv(ROOT / "studies" / "spy_temporary_hedge_borrow_sensitivity.csv", index=False)

    _save_charts(overlay, pairs, selected, benchmark, benchmark_result,
                 best_result, defensive_result)
    report = _write_report(overlay, pairs, selected, borrow, benchmark, best, defensive, best_result)
    print(overlay.sort_values("Final Value", ascending=False).head(20).to_string(index=False))
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

"""Validate the frozen weekly SMA75 contribution gate against SPY B&H."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dca.contribution_gate import (  # noqa: E402
    ContributionGateConfig,
    run_contribution_gate,
)
from studies.run_spy_hedge_edge_validation import (  # noqa: E402
    crisis_attribution,
    deflated_sharpe_probability,
    known_trial_count,
    moving_block_bootstrap,
)


PRICE_PATH = ROOT / "data" / "spy_daily_yfinance_1993.parquet"
YIELD_PATH = ROOT / "data" / "dgs3mo_fred.parquet"
START = "1994-01-03"
END = "2026-07-30"
WEEKLY_AMOUNT = 25.0
BASE_COST = 0.0005
RANDOM_RUNS = 500
SEED = 20260803
SEGMENTS = [
    ("1994–1999", "1994-01-03", "1999-12-31"),
    ("2000–2004", "2000-01-03", "2004-12-31"),
    ("2005–2009", "2005-01-03", "2009-12-31"),
    ("2010–2014", "2010-01-04", "2014-12-31"),
    ("2015–2019", "2015-01-02", "2019-12-31"),
    ("2020–2022", "2020-01-02", "2022-12-30"),
    ("2023–2026", "2023-01-03", "2026-07-30"),
]


def load_prices() -> pd.DataFrame:
    prices = pd.read_parquet(PRICE_PATH).sort_index()
    prices.index = pd.DatetimeIndex(prices.index).tz_localize(None)
    return prices[["open", "close"]].loc[:END]


def load_cash_yield() -> tuple[pd.Series, str]:
    """Load the U.S. 3-month Treasury constant-maturity yield from FRED."""
    if YIELD_PATH.exists():
        frame = pd.read_parquet(YIELD_PATH)
        series = frame.iloc[:, 0]
        series.index = pd.DatetimeIndex(series.index).tz_localize(None)
        return series.astype(float), "FRED DGS3MO cache"

    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS3MO"
    frame = pd.read_csv(url)
    frame.columns = ["date", "yield_pct"]
    frame["date"] = pd.to_datetime(frame["date"])
    frame["yield_pct"] = pd.to_numeric(frame["yield_pct"], errors="coerce")
    frame = frame.dropna().set_index("date").sort_index()
    annual = (frame["yield_pct"] / 100.0).rename("annual_cash_yield")
    annual.to_frame().to_parquet(YIELD_PATH)
    return annual, "FRED DGS3MO"


def run_gate(prices, yields, *, ma_period=75, gate_mode="above_sma",
             start=START, end=END, cost=BASE_COST, fixed_yield=None,
             custom_gate=None, label=None):
    annual = None if fixed_yield is not None else yields
    return run_contribution_gate(
        ContributionGateConfig(
            label=label or ("Weekly B&H" if gate_mode == "always" else f"SMA{ma_period} gate"),
            start=start, end=end, weekly_amount=WEEKLY_AMOUNT,
            ma_period=ma_period, gate_mode=gate_mode, cost_pct=cost,
            fixed_cash_yield=0.0 if fixed_yield is None else fixed_yield,
        ),
        prices,
        annual_cash_yield=annual,
        custom_weekly_gate=custom_gate,
    )


def active_log_returns(result, benchmark) -> pd.Series:
    return (np.log(result.daily["nav"]).diff()
            - np.log(benchmark.daily["nav"]).diff()).dropna()


def result_row(key, label, result, benchmark, period="1994–2026") -> dict:
    s = result.summary
    return {
        "Key": key, "Strategy": label, "Period": period,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"], "Profit": s["Profit"],
        "Delta vs B&H": s["Final Value"] - benchmark.summary["Final Value"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "TWR CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Average Invested Fraction": s["Average Invested Fraction"],
        "Average Reserve Cash": s["Average Reserve Cash"],
        "Cash Interest": s["Cash Interest"], "Trading Cost": s["Trading Cost"],
        "Delayed Contributions": s["Closed-Gate Contributions"],
        "Percent Delayed": s["Percent Contributions Delayed"],
    }


def chronological_tests(prices, yields) -> pd.DataFrame:
    rows = []
    for name, start, end in SEGMENTS:
        benchmark = run_gate(prices, yields, gate_mode="always", start=start, end=end)
        for ma in [60, 75, 90]:
            result = run_gate(prices, yields, ma_period=ma, start=start, end=end)
            rows.append({
                "Period": name, "MA": ma,
                "Final Value": result.summary["Final Value"],
                "B&H Final": benchmark.summary["Final Value"],
                "Delta vs B&H": result.summary["Final Value"] - benchmark.summary["Final Value"],
                "Max Drawdown": result.summary["Cash-Flow Adjusted Max Drawdown"],
                "Delayed Contributions": result.summary["Closed-Gate Contributions"],
            })
    return pd.DataFrame(rows)


def random_delay_controls(prices, yields, frozen) -> pd.DataFrame:
    decisions = frozen.decisions.copy()
    dates = pd.DatetimeIndex(decisions["trade_date"])
    states = decisions["gate_open"].to_numpy(dtype=bool)
    blocks = [states[i:i + 4] for i in range(0, len(states), 4)]
    rng = np.random.default_rng(SEED)
    rows = []
    for run in range(RANDOM_RUNS):
        order = rng.permutation(len(blocks))
        shuffled = np.concatenate([blocks[i] for i in order])[:len(states)]
        custom = pd.Series(False, index=prices.index)
        custom.loc[dates] = shuffled
        result = run_gate(
            prices, yields, gate_mode="custom", custom_gate=custom,
            label=f"Random block delay {run + 1}",
        )
        rows.append({
            "Run": run + 1, "Final Value": result.summary["Final Value"],
            "TWR CAGR": result.summary["Time-Weighted CAGR"],
            "Max Drawdown": result.summary["Cash-Flow Adjusted Max Drawdown"],
            "Delayed Contributions": result.summary["Closed-Gate Contributions"],
        })
    return pd.DataFrame(rows)


def stress_tests(prices, yields) -> pd.DataFrame:
    rows = []
    for cash_case, fixed in [("0%", 0.0), ("3%", 0.03), ("Historical T-bill", None)]:
        for cost in [0.0005, 0.0010, 0.0020]:
            result = run_gate(prices, yields, cost=cost, fixed_yield=fixed)
            benchmark = run_gate(prices, yields, gate_mode="always", cost=cost)
            rows.append({
                "Cash Yield": cash_case, "Cost Per Side": cost,
                "Final Value": result.summary["Final Value"],
                "Delta vs B&H": result.summary["Final Value"] - benchmark.summary["Final Value"],
                "Cash Interest": result.summary["Cash Interest"],
                "Trading Cost": result.summary["Trading Cost"],
            })
    return pd.DataFrame(rows)


def release_episodes(frozen) -> pd.DataFrame:
    decisions = frozen.decisions.copy()
    decisions["Reserve Released"] = (decisions["cash_deployed"] - decisions["contribution"]).clip(lower=0.0)
    releases = decisions[decisions["Reserve Released"] > 1.0].copy()
    releases["Weeks Accumulated"] = (releases["Reserve Released"] / WEEKLY_AMOUNT).round().astype(int)
    return releases.sort_values("Reserve Released", ascending=False).head(12)[[
        "trade_date", "signal_date", "prior_close", "sma", "cash_deployed",
        "Reserve Released", "Weeks Accumulated", "execution_open",
    ]]


def money(v):
    return f"${v:,.0f}"


def pct(v):
    return f"{v * 100:.2f}%"


def main_table(frame):
    lines = [
        "| Strategy | Contributed | Final value | vs B&H | IRR | TWR CAGR | Max DD | Delayed | Cash interest |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in frame.sort_values("Final Value", ascending=False).iterrows():
        lines.append(
            f"| {r['Strategy']} | {money(r['Total Contributed'])} | {money(r['Final Value'])} | "
            f"{money(r['Delta vs B&H'])} | {pct(r['IRR'])} | {pct(r['TWR CAGR'])} | "
            f"{pct(r['Max Drawdown'])} | {int(r['Delayed Contributions'])} | {money(r['Cash Interest'])} |"
        )
    return "\n".join(lines)


def save_charts(results, benchmark, segments, randoms) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for key, label in [
        ("buy_hold", "Weekly B&H"), ("sma60", "SMA60 gate"),
        ("sma75", "SMA75 gate"), ("sma90", "SMA90 gate"),
    ]:
        result = benchmark if key == "buy_hold" else results[key]
        ax.plot(result.daily.index, result.daily["drawdown"] * 100,
                label=label, linewidth=1.7 if key == "buy_hold" else 1.2)
    ax.set_title("Contribution-gate validation — cash-flow-adjusted drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_sma75_contribution_drawdown.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.plot(results["sma75"].daily.index, results["sma75"].daily["cash"],
            color="#d97706", linewidth=1.3)
    ax.set_title("Frozen SMA75 reserve cash")
    ax.set_ylabel("Reserve cash ($)")
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_sma75_contribution_reserve.png", dpi=170)
    plt.close(fig)

    pivot = segments.pivot(index="Period", columns="MA", values="Delta vs B&H")
    fig, ax = plt.subplots(figsize=(11, 6))
    pivot.plot(kind="bar", ax=ax, width=0.8)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Chronological segment difference vs weekly B&H")
    ax.set_ylabel("Ending-value difference ($)")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", alpha=0.2)
    ax.legend(title="SMA period")
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_sma75_contribution_segments.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 5.8))
    ax.hist(randoms["Final Value"], bins=30, color="#94a3b8", edgecolor="white")
    ax.axvline(results["sma75"].summary["Final Value"], color="#16a34a", linewidth=2,
               label=f"SMA75 {money(results['sma75'].summary['Final Value'])}")
    ax.axvline(benchmark.summary["Final Value"], color="#2563eb", linewidth=2,
               label=f"B&H {money(benchmark.summary['Final Value'])}")
    ax.set_title("SMA75 versus 500 block-shuffled delay schedules")
    ax.set_xlabel("Final account value ($)")
    ax.grid(axis="y", alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_sma75_contribution_random_control.png", dpi=170)
    plt.close(fig)


def write_report(source, prices, main, segments, crisis, stresses, randoms,
                 episodes, stats, benchmark, frozen, known_trials) -> Path:
    frozen_row = main.loc[main["Key"] == "sma75"].iloc[0]
    zero_row = main.loc[main["Key"] == "sma75_zero"].iloc[0]
    center_segments = segments[segments["MA"] == 75]
    wins = int((center_segments["Delta vs B&H"] > 0).sum())
    neighborhood = main[main["Key"].isin(["sma60", "sma75", "sma90"])]
    neighbor_wins = int((neighborhood["Delta vs B&H"] > 0).sum())
    outside = crisis.loc[crisis["Segment"] == "All dates outside both windows", "Active Log Return"].iloc[0]
    random_percentile = float((randoms["Final Value"] < frozen_row["Final Value"]).mean())
    random_95 = float(randoms["Final Value"].quantile(0.95))
    stress_wins = int((stresses["Delta vs B&H"] > 0).sum())
    bh_dd = main.loc[main["Key"] == "buy_hold", "Max Drawdown"].iloc[0]

    gates = {
        "Full history beats weekly B&H": frozen_row["Delta vs B&H"] > 0,
        "Time-weighted CAGR beats weekly B&H":
            frozen_row["TWR CAGR"] > main.loc[main["Key"] == "buy_hold", "TWR CAGR"].iloc[0],
        "1994–2004 combined evidence beats B&H":
            center_segments[center_segments["Period"].isin(["1994–1999", "2000–2004"])]["Delta vs B&H"].sum() > 0,
        "At least 70% of chronological segments beat B&H": wins / len(center_segments) >= 0.70,
        "Positive median segment result": center_segments["Delta vs B&H"].median() > 0,
        "SMA60, SMA75 and SMA90 all beat B&H": neighbor_wins == 3,
        "SMA75 beats B&H with 0% cash yield": zero_row["Delta vs B&H"] > 0,
        "Positive active return outside 2008 and 2020": outside > 0,
        "Bootstrap 95% interval above zero": stats["Bootstrap CI Low"] > 0,
        "Deflated Sharpe probability at least 95%": stats["Deflated Sharpe Probability"] >= 0.95,
        "SMA75 beats 95th percentile random delay": frozen_row["Final Value"] > random_95,
        "At least 70% of cost/yield stresses beat B&H": stress_wins / len(stresses) >= 0.70,
        "Drawdown improves by at least 3 percentage points": frozen_row["Max Drawdown"] - bh_dd >= 0.03,
    }
    passed = sum(gates.values())
    essential = list(gates.values())[:10]
    status = "SUPPORTED" if passed >= 10 and all(essential) else (
        "PROMISING BUT UNCONFIRMED" if passed >= 6 else "REJECTED AS A PROVEN EDGE"
    )

    segment_lines = [
        "| Period | SMA75 final | B&H final | Difference | Delayed contributions |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, r in center_segments.iterrows():
        segment_lines.append(
            f"| {r['Period']} | {money(r['Final Value'])} | {money(r['B&H Final'])} | "
            f"{money(r['Delta vs B&H'])} | {int(r['Delayed Contributions'])} |"
        )
    crisis_lines = ["| Segment | Active log return | Share of total |", "|---|---:|---:|"]
    for _, r in crisis.iterrows():
        crisis_lines.append(
            f"| {r['Segment']} | {pct(r['Active Log Return'])} | "
            f"{pct(r['Share of Total Active Return'])} |"
        )
    stress_lines = ["| Cash yield | Cost | Final value | vs B&H | Cash interest |",
                    "|---|---:|---:|---:|---:|"]
    for _, r in stresses.iterrows():
        stress_lines.append(
            f"| {r['Cash Yield']} | {pct(r['Cost Per Side'])} | {money(r['Final Value'])} | "
            f"{money(r['Delta vs B&H'])} | {money(r['Cash Interest'])} |"
        )
    episode_lines = ["| Re-entry date | Signal date | Reserve deployed | Approx. weeks accumulated | Execution open |",
                     "|---|---|---:|---:|---:|"]
    for _, r in episodes.iterrows():
        episode_lines.append(
            f"| {r['trade_date']:%Y-%m-%d} | {r['signal_date']:%Y-%m-%d} | "
            f"{money(r['cash_deployed'])} | {int(r['Weeks Accumulated'])} | ${r['execution_open']:.2f} |"
        )
    gate_lines = [f"- {'PASS' if ok else 'FAIL'} — {name}" for name, ok in gates.items()]

    report = f"""# SPY SMA75 Contribution-Gate Validation

Study period: **{START} through {END}**  
SPY history available: **{prices.index.min():%Y-%m-%d} through {prices.index.max():%Y-%m-%d}**  
Contribution: **$25 on the first trading session of every ISO week**  
Cash-yield source: **{source}**  
Base transaction cost: **5 basis points per purchase**

## Verdict

**{status} — {passed}/{len(gates)} predeclared validation gates passed.**

The frozen SMA75 contribution gate ended at **{money(frozen_row['Final Value'])}**, versus **{money(benchmark.summary['Final Value'])}** for immediate weekly B&H, a difference of **{money(frozen_row['Delta vs B&H'])}**. With cash interest removed, its difference was **{money(zero_row['Delta vs B&H'])}**.

Despite the higher ending balance, SMA75's time-weighted CAGR was **{pct(frozen_row['TWR CAGR'])}**, below B&H at **{pct(main.loc[main['Key'] == 'buy_hold', 'TWR CAGR'].iloc[0])}**. Its cumulative active log return was also negative. Equal contributions make ending dollars comparable, but the exact sequence of returns and growing deposits can still produce a small dollar win without a superior unitized return stream. This is a central reason the result is not confirmed.

The strategy won **{wins}/{len(center_segments)}** chronological segments and ranked at the **{pct(random_percentile)} percentile** of 500 block-shuffled delay schedules. Its bootstrap 95% interval for annualized active log return was **{pct(stats['Bootstrap CI Low'])} to {pct(stats['Bootstrap CI High'])}**.

## Frozen rule

Existing SPY shares are never sold.

1. Add $25 on the first trading session of each week.
2. At that session's open, compare the **prior completed close** with its SMA75.
3. If the prior close is above SMA75, invest the new $25 and all accumulated reserve cash at the current open.
4. Otherwise retain the new contribution in cash until a later weekly review opens the gate.
5. Apply the cash yield only to the reserve and charge the configured purchase cost.

This is stricter than the exploratory report's older implementation, which could release reserved cash when a daily gate reopened. The confirmation figures therefore replace—not reproduce—the exploratory headline.

## Full-history results

{main_table(main)}

![Drawdown comparison](spy_sma75_contribution_drawdown.png)

![Reserve cash](spy_sma75_contribution_reserve.png)

## Chronological evidence

Each segment begins with no shares and receives its own weekly contributions. The rule is unchanged.

{chr(10).join(segment_lines)}

![Chronological segments](spy_sma75_contribution_segments.png)

## Parameter neighborhood

SMA60, SMA75 and SMA90 were run as a robustness neighborhood. SMA75 remains the frozen center regardless of which result ranks highest; the neighbors are not a new optimization search.

- Neighboring rules beating B&H: **{neighbor_wins}/3**.
- SMA60 difference: **{money(main.loc[main['Key'] == 'sma60', 'Delta vs B&H'].iloc[0])}**.
- SMA75 difference: **{money(frozen_row['Delta vs B&H'])}**.
- SMA90 difference: **{money(main.loc[main['Key'] == 'sma90', 'Delta vs B&H'].iloc[0])}**.

## Is the result timing or cash interest?

- SMA75 with historical T-bill yield: **{money(frozen_row['Final Value'])}**.
- SMA75 with 0% reserve yield: **{money(zero_row['Final Value'])}**.
- Dollar benefit associated with historical reserve interest: **{money(frozen_row['Final Value'] - zero_row['Final Value'])}**.
- Immediate weekly B&H: **{money(benchmark.summary['Final Value'])}**.

A rule that wins only after crediting cash interest has not demonstrated that SMA75 improved purchase timing. It has demonstrated that earning interest on delayed contributions helped in this sample.

## Crisis dependence

{chr(10).join(crisis_lines)}

## Random-delay control

The weekly open/closed states were divided into four-week blocks and shuffled 500 times. This preserves the approximate amount and clustering of delayed capital while removing the SMA75 relationship to market prices.

- Random-delay median final value: **{money(randoms['Final Value'].median())}**.
- Random-delay 95th percentile: **{money(random_95)}**.
- Random schedules finishing below SMA75: **{int((randoms['Final Value'] < frozen_row['Final Value']).sum())}/{len(randoms)}**.

![Random-delay comparison](spy_sma75_contribution_random_control.png)

## Cost and yield stress

{chr(10).join(stress_lines)}

Stress cases beating the fixed-cost B&H benchmark: **{stress_wins}/{len(stresses)}**.

## Largest reserve deployments

{chr(10).join(episode_lines)}

These are not sales or market exits. They are accumulated weekly contributions finally entering SPY after the gate reopened.

## Statistical checks

- Annualized mean active log return: **{pct(stats['Annualized Mean Excess'])}**.
- Bootstrap probability of a non-positive edge: **{pct(stats['Bootstrap P <= 0'])}**.
- Bootstrap 95% interval: **{pct(stats['Bootstrap CI Low'])} to {pct(stats['Bootstrap CI High'])}**.
- Annualized active Sharpe: **{stats['Annualized Active Sharpe']:.2f}**.
- Deflated Sharpe probability after **{known_trials}** known prior trials: **{pct(stats['Deflated Sharpe Probability'])}**.

## Validation gates

{chr(10).join(gate_lines)}

## Limitations

1. The rule was discovered after inspecting 2005–2026, and the 1993–2026 SPY history has now been reused across many studies. Chronological segmentation cannot restore a truly untouched holdout.
2. DGS3MO is a Treasury-market reference yield, not a guarantee that a brokerage account would have earned that rate after fund expenses, spreads or taxes.
3. Adjusted Yahoo OHLC data are used. They are practical for total-return research but are not raw historical execution prices.
4. Taxes on cash interest are excluded. The strategy makes purchases only and does not realize gains from existing SPY shares.
5. Random block schedules are a diagnostic null model, not a perfect representation of every possible contribution-delay strategy.
6. The strategy differs from B&H only during below-SMA75 weeks. There are far fewer independent gate cycles than daily observations.
7. A small ending-value advantage may be real but economically too weak to distinguish reliably from market-path noise.

## Decision

Treat the SMA75 gate as confirmed only if the verdict is **SUPPORTED**. A higher full-period balance by itself is insufficient. If the 0%-yield rule, chronological folds, bootstrap interval or random-delay comparison fail, immediate weekly B&H remains the better-supported default.

The only source of genuinely new evidence now is a frozen forward paper log containing each prior-close signal, weekly opening execution price, contribution, reserve balance and simultaneous B&H purchase.

## Reproduction

- `spy_sma75_contribution_results.csv`
- `spy_sma75_contribution_segments.csv`
- `spy_sma75_contribution_stress.csv`
- `spy_sma75_contribution_random_controls.csv`
- `spy_sma75_contribution_crisis.csv`
- `spy_sma75_contribution_releases.csv`
- `spy_sma75_contribution_decisions.csv`

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_sma75_contribution_validation.py
```
"""
    path = ROOT / "studies" / "spy_sma75_contribution_validation.md"
    path.write_text(report, encoding="utf-8")
    return path


def run() -> None:
    prices = load_prices()
    yields, yield_source = load_cash_yield()
    benchmark = run_gate(prices, yields, gate_mode="always", label="Weekly B&H")
    results = {}
    main_rows = [result_row("buy_hold", "Weekly B&H", benchmark, benchmark)]
    for ma in [60, 75, 90]:
        key = f"sma{ma}"
        result = run_gate(prices, yields, ma_period=ma, label=f"SMA{ma} gate + historical yield")
        results[key] = result
        main_rows.append(result_row(key, f"SMA{ma} gate + historical yield", result, benchmark))
    zero = run_gate(prices, yields, ma_period=75, fixed_yield=0.0,
                    label="SMA75 gate + 0% cash yield")
    fixed3 = run_gate(prices, yields, ma_period=75, fixed_yield=0.03,
                      label="SMA75 gate + fixed 3% yield")
    results["sma75_zero"] = zero
    results["sma75_fixed3"] = fixed3
    main_rows.extend([
        result_row("sma75_zero", "SMA75 gate + 0% cash yield", zero, benchmark),
        result_row("sma75_fixed3", "SMA75 gate + fixed 3% yield", fixed3, benchmark),
    ])
    main = pd.DataFrame(main_rows)

    segments = chronological_tests(prices, yields)
    frozen = results["sma75"]
    active = active_log_returns(frozen, benchmark)
    crisis = crisis_attribution(active)
    randoms = random_delay_controls(prices, yields, frozen)
    stresses = stress_tests(prices, yields)
    episodes = release_episodes(frozen)
    prior_trials, _ = known_trial_count()
    known_trials = prior_trials + 19 + 3
    stats = {
        **moving_block_bootstrap(active),
        **deflated_sharpe_probability(active, known_trials),
    }

    artifacts = {
        "spy_sma75_contribution_results.csv": main,
        "spy_sma75_contribution_segments.csv": segments,
        "spy_sma75_contribution_stress.csv": stresses,
        "spy_sma75_contribution_random_controls.csv": randoms,
        "spy_sma75_contribution_crisis.csv": crisis,
        "spy_sma75_contribution_releases.csv": episodes,
        "spy_sma75_contribution_decisions.csv": frozen.decisions,
    }
    for filename, frame in artifacts.items():
        frame.to_csv(ROOT / "studies" / filename, index=False)
    save_charts(results, benchmark, segments, randoms)
    report = write_report(
        yield_source, prices, main, segments, crisis, stresses, randoms,
        episodes, stats, benchmark, frozen, known_trials,
    )
    print(main.sort_values("Final Value", ascending=False).to_string(index=False))
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

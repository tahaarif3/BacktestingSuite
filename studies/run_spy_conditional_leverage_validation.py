"""Confirmation-oriented SPY conditional-leverage study.

The primary rule is frozen before results are inspected: review monthly, hold
1.25x only when price is above a rising SMA200, six-month momentum is positive,
and 20-day annualized volatility is below 20%; hold 1.0x in a bullish but
high-volatility regime and 0.75x otherwise.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from studies.run_spy_hedge_edge_validation import (  # noqa: E402
    crisis_attribution,
    deflated_sharpe_probability,
    known_trial_count,
    moving_block_bootstrap,
)
from timing.realistic import RealisticConfig, run_realistic  # noqa: E402


DATA_PATH = ROOT / "data" / "spy_daily_yfinance_1993.parquet"
START = "1994-01-03"
END = "2026-07-30"
WEEKLY_AMOUNT = 25.0
BASE_BORROW = 0.10
BASE_COST = 0.0005
BASE_CASH_YIELD = 0.03


def load_prices() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError(
            "Run studies/run_spy_hedge_edge_validation.py first to build inception history."
        )
    prices = pd.read_parquet(DATA_PATH).sort_index()
    prices.index = pd.DatetimeIndex(prices.index).tz_localize(None)
    return prices[["open", "high", "low", "close"]].loc[:END]


def monthly_targets(raw: pd.Series, default: float = 1.0) -> pd.Series:
    """Use each month-end close to set exposure for the next month's open."""
    idx = raw.index
    periods = idx.to_period("M")
    flags = np.r_[periods[:-1] != periods[1:], True]
    values = np.full(len(raw), float(default))
    state = float(default)
    raw_values = raw.to_numpy(dtype=float)
    for i in range(len(raw)):
        if flags[i] and np.isfinite(raw_values[i]):
            state = raw_values[i]
        values[i] = state
    return pd.Series(values, index=idx)


def indicators(prices: pd.DataFrame, sma_period: int = 200) -> pd.DataFrame:
    close = prices["close"].astype(float)
    out = pd.DataFrame(index=prices.index)
    out["close"] = close
    out["sma"] = close.rolling(sma_period, min_periods=sma_period).mean()
    out["sma_rising"] = out["sma"] > out["sma"].shift(20)
    out["momentum126"] = close / close.shift(126) - 1.0
    out["vol20"] = close.pct_change().rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252)
    out["bull"] = (close > out["sma"]) & out["sma_rising"] & (out["momentum126"] > 0)
    return out


def target_library(prices: pd.DataFrame) -> tuple[dict[str, pd.Series], dict[str, str], list[str]]:
    targets: dict[str, pd.Series] = {}
    labels: dict[str, str] = {}
    plateau_keys: list[str] = []

    targets["buy_hold"] = pd.Series(1.0, index=prices.index)
    labels["buy_hold"] = "Weekly SPY buy & hold"
    for exposure in [1.15, 1.25, 1.35]:
        key = f"constant_{round(exposure * 100)}"
        targets[key] = pd.Series(exposure, index=prices.index)
        labels[key] = f"Constant {exposure:.2f}x exposure"

    base = indicators(prices, 200)
    for cap in [1.15, 1.25, 1.35]:
        key = f"trend_{round(cap * 100)}"
        raw = pd.Series(np.where(base["bull"], cap, 1.0), index=prices.index)
        targets[key] = monthly_targets(raw)
        labels[key] = f"Trend-confirmed leverage, {cap:.2f}x cap"

    for target_vol in [0.12, 0.15, 0.18]:
        key = f"vol_{round(target_vol * 100)}"
        raw = (target_vol / base["vol20"]).clip(0.75, 1.25).fillna(1.0)
        targets[key] = monthly_targets(raw)
        labels[key] = f"Volatility target {target_vol:.0%}, 0.75–1.25x"

    def add_hybrid(key: str, label: str, *, cap: float = 1.25,
                   vol_threshold: float = 0.20, bear: float = 0.75,
                   sma_period: int = 200) -> None:
        ind = base if sma_period == 200 else indicators(prices, sma_period)
        raw = pd.Series(
            np.where(ind["bull"] & (ind["vol20"] < vol_threshold), cap,
                     np.where(ind["bull"], 1.0, bear)),
            index=prices.index,
        )
        raw = raw.where(ind["sma"].notna(), 1.0)
        targets[key] = monthly_targets(raw)
        labels[key] = label
        plateau_keys.append(key)

    add_hybrid("hybrid_center", "Frozen hybrid: 1.25x / 1.00x / 0.75x")
    add_hybrid("hybrid_cap115", "Hybrid neighbor: 1.15x bull cap", cap=1.15)
    add_hybrid("hybrid_cap135", "Hybrid neighbor: 1.35x bull cap", cap=1.35)
    add_hybrid("hybrid_vol15", "Hybrid neighbor: 15% low-vol threshold", vol_threshold=0.15)
    add_hybrid("hybrid_vol25", "Hybrid neighbor: 25% low-vol threshold", vol_threshold=0.25)
    add_hybrid("hybrid_bear50", "Hybrid neighbor: 0.50x bear exposure", bear=0.50)
    add_hybrid("hybrid_bear100", "Hybrid neighbor: 1.00x bear exposure", bear=1.00)
    add_hybrid("hybrid_sma180", "Hybrid neighbor: SMA180", sma_period=180)
    add_hybrid("hybrid_sma220", "Hybrid neighbor: SMA220", sma_period=220)
    return targets, labels, plateau_keys


def config(label: str, *, borrow: float = BASE_BORROW, cost: float = BASE_COST,
           cash_yield: float = BASE_CASH_YIELD) -> RealisticConfig:
    return RealisticConfig(
        label=label, start_capital=0.0, contribution_amount=WEEKLY_AMOUNT,
        contribution_cadence="weekly", contribution_day="start",
        contribution_buy_rule="always", cash_yield_annual=cash_yield,
        borrow_annual=borrow, cost_pct=cost, rebalance_band=0.03,
        initial_margin=0.50, maintenance_margin=0.40,
        liquidation_lockout_days=20, enable_margin_calls=True,
        max_exposure=1.50,
    )


def run_target(prices: pd.DataFrame, target: pd.Series, label: str,
               start: str = START, end: str = END, **cfg_kwargs):
    mask = (prices.index >= start) & (prices.index <= end)
    frame = prices.loc[mask]
    exposure = target.reindex(frame.index).to_numpy(dtype=float)
    return run_realistic(config(label, **cfg_kwargs), frame, exposure)


def daily_frame(result) -> pd.DataFrame:
    return pd.DataFrame({
        "value": result.value, "nav": result.nav,
        "drawdown": result.drawdown, "exposure": result.exposure,
    }, index=pd.to_datetime(result.dates))


def active_log_returns(result, benchmark) -> pd.Series:
    left = np.log(daily_frame(result)["nav"]).diff()
    right = np.log(daily_frame(benchmark)["nav"]).diff()
    return (left - right).dropna()


def row(key: str, label: str, result, benchmark, period: str) -> dict:
    s = result.summary
    return {
        "Key": key, "Strategy": label, "Period": period,
        "Total Contributed": s["Total Contributed"], "Final Value": s["Final Value"],
        "Profit": s["Profit"], "Delta vs B&H": s["Final Value"] - benchmark.summary["Final Value"],
        "IRR": s["IRR"], "TWR CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Max Drawdown"], "Avg Exposure": s["Avg Exposure"],
        "Turnover / yr": s["Turnover / yr"], "Trading Cost": s["Trading Cost"],
        "Financing Cost": s["Financing Cost"], "Cash Interest": s["Cash Interest"],
        "Margin Calls": s["Margin Calls"],
    }


def walk_forward(prices, targets, labels, keys) -> tuple[pd.DataFrame, pd.DataFrame]:
    fixed_rows, selected_rows = [], []
    for test_start in range(2004, 2026, 3):
        test_end = min(test_start + 2, 2026)
        start_s = f"{test_start}-01-03"
        end_s = str(min(pd.Timestamp(f"{test_end}-12-31"), prices.index.max()).date())
        benchmark = run_target(prices, targets["buy_hold"], labels["buy_hold"], start_s, end_s)
        train_values, test_values = {}, {}
        for key in keys:
            train = run_target(prices, targets[key], labels[key], START, f"{test_start - 1}-12-31")
            test = run_target(prices, targets[key], labels[key], start_s, end_s)
            train_values[key] = train.summary["Final Value"]
            test_values[key] = test.summary["Final Value"]
            fixed_rows.append({
                "Test Period": f"{test_start}-{test_end}", "Key": key,
                "Strategy": labels[key], "Final Value": test.summary["Final Value"],
                "B&H Final": benchmark.summary["Final Value"],
                "Delta vs B&H": test.summary["Final Value"] - benchmark.summary["Final Value"],
            })
        choice = max(train_values, key=train_values.get)
        selected_rows.append({
            "Test Period": f"{test_start}-{test_end}", "Selected Key": choice,
            "Selected Strategy": labels[choice],
            "Delta vs B&H": test_values[choice] - benchmark.summary["Final Value"],
        })
    return pd.DataFrame(fixed_rows), pd.DataFrame(selected_rows)


def pbo(active: dict[str, pd.Series]) -> dict:
    common = pd.concat(active, axis=1).dropna()
    years = sorted(common.index.year.unique())
    blocks = [years[i:i + 3] for i in range(0, len(years), 3) if len(years[i:i + 3]) >= 2]
    matrix = np.array([
        [common.loc[common.index.year.isin(block), key].mean() for key in common.columns]
        for block in blocks
    ])
    failures = cases = 0
    half = len(blocks) // 2
    for train_idx_tuple in combinations(range(len(blocks)), half):
        train_idx = np.array(train_idx_tuple)
        train_set = set(train_idx_tuple)
        test_idx = np.array([i for i in range(len(blocks)) if i not in train_set])
        winner = int(np.argmax(matrix[train_idx].mean(axis=0)))
        scores = matrix[test_idx].mean(axis=0)
        rank = int(np.argsort(np.argsort(scores))[winner]) + 1
        percentile = rank / (len(scores) + 1)
        failures += int(percentile <= 0.5)
        cases += 1
    return {"PBO": failures / cases, "Splits": cases}


def stress_tests(prices, primary_target, benchmark_target, constant_target) -> pd.DataFrame:
    rows = []
    for borrow in [0.08, 0.10, 0.12]:
        for cost in [0.0005, 0.0010, 0.0020]:
            for cash_yield in [0.0, 0.03]:
                kwargs = {"borrow": borrow, "cost": cost, "cash_yield": cash_yield}
                primary = run_target(prices, primary_target, "Frozen hybrid", **kwargs)
                benchmark = run_target(prices, benchmark_target, "B&H", **kwargs)
                constant = run_target(prices, constant_target, "Constant exposure", **kwargs)
                rows.append({
                    "Borrow Rate": borrow, "Cost Per Side": cost,
                    "Cash Yield": cash_yield, "Final Value": primary.summary["Final Value"],
                    "B&H Final": benchmark.summary["Final Value"],
                    "Constant Final": constant.summary["Final Value"],
                    "Delta vs B&H": primary.summary["Final Value"] - benchmark.summary["Final Value"],
                    "Delta vs Constant": primary.summary["Final Value"] - constant.summary["Final Value"],
                    "Financing Cost": primary.summary["Financing Cost"],
                    "Margin Calls": primary.summary["Margin Calls"],
                })
    return pd.DataFrame(rows)


def money(value):
    return f"${value:,.0f}"


def pct(value):
    return f"{value * 100:.2f}%"


def main_table(frame: pd.DataFrame) -> str:
    lines = [
        "| Strategy | Contributed | Final value | vs B&H | IRR | Max DD | Avg exposure | Financing | Margin calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in frame.sort_values("Final Value", ascending=False).iterrows():
        lines.append(
            f"| {r['Strategy']} | {money(r['Total Contributed'])} | {money(r['Final Value'])} | "
            f"{money(r['Delta vs B&H'])} | {pct(r['IRR'])} | {pct(r['Max Drawdown'])} | "
            f"{pct(r['Avg Exposure'])} | {money(r['Financing Cost'])} | {int(r['Margin Calls'])} |"
        )
    return "\n".join(lines)


def save_charts(results, benchmark, constant_match, folds, plateau) -> None:
    selected = {
        "Weekly B&H": benchmark,
        "Frozen hybrid": results["hybrid_center"],
        "Constant matched exposure": constant_match,
        "Trend 1.25x cap": results["trend_125"],
        "Vol target 15%": results["vol_15"],
    }
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for label, result in selected.items():
        frame = daily_frame(result)
        ax.plot(frame.index, frame["drawdown"] * 100, label=label,
                linewidth=1.8 if label == "Weekly B&H" else 1.2)
    ax.set_title("Conditional leverage validation — cash-flow-adjusted drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_conditional_leverage_drawdown.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(12, 5.5))
    frame = daily_frame(results["hybrid_center"])
    ax.step(frame.index, frame["exposure"], where="post", linewidth=1.0, color="#9467bd")
    ax.axhline(1.0, color="black", linewidth=1, linestyle="--")
    ax.set_title("Frozen hybrid realized exposure")
    ax.set_ylabel("SPY exposure")
    ax.set_ylim(0.45, 1.42)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_conditional_leverage_exposure.png", dpi=170)
    plt.close(fig)

    fixed = folds[folds["Key"].isin(["hybrid_center", "trend_125", "vol_15"])]
    pivot = fixed.pivot(index="Test Period", columns="Strategy", values="Delta vs B&H")
    fig, ax = plt.subplots(figsize=(11.5, 6))
    pivot.plot(kind="bar", ax=ax, width=0.8)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Chronological fold difference vs weekly B&H")
    ax.set_ylabel("Ending-value difference ($)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.2)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_conditional_leverage_walkforward.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10.5, 6))
    plot = plateau.sort_values("Delta vs B&H")
    colors = np.where(plot["Delta vs B&H"] > 0, "#2ca02c", "#d62728")
    ax.barh(plot["Strategy"], plot["Delta vs B&H"], color=colors, alpha=0.82)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_title("Frozen hybrid parameter neighborhood")
    ax.set_xlabel("Ending-value difference vs weekly B&H ($)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_conditional_leverage_plateau.png", dpi=170)
    plt.close(fig)


def write_report(prices, main, early, folds, selected, plateau, crisis, stresses,
                 stats, pbo_result, primary, benchmark, constant_match,
                 trial_detail, known_trials) -> Path:
    primary_row = main.loc[main["Key"] == "hybrid_center"].iloc[0]
    benchmark_row = main.loc[main["Key"] == "buy_hold"].iloc[0]
    match_row = row("constant_match", "Constant matched exposure", constant_match,
                    benchmark, "1994-2026")
    early_primary = early.loc[early["Key"] == "hybrid_center"].iloc[0]
    fixed = folds[folds["Key"] == "hybrid_center"]
    fixed_wins = int((fixed["Delta vs B&H"] > 0).sum())
    selected_wins = int((selected["Delta vs B&H"] > 0).sum())
    plateau_bh = int((plateau["Delta vs B&H"] > 0).sum())
    plateau_constant = int((plateau["Final Value"] > constant_match.summary["Final Value"]).sum())
    outside = crisis.loc[crisis["Segment"] == "All dates outside both windows", "Active Log Return"].iloc[0]

    gates = {
        "Full history beats weekly B&H": primary_row["Delta vs B&H"] > 0,
        "Full history beats constant matched exposure": primary_row["Final Value"] > match_row["Final Value"],
        "Positive earlier 1994–2004 evidence": early_primary["Delta vs B&H"] > 0,
        "At least 70% of chronological folds beat B&H": fixed_wins / len(fixed) >= 0.70,
        "At least 70% of anchored selections beat B&H": selected_wins / len(selected) >= 0.70,
        "Positive active return outside 2008 and 2020": outside > 0,
        "Bootstrap 95% interval above zero": stats["Bootstrap CI Low"] > 0,
        "Deflated Sharpe probability at least 95%": stats["Deflated Sharpe Probability"] >= 0.95,
        "PBO below 20%": pbo_result["PBO"] < 0.20,
        "At least 70% of hybrid neighbors beat B&H": plateau_bh / len(plateau) >= 0.70,
        "At least 70% of neighbors beat matched constant exposure": plateau_constant / len(plateau) >= 0.70,
        "Maximum drawdown no worse than 40%": primary_row["Max Drawdown"] >= -0.40,
        "No margin calls": primary_row["Margin Calls"] == 0 and stresses["Margin Calls"].sum() == 0,
        "At least 70% of stress cases beat both controls":
            ((stresses["Delta vs B&H"] > 0) & (stresses["Delta vs Constant"] > 0)).mean() >= 0.70,
    }
    passed = sum(gates.values())
    essential = list(gates.values())[:8]
    status = "SUPPORTED" if passed >= 11 and all(essential) else (
        "PROMISING BUT UNCONFIRMED" if passed >= 7 else "REJECTED AS A PROVEN EDGE"
    )

    fold_summary = folds.groupby("Strategy", as_index=False).agg(
        Wins=("Delta vs B&H", lambda x: int((x > 0).sum())),
        Folds=("Delta vs B&H", "count"), Median=("Delta vs B&H", "median"),
        Total=("Delta vs B&H", "sum"),
    )
    fold_lines = ["| Strategy | Folds won | Median difference | Sum of differences |",
                  "|---|---:|---:|---:|"]
    for _, r in fold_summary.iterrows():
        fold_lines.append(f"| {r['Strategy']} | {int(r['Wins'])}/{int(r['Folds'])} | "
                          f"{money(r['Median'])} | {money(r['Total'])} |")
    crisis_lines = ["| Segment | Active log return | Share of total |", "|---|---:|---:|"]
    for _, r in crisis.iterrows():
        crisis_lines.append(f"| {r['Segment']} | {pct(r['Active Log Return'])} | "
                            f"{pct(r['Share of Total Active Return'])} |")
    gate_lines = [f"- {'PASS' if ok else 'FAIL'} — {name}" for name, ok in gates.items()]
    trial_lines = [f"- `{name}`: {count} rows" for name, count in trial_detail]
    stress_wins = int(((stresses["Delta vs B&H"] > 0) &
                       (stresses["Delta vs Constant"] > 0)).sum())

    report = f"""# SPY Conditional-Leverage Edge Validation

Study period: **{START} through {END}**  
SPY data available: **{prices.index.min():%Y-%m-%d} through {prices.index.max():%Y-%m-%d}**  
Contribution: **$25 on the first trading day of every ISO week**  
Execution: **month-end signal, next session's open, 3% rebalance band**  
Base financing: **10% annual margin rate, 3% positive cash yield, 5 bps per trade side**

## Verdict

**{status} — {passed}/{len(gates)} predeclared validation gates passed.**

The frozen hybrid finished at **{money(primary_row['Final Value'])}**, versus **{money(benchmark_row['Final Value'])}** for weekly B&H and **{money(match_row['Final Value'])}** for constant **{match_row['Avg Exposure']:.2f}x** exposure. Its maximum drawdown was **{pct(primary_row['Max Drawdown'])}**, and it generated **{primary_row['Margin Calls']:.0f}** margin calls.

The constant-exposure comparison is essential. If the conditional rule cannot beat an untimed portfolio carrying the same average exposure, its apparent improvement comes from leverage rather than timing skill.

## Frozen primary rule

At every month-end, use only completed SPY data and change exposure at the next session's open:

- **1.25x** when close is above SMA200, SMA200 is above its value 20 sessions earlier, six-month return is positive, and 20-day annualized volatility is below 20%.
- **1.00x** when the trend conditions are bullish but volatility is at least 20%.
- **0.75x** otherwise.
- Exposure is implemented through SPY margin, not a daily-reset leveraged ETF.

## Full-history results

{main_table(pd.concat([main, pd.DataFrame([match_row])], ignore_index=True))}

![Drawdown comparison](spy_conditional_leverage_drawdown.png)

![Frozen exposure](spy_conditional_leverage_exposure.png)

## Earlier-period evidence

The 1994–2004 segment predates the original 2005–2026 studies, although it was consumed by the preceding hedge validation and is no longer untouched.

{main_table(early)}

## Walk-forward evidence

Fixed candidates were restarted and tested in forward-moving three-year segments. An anchored selector separately chose among the trend 1.25x, volatility-target 15%, and frozen hybrid rules using only prior years.

{chr(10).join(fold_lines)}

The frozen hybrid beat B&H in **{fixed_wins}/{len(fixed)}** folds. The anchored selector won **{selected_wins}/{len(selected)}** subsequent folds.

![Walk-forward results](spy_conditional_leverage_walkforward.png)

## Crisis dependence

Daily active log return versus B&H was attributed to the 2008 and 2020 windows and all remaining dates:

{chr(10).join(crisis_lines)}

## Parameter neighborhood

The center was varied one input at a time: 1.15x/1.25x/1.35x bull caps, 15%/20%/25% low-volatility thresholds, 0.50x/0.75x/1.00x bear exposure, and SMA180/200/220. **{plateau_bh}/{len(plateau)}** points beat B&H and **{plateau_constant}/{len(plateau)}** beat constant matched exposure.

![Parameter neighborhood](spy_conditional_leverage_plateau.png)

## Financing and execution stress

The frozen hybrid was rerun at 8%/10%/12% margin rates, 5/10/20 bps transaction costs, and 0%/3% cash yields. Each case was compared with B&H and constant matched exposure under the same assumptions.

- Stress cases beating both controls: **{stress_wins}/{len(stresses)}**.
- Financing cost in the base frozen run: **{money(primary_row['Financing Cost'])}**.
- Worst stress ending value: **{money(stresses['Final Value'].min())}**.
- Best stress ending value: **{money(stresses['Final Value'].max())}**.
- Margin calls across every stress run: **{int(stresses['Margin Calls'].sum())}**.

## Statistical checks and multiple testing

- Annualized mean active log return: **{pct(stats['Annualized Mean Excess'])}**.
- Moving-block bootstrap 95% interval: **{pct(stats['Bootstrap CI Low'])} to {pct(stats['Bootstrap CI High'])}**.
- Probability of a non-positive bootstrapped edge: **{pct(stats['Bootstrap P <= 0'])}**.
- Annualized active Sharpe: **{stats['Annualized Active Sharpe']:.2f}**.
- Deflated Sharpe probability after **{known_trials}** known trials: **{pct(stats['Deflated Sharpe Probability'])}**.
- PBO across the three distinct conditional families: **{pct(pbo_result['PBO'])}** from **{pbo_result['Splits']}** symmetric splits.

Known prior rows included in the multiple-testing penalty:

{chr(10).join(trial_lines)}

## Validation gates

{chr(10).join(gate_lines)}

## Limitations

1. The entire SPY history has now been inspected repeatedly. Walk-forward tests reduce leakage, but only a frozen forward log or a clearly labelled earlier index proxy can add genuinely untouched evidence.
2. Adjusted Yahoo OHLC bars include distributions in prices and can distort historical intraday levels. Raw OHLC plus separately credited dividends would be better for final execution work.
3. Financing is charged daily and stressed, but historical broker rates, changing house requirements, tax deductibility, and account-specific borrowing terms are not reconstructed.
4. The model checks open and intraday-low maintenance margin and forces liquidation, but daily bars cannot reproduce every intraday margin event or spread.
5. Taxes are excluded. Rebalancing a taxable account can realize gains, and margin-interest deductibility depends on the investor's circumstances.
6. Constant leverage and conditional leverage both add risk. Beating B&H through a higher average exposure is not alpha.
7. A single U.S. equity ETF supplies few independent bear and volatility regimes. Statistical precision is inherently limited.

## Decision

Do not live-trade conditional leverage as an established edge unless the verdict is **SUPPORTED**. A **PROMISING BUT UNCONFIRMED** result is suitable only for frozen paper trading. If the rule fails to beat constant matched exposure, retain B&H as the default because leverage—not timing—explains the extra wealth.

## Reproduction

- `spy_conditional_leverage_results.csv`
- `spy_conditional_leverage_early.csv`
- `spy_conditional_leverage_folds.csv`
- `spy_conditional_leverage_selected.csv`
- `spy_conditional_leverage_plateau.csv`
- `spy_conditional_leverage_crisis.csv`
- `spy_conditional_leverage_stress.csv`

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_conditional_leverage_validation.py
```
"""
    path = ROOT / "studies" / "spy_conditional_leverage_validation.md"
    path.write_text(report, encoding="utf-8")
    return path


def run() -> None:
    prices = load_prices()
    targets, labels, plateau_keys = target_library(prices)
    headline_keys = [
        "buy_hold", "constant_115", "constant_125", "constant_135",
        "trend_115", "trend_125", "trend_135",
        "vol_12", "vol_15", "vol_18", "hybrid_center",
    ]
    benchmark = run_target(prices, targets["buy_hold"], labels["buy_hold"])
    results = {"buy_hold": benchmark}
    main_rows = [row("buy_hold", labels["buy_hold"], benchmark, benchmark, "1994-2026")]
    for key in headline_keys[1:]:
        result = run_target(prices, targets[key], labels[key])
        results[key] = result
        main_rows.append(row(key, labels[key], result, benchmark, "1994-2026"))
    main = pd.DataFrame(main_rows)

    primary = results["hybrid_center"]
    matched_exposure = primary.summary["Avg Exposure"]
    matched_target = pd.Series(matched_exposure, index=prices.index)
    constant_match = run_target(prices, matched_target,
                                f"Constant {matched_exposure:.2f}x exposure")

    early_benchmark = run_target(prices, targets["buy_hold"], labels["buy_hold"],
                                 START, "2004-12-31")
    early_keys = ["buy_hold", "trend_125", "vol_15", "hybrid_center"]
    early_rows = []
    for key in early_keys:
        result = early_benchmark if key == "buy_hold" else run_target(
            prices, targets[key], labels[key], START, "2004-12-31")
        early_rows.append(row(key, labels[key], result, early_benchmark, "1994-2004"))
    early = pd.DataFrame(early_rows)

    walk_keys = ["trend_125", "vol_15", "hybrid_center"]
    folds, selected = walk_forward(prices, targets, labels, walk_keys)

    plateau_rows = []
    plateau_results = {}
    for key in plateau_keys:
        result = primary if key == "hybrid_center" else run_target(prices, targets[key], labels[key])
        plateau_results[key] = result
        plateau_rows.append(row(key, labels[key], result, benchmark, "1994-2026"))
    plateau = pd.DataFrame(plateau_rows)

    active = active_log_returns(primary, benchmark)
    crisis = crisis_attribution(active)
    stresses = stress_tests(prices, targets["hybrid_center"], targets["buy_hold"], matched_target)
    trials, trial_detail = known_trial_count()
    known_trials = trials + len(targets)
    stats = {
        **moving_block_bootstrap(active),
        **deflated_sharpe_probability(active, known_trials),
    }
    pbo_result = pbo({key: active_log_returns(results[key], benchmark) for key in walk_keys})

    artifacts = {
        "spy_conditional_leverage_results.csv": main,
        "spy_conditional_leverage_early.csv": early,
        "spy_conditional_leverage_folds.csv": folds,
        "spy_conditional_leverage_selected.csv": selected,
        "spy_conditional_leverage_plateau.csv": plateau,
        "spy_conditional_leverage_crisis.csv": crisis,
        "spy_conditional_leverage_stress.csv": stresses,
    }
    for filename, frame in artifacts.items():
        frame.to_csv(ROOT / "studies" / filename, index=False)

    save_charts(results, benchmark, constant_match, folds, plateau)
    report = write_report(
        prices, main, early, folds, selected, plateau, crisis, stresses,
        stats, pbo_result, primary, benchmark, constant_match,
        trial_detail, known_trials,
    )
    print(main.sort_values("Final Value", ascending=False).to_string(index=False))
    print(f"Matched constant exposure: {matched_exposure:.4f}")
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

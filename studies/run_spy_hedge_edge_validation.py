"""Validate the frozen monthly SMA200 SPY de-risking hypothesis.

This is a confirmation-oriented study.  It compares four predeclared re-entry
rules, a matched explicit-short implementation, weekly buy-and-hold, an early
pre-discovery period, chronological folds, crisis attribution, neighboring
parameters, execution stresses, and multiple-testing-aware statistics.
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from statistics import NormalDist
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timing.short_weekly import build_short_indicators  # noqa: E402
from timing.temporary_hedge import HedgeConfig, run_temporary_hedge  # noqa: E402


DATA_PATH = ROOT / "data" / "spy_daily_yfinance_1993.parquet"
ORIGINAL_DATA_PATH = ROOT / "data" / "spy_daily_yfinance.parquet"
START = "1994-01-03"
END = "2026-07-30"
DISCOVERY_START = "2005-01-03"
WEEKLY_AMOUNT = 25.0
BASE_COST = 0.0005
BASE_CASH_YIELD = 0.03
BASE_BORROW = 0.01
SEED = 20260802

EXIT_RULES = {
    "profit10_reversal": "10% decline OR SMA20 recovery",
    "profit10_only": "10% decline only",
    "profit10_and_sma20": "10% decline AND SMA20 recovery",
    "staged_profit10_sma20": "Half at 10%, rest above SMA20",
}


def load_or_fetch_prices() -> tuple[pd.DataFrame, str]:
    """Extend the cached adjusted SPY bars back to inception when possible."""
    original = pd.read_parquet(ORIGINAL_DATA_PATH).sort_index()
    original.index = pd.DatetimeIndex(original.index).tz_localize(None)
    source = "cached adjusted Yahoo Finance bars"
    if DATA_PATH.exists():
        extended = pd.read_parquet(DATA_PATH).sort_index()
        extended.index = pd.DatetimeIndex(extended.index).tz_localize(None)
        if extended.index.min() <= pd.Timestamp("1993-02-01"):
            return extended.loc[:END], "extended adjusted Yahoo Finance bars"

    try:
        import yfinance as yf

        downloaded = yf.download(
            "SPY", start="1993-01-01", end="2026-08-01", interval="1d",
            auto_adjust=True, progress=False,
        )
        if isinstance(downloaded.columns, pd.MultiIndex):
            downloaded.columns = downloaded.columns.get_level_values(0)
        downloaded.columns = [str(c).lower() for c in downloaded.columns]
        downloaded.index = pd.DatetimeIndex(downloaded.index).tz_localize(None)
        downloaded = downloaded[["open", "high", "low", "close", "volume"]]
        # Preserve the suite's already-frozen recent cache if the live download
        # ends earlier, while taking the pre-2004 history from the new request.
        early = downloaded.loc[downloaded.index < original.index.min()]
        combined = pd.concat([early, original]).sort_index()
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.to_parquet(DATA_PATH)
        return combined.loc[:END], "extended adjusted Yahoo Finance bars"
    except Exception as exc:  # pragma: no cover - network fallback
        return original.loc[:END], f"cached bars only; extension failed: {exc}"


def prepared_indicators(prices: pd.DataFrame, trigger_sma: int = 200,
                        recovery_sma: int = 20) -> pd.DataFrame:
    out = build_short_indicators(prices)
    close = prices["close"].astype(float)
    out["sma200"] = close.rolling(trigger_sma, min_periods=trigger_sma).mean()
    out["sma200_rising"] = out["sma200"] > out["sma200"].shift(20)
    out["sma20"] = close.rolling(recovery_sma, min_periods=recovery_sma).mean()
    return out


def run_cfg(prices: pd.DataFrame, *, vehicle: str = "derisk_cash",
            exit_plan: str = "profit10_reversal", start: str = START,
            end: str = END, fraction: float = 0.50, frequency: str = "monthly",
            trigger_sma: int = 200, recovery_sma: int = 20,
            profit_target: float = 0.10, cost: float = BASE_COST,
            cash_yield: float = BASE_CASH_YIELD,
            borrow: float = BASE_BORROW):
    prepared = prepared_indicators(prices, trigger_sma, recovery_sma)
    return run_temporary_hedge(HedgeConfig(
        strategy="sma200", vehicle=vehicle, hedge_fraction=fraction,
        decision_frequency=frequency, exit_plan=exit_plan,
        weekly_amount=WEEKLY_AMOUNT, start=start, end=end,
        cash_yield_annual=cash_yield, short_borrow_annual=borrow,
        cost_pct=cost, maintenance_margin=0.30,
        profit_target_pct=profit_target,
        rebalance_on_contribution=False,
    ), prices, prepared)


def result_row(name: str, result, period: str, vehicle: str, benchmark=None) -> dict:
    s = result.summary
    row = {
        "Strategy": name, "Period": period, "Vehicle": vehicle,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"], "Profit": s["Profit"],
        "IRR": s["Money-Weighted Return (IRR)"],
        "TWR CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Cash-Flow Adjusted Max Drawdown"],
        "Average Net Exposure": s["Average Net Exposure"],
        "Hedge Entries": s["Hedge Entries"], "Turnover": s["Turnover"],
        "Trading Cost": s["Trading Cost"], "Borrow Cost": s["Short Borrow Cost"],
    }
    row["Delta vs B&H"] = 0.0 if benchmark is None else s["Final Value"] - benchmark.summary["Final Value"]
    return row


def active_returns(result, benchmark) -> pd.Series:
    # Log-return differences add exactly through time and therefore reconcile
    # to the ratio of the two unitized ending NAVs.
    left = np.log(result.daily["nav"]).diff()
    right = np.log(benchmark.daily["nav"]).diff()
    return (left - right).dropna()


def moving_block_bootstrap(active: pd.Series, block: int = 20,
                           samples: int = 5000) -> dict:
    values = active.to_numpy(dtype=float)
    rng = np.random.default_rng(SEED)
    n = len(values)
    means = np.empty(samples)
    for j in range(samples):
        starts = rng.integers(0, max(1, n - block + 1), size=int(np.ceil(n / block)))
        draw = np.concatenate([values[s:s + block] for s in starts])[:n]
        means[j] = draw.mean() * 252
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {
        "Annualized Mean Excess": float(values.mean() * 252),
        "Bootstrap CI Low": float(lo), "Bootstrap CI High": float(hi),
        "Bootstrap P <= 0": float(np.mean(means <= 0)),
    }


def known_trial_count() -> tuple[int, list[tuple[str, int]]]:
    files = [
        "spy_directional_tp_all_configs.csv", "spy_temporary_hedge_overlays.csv",
        "spy_temporary_hedge_derisk.csv", "spy_short_decline_results.csv",
        "spy_adaptive_weekly_results.csv", "spy_timing_weekly_combined_results.csv",
        "spy_realistic_leverage_results.csv",
    ]
    detail = []
    for filename in files:
        path = ROOT / "studies" / filename
        if path.exists():
            detail.append((filename, len(pd.read_csv(path))))
    return sum(count for _, count in detail), detail


def deflated_sharpe_probability(active: pd.Series, trials: int) -> dict:
    """Bailey/Lopez de Prado DSR using a conservative known-trial count."""
    x = active.to_numpy(dtype=float)
    n = len(x)
    mean = x.mean()
    std = x.std(ddof=1)
    sr = mean / std if std > 0 else 0.0  # daily Sharpe
    centered = x - mean
    skew = float(np.mean(centered ** 3) / (np.mean(centered ** 2) ** 1.5)) if std > 0 else 0.0
    kurt = float(np.mean(centered ** 4) / (np.mean(centered ** 2) ** 2)) if std > 0 else 3.0
    nd = NormalDist()
    euler_gamma = 0.5772156649
    trials = max(2, int(trials))
    expected_max_z = (
        (1 - euler_gamma) * nd.inv_cdf(1 - 1 / trials)
        + euler_gamma * nd.inv_cdf(1 - 1 / (trials * np.e))
    )
    sr0 = expected_max_z / np.sqrt(max(1, n - 1))
    denom = np.sqrt(max(1e-12, 1 - skew * sr + ((kurt - 1) / 4) * sr * sr))
    z = (sr - sr0) * np.sqrt(max(1, n - 1)) / denom
    return {
        "Annualized Active Sharpe": float(sr * np.sqrt(252)),
        "Deflated Sharpe Probability": float(nd.cdf(z)),
        "Known Trials": trials, "Skew": skew, "Kurtosis": kurt,
    }


def crisis_attribution(active: pd.Series) -> pd.DataFrame:
    windows = {
        "2008 financial crisis": ("2007-10-01", "2009-06-30"),
        "2020 COVID crash": ("2020-02-01", "2020-06-30"),
    }
    total = active.sum()
    rows = []
    covered = pd.Series(False, index=active.index)
    for name, (start, end) in windows.items():
        mask = (active.index >= start) & (active.index <= end)
        covered |= mask
        contribution = float(active[mask].sum())
        rows.append({"Segment": name, "Active Log Return": contribution,
                     "Share of Total Active Return": contribution / total if total else np.nan})
    outside = float(active[~covered].sum())
    rows.append({"Segment": "All dates outside both windows", "Active Log Return": outside,
                 "Share of Total Active Return": outside / total if total else np.nan})
    rows.append({"Segment": "Total", "Active Log Return": float(total),
                 "Share of Total Active Return": 1.0})
    return pd.DataFrame(rows)


def pbo_from_blocks(candidates: dict[str, object], benchmark) -> dict:
    active = {name: active_returns(result, benchmark) for name, result in candidates.items()}
    common = pd.concat(active, axis=1).dropna()
    years = sorted(common.index.year.unique())
    blocks = [years[i:i + 3] for i in range(0, len(years), 3) if len(years[i:i + 3]) >= 2]
    matrix = np.array([
        [common.loc[common.index.year.isin(block), name].mean() for name in common.columns]
        for block in blocks
    ])
    failures = logits = 0
    cases = 0
    half = len(blocks) // 2
    for train_idx in combinations(range(len(blocks)), half):
        train_idx = np.array(train_idx)
        test_idx = np.array([i for i in range(len(blocks)) if i not in set(train_idx)])
        winner = int(np.argmax(matrix[train_idx].mean(axis=0)))
        test_scores = matrix[test_idx].mean(axis=0)
        rank = int(np.argsort(np.argsort(test_scores))[winner]) + 1  # 1=worst
        percentile = rank / (len(test_scores) + 1)
        failures += int(percentile <= 0.5)
        logits += float(np.log(percentile / (1 - percentile)))
        cases += 1
    return {"PBO": failures / cases, "CSCV Splits": cases,
            "Mean OOS Rank Logit": logits / cases}


def walk_forward(prices: pd.DataFrame, exit_rules: dict[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    folds = []
    selected = []
    for test_start in range(2004, 2026, 3):
        test_end = min(test_start + 2, 2026)
        train_end = test_start - 1
        train_start = 1994
        test_start_s, test_end_s = f"{test_start}-01-03", f"{test_end}-12-31"
        if pd.Timestamp(test_start_s) >= prices.index.max():
            continue
        test_end_s = str(min(pd.Timestamp(test_end_s), prices.index.max()).date())
        benchmark = run_cfg(prices, fraction=0.0, exit_plan="signal_clear",
                            start=test_start_s, end=test_end_s)
        train_values = {}
        test_values = {}
        for key, label in exit_rules.items():
            train = run_cfg(prices, exit_plan=key, start=f"{train_start}-01-03",
                            end=f"{train_end}-12-31")
            test = run_cfg(prices, exit_plan=key, start=test_start_s, end=test_end_s)
            train_values[key] = train.summary["Final Value"]
            test_values[key] = test.summary["Final Value"]
            folds.append({"Test Period": f"{test_start}-{test_end}", "Rule": label,
                          "Final Value": test.summary["Final Value"],
                          "B&H Final": benchmark.summary["Final Value"],
                          "Delta vs B&H": test.summary["Final Value"] - benchmark.summary["Final Value"]})
        choice = max(train_values, key=train_values.get)
        selected.append({"Test Period": f"{test_start}-{test_end}",
                         "Selected From Prior Data": exit_rules[choice],
                         "Delta vs B&H": test_values[choice] - benchmark.summary["Final Value"]})
    return pd.DataFrame(folds), pd.DataFrame(selected)


def one_at_a_time_plateau(prices: pd.DataFrame, benchmark) -> pd.DataFrame:
    specs = [
        ("Frozen center", {}),
        ("Hedge 25%", {"fraction": 0.25}), ("Hedge 37.5%", {"fraction": 0.375}),
        ("Trigger SMA180", {"trigger_sma": 180}), ("Trigger SMA220", {"trigger_sma": 220}),
        ("Recovery SMA15", {"recovery_sma": 15}), ("Recovery SMA30", {"recovery_sma": 30}),
        ("Profit target 8%", {"profit_target": 0.08}),
        ("Profit target 12%", {"profit_target": 0.12}),
        ("Weekly review", {"frequency": "weekly"}),
        ("Quarterly review", {"frequency": "quarterly"}),
    ]
    rows = []
    for label, kwargs in specs:
        result = run_cfg(prices, **kwargs)
        rows.append({"Neighbor": label, "Final Value": result.summary["Final Value"],
                     "Delta vs B&H": result.summary["Final Value"] - benchmark.summary["Final Value"],
                     "Max Drawdown": result.summary["Cash-Flow Adjusted Max Drawdown"]})
    return pd.DataFrame(rows)


def stress_tests(prices: pd.DataFrame, benchmark) -> pd.DataFrame:
    rows = []
    for vehicle in ["derisk_cash", "short_overlay"]:
        for cost in [0.0005, 0.0010, 0.0020]:
            for cash_yield in [0.0, 0.03]:
                borrows = [0.01] if vehicle == "derisk_cash" else [0.01, 0.03, 0.06]
                for borrow in borrows:
                    result = run_cfg(prices, vehicle=vehicle, cost=cost,
                                     cash_yield=cash_yield, borrow=borrow)
                    rows.append({"Vehicle": vehicle, "Cost Per Side": cost,
                                 "Cash Yield": cash_yield, "Borrow Rate": borrow,
                                 "Final Value": result.summary["Final Value"],
                                 "Delta vs B&H": result.summary["Final Value"] - benchmark.summary["Final Value"]})
    return pd.DataFrame(rows)


def money(v):
    return f"${v:,.0f}"


def pct(v):
    return f"{v * 100:.2f}%"


def markdown_table(frame: pd.DataFrame, columns: list[tuple[str, str]]) -> str:
    lines = ["| " + " | ".join(label for _, label in columns) + " |",
             "|" + "|".join("---" for _ in columns) + "|"]
    for _, row in frame.iterrows():
        values = []
        for key, _ in columns:
            value = row[key]
            if key in {"Final Value", "Profit", "Delta vs B&H", "B&H Final", "Trading Cost", "Borrow Cost"}:
                values.append(money(value))
            elif key in {"IRR", "TWR CAGR", "Max Drawdown", "Average Net Exposure",
                         "Active Log Return", "Share of Total Active Return",
                         "Bootstrap CI Low", "Bootstrap CI High", "Annualized Mean Excess"}:
                values.append(pct(value))
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def save_charts(results: dict[str, object], benchmark, folds: pd.DataFrame,
                plateau: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    selected = {"Weekly B&H": benchmark, **results}
    for name, result in selected.items():
        ax.plot(result.daily.index, result.daily["drawdown"] * 100,
                label=name, linewidth=1.8 if name == "Weekly B&H" else 1.15)
    ax.set_title("Cash-flow-adjusted drawdown — frozen re-entry rules")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_hedge_validation_drawdown.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6))
    pivot = folds.pivot(index="Test Period", columns="Rule", values="Delta vs B&H")
    pivot.plot(kind="bar", ax=ax, width=0.82)
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Chronological test-fold ending-value difference vs weekly B&H")
    ax.set_ylabel("Difference ($)")
    ax.tick_params(axis="x", rotation=35)
    ax.grid(axis="y", alpha=0.2)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_hedge_validation_walkforward.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 6))
    plot = plateau.sort_values("Delta vs B&H")
    colors = np.where(plot["Delta vs B&H"] >= 0, "#2ca02c", "#d62728")
    ax.barh(plot["Neighbor"], plot["Delta vs B&H"], color=colors, alpha=0.82)
    ax.axvline(0, color="black", linewidth=1)
    ax.set_title("One-at-a-time parameter neighborhood")
    ax.set_xlabel("Ending-value difference vs weekly B&H ($)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_hedge_validation_plateau.png", dpi=170)
    plt.close(fig)


def write_report(source: str, prices: pd.DataFrame, main: pd.DataFrame,
                 early: pd.DataFrame, folds: pd.DataFrame, selected: pd.DataFrame,
                 crisis: pd.DataFrame, plateau: pd.DataFrame, stresses: pd.DataFrame,
                 stats: dict, pbo: dict, trial_detail: list[tuple[str, int]]) -> Path:
    primary = main[(main["Strategy"] == EXIT_RULES["profit10_reversal"]) &
                   (main["Vehicle"] == "derisk_cash")].iloc[0]
    early_primary = early[(early["Strategy"] == EXIT_RULES["profit10_reversal"]) &
                          (early["Vehicle"] == "derisk_cash")].iloc[0]
    fixed = folds[folds["Rule"] == EXIT_RULES["profit10_reversal"]]
    fixed_wins = int((fixed["Delta vs B&H"] > 0).sum())
    neighbor_wins = int((plateau["Delta vs B&H"] > 0).sum())
    selected_wins = int((selected["Delta vs B&H"] > 0).sum())
    short_primary = main[(main["Strategy"] == EXIT_RULES["profit10_reversal"]) &
                         (main["Vehicle"] == "short_overlay")].iloc[0]

    gates = {
        "Positive pre-2005 evidence": early_primary["Delta vs B&H"] > 0,
        "At least 70% fixed chronological folds won": fixed_wins / len(fixed) >= 0.70,
        "At least 70% anchored selections won": selected_wins / len(selected) >= 0.70,
        "Bootstrap 95% interval above zero": stats["Bootstrap CI Low"] > 0,
        "Deflated Sharpe probability at least 95%": stats["Deflated Sharpe Probability"] >= 0.95,
        "PBO below 20%": pbo["PBO"] < 0.20,
        "At least 70% of neighbors beat B&H": neighbor_wins / len(plateau) >= 0.70,
        "No one crisis contributes over half of active return": bool(
            crisis.iloc[:2]["Share of Total Active Return"].abs().max() <= 0.50),
        "At least 3-point drawdown improvement": primary["Max Drawdown"] - main.loc[main["Strategy"] == "Weekly buy & hold", "Max Drawdown"].iloc[0] >= 0.03,
        "Explicit short beats matched partial sale": short_primary["Final Value"] > primary["Final Value"],
    }
    passed = sum(gates.values())
    status = "SUPPORTED" if passed >= 8 and all(list(gates.values())[:6]) else (
        "PROMISING BUT UNCONFIRMED" if passed >= 5 else "REJECTED AS A PROVEN EDGE"
    )

    main_table = markdown_table(main, [
        ("Strategy", "Rule"), ("Vehicle", "Implementation"),
        ("Total Contributed", "Contributed"), ("Final Value", "Final value"),
        ("Delta vs B&H", "vs B&H"), ("IRR", "IRR"),
        ("Max Drawdown", "Max DD"), ("Hedge Entries", "Entries"),
    ])
    early_table = markdown_table(early, [
        ("Strategy", "Rule"), ("Vehicle", "Implementation"),
        ("Final Value", "Final value"), ("Delta vs B&H", "vs B&H"),
        ("Max Drawdown", "Max DD"),
    ])
    fold_summary = folds.groupby("Rule", as_index=False).agg(
        **{"Folds Won": ("Delta vs B&H", lambda x: int((x > 0).sum())),
           "Folds": ("Delta vs B&H", "count"),
           "Median Delta": ("Delta vs B&H", "median"),
           "Total Delta": ("Delta vs B&H", "sum")})
    fold_summary["Win Rate"] = fold_summary["Folds Won"] / fold_summary["Folds"]
    fold_lines = ["| Rule | Folds won | Win rate | Median fold difference | Sum of fold differences |",
                  "|---|---:|---:|---:|---:|"]
    for _, row in fold_summary.iterrows():
        fold_lines.append(f"| {row['Rule']} | {int(row['Folds Won'])}/{int(row['Folds'])} | "
                          f"{pct(row['Win Rate'])} | {money(row['Median Delta'])} | {money(row['Total Delta'])} |")
    crisis_table = markdown_table(crisis, [
        ("Segment", "Segment"), ("Active Log Return", "Active log return"),
        ("Share of Total Active Return", "Share of total"),
    ])
    gate_lines = [f"- {'PASS' if ok else 'FAIL'} — {name}" for name, ok in gates.items()]
    trial_lines = [f"- `{name}`: {count} rows" for name, count in trial_detail]
    worst_stress = stresses.loc[stresses["Final Value"].idxmin()]
    best_stress = stresses.loc[stresses["Final Value"].idxmax()]

    report = f"""# SPY Hedge Edge Validation

Run through: **{END}**  
Available adjusted-bar history: **{prices.index.min():%Y-%m-%d} through {prices.index.max():%Y-%m-%d}**  
Primary confirmation period: **{START} through {END}**  
Owner contribution: **$25 on the first trading day of every ISO week**  
Data source: **{source}**

## Verdict

**{status} — {passed}/{len(gates)} predeclared validation gates passed.**

The frozen partial-sale rule finished **{money(primary['Delta vs B&H'])}** above weekly buy-and-hold over 1994–2026, but a full-sample lead is not sufficient evidence. Its earlier 1994–2004 result was **{money(early_primary['Delta vs B&H'])}** versus B&H, it won **{fixed_wins}/{len(fixed)}** fixed chronological folds, and the bootstrap 95% interval for annualized active return was **{pct(stats['Bootstrap CI Low'])} to {pct(stats['Bootstrap CI High'])}**.

The matched explicit-short version finished **{money(short_primary['Final Value'] - primary['Final Value'])}** relative to partial sale. It should not be preferred unless it wins after borrow, execution, dividend and margin frictions.

Every row received the same amount on the same weekly schedule, so the dollar lead is not caused by extra contributions. Final dollars and unitized active return can still tell different stories because returns earned early and late interact differently with a growing contribution balance. The report therefore requires both wealth and return-based tests rather than treating the largest ending account as proof by itself.

## Frozen rules

All strategies receive identical contributions. The portfolio normally holds 100% SPY. On the first trading session of each month, the prior completed close is inspected. If it is below SMA200 and the trigger is armed, exposure is reduced to 50% at that session's open. After an exit, the trigger must clear before another activation.

The four re-entry rules were declared before this validation run:

1. Return to 100% after a 10% decline from activation **or** a prior close above SMA20.
2. Return after the 10% decline only.
3. Require the 10% decline and then an SMA20 recovery.
4. Restore half at the 10% decline and the remainder above SMA20.

## Full-history comparison

{main_table}

![Drawdown comparison](spy_hedge_validation_drawdown.png)

## Earlier evidence: 1994–2004

This period predates the original 2005–2026 research sample. It is useful evidence, but inspecting it in this report consumes it as a future holdout.

{early_table}

## Chronological walk-forward evidence

Each fixed rule was tested in non-overlapping, forward-moving three-year segments. Separately, an anchored procedure selected one of the four rules using only earlier years and then applied that choice to the next segment.

{chr(10).join(fold_lines)}

The anchored selector won **{selected_wins}/{len(selected)}** subsequent test folds. Selecting among these four rules did not create a reliable edge unless that rate and the fixed-rule results both remained strong.

![Walk-forward fold results](spy_hedge_validation_walkforward.png)

## Is the result only 2008 or 2020?

This attribution decomposes the strategy's daily active return versus B&H. It does not pretend that deleting dates creates a directly executable alternate history.

{crisis_table}

## Parameter plateau

One input at a time was moved around the frozen center: 25%/37.5%/50% de-risking, SMA180/200/220, SMA15/20/30 recovery, 8%/10%/12% decline targets, and weekly/monthly/quarterly reviews. **{neighbor_wins}/{len(plateau)}** tested points beat B&H.

![Parameter neighborhood](spy_hedge_validation_plateau.png)

## Statistical checks and multiple testing

- Annualized mean active return: **{pct(stats['Annualized Mean Excess'])}**.
- Moving-block bootstrap 95% interval: **{pct(stats['Bootstrap CI Low'])} to {pct(stats['Bootstrap CI High'])}**.
- One-sided bootstrap probability of a non-positive edge: **{pct(stats['Bootstrap P <= 0'])}**.
- Annualized active Sharpe: **{stats['Annualized Active Sharpe']:.2f}**.
- Deflated Sharpe probability after **{stats['Known Trials']}** known prior rows: **{pct(stats['Deflated Sharpe Probability'])}**.
- Combinatorially symmetric cross-validation PBO across the four rules: **{pct(pbo['PBO'])}** from **{pbo['CSCV Splits']}** splits.

PBO only asks whether selecting among these four re-entry rules was unstable. A low PBO does **not** show that the best member beats B&H; here it mainly says the OR rule consistently ranked above three structurally weak alternatives.

The trial count is deliberately conservative and includes overlapping report rows rather than pretending only the final four ideas were tried:

{chr(10).join(trial_lines)}

## Execution and financing stress

The base case charges 5 basis points per trade side, credits 3% on positive cash and charges the explicit short 1% annual borrow. Stress cases use 5–20 basis points, 0%/3% cash yield, and 1%/3%/6% short borrow.

- Best stress-case ending value: **{money(best_stress['Final Value'])}** ({best_stress['Vehicle']}).
- Worst stress-case ending value: **{money(worst_stress['Final Value'])}** ({worst_stress['Vehicle']}).
- Stress rows beating the fixed weekly B&H base: **{int((stresses['Delta vs B&H'] > 0).sum())}/{len(stresses)}**.

## Validation gates

{chr(10).join(gate_lines)}

These thresholds are research gates, not guarantees. A failed gate is a reason not to describe the result as established alpha.

## Important limitations that remain

1. Yahoo's adjusted OHLC bars are convenient for total-return testing but can distort historical intraday target touches. Raw prices plus separately credited dividends are preferable for final execution validation.
2. The 10% target assumes a conservative gap-through fill at the open but otherwise fills exactly at the adjusted daily low threshold. Intraday quotes, spreads and order queue effects are unavailable.
3. The cash yield is constant rather than historical T-bill or broker sweep rates.
4. Explicit-short borrow is stressed but historical locate availability, recalls, changing borrow fees, payments in lieu of dividends, and broker house margin changes are not fully reconstructed.
5. Taxes are excluded. Partial sales realize gains; explicit shorts add their own tax and distribution-payment complications. Taxable and retirement accounts can rank implementations differently.
6. The early history contains the same underlying U.S. equity market and is only about eleven years. It is new to this research process, not an independent universe.
7. The 2005–2026 history and the newly inspected 1994–2004 history are now consumed. Future confirmation must come from a frozen forward paper/live log or a clearly labelled pre-SPY proxy.
8. Statistical observations within a market path are dependent. Bootstrap, DSR and PBO reduce false confidence but cannot manufacture independent crash histories.

## Decision

Use weekly buy-and-hold as the live default unless the verdict above is **SUPPORTED** and a frozen forward test adds evidence. If partial sale passes while the explicit short does not beat it, the result is a **de-risking/timing hypothesis**, not a short-selling edge.

## Reproduction files

- `spy_hedge_validation_main.csv`
- `spy_hedge_validation_early.csv`
- `spy_hedge_validation_folds.csv`
- `spy_hedge_validation_anchored_selection.csv`
- `spy_hedge_validation_crisis.csv`
- `spy_hedge_validation_plateau.csv`
- `spy_hedge_validation_stress.csv`

```powershell
.\\.venv\\Scripts\\python.exe studies\\run_spy_hedge_edge_validation.py
```
"""
    path = ROOT / "studies" / "spy_hedge_edge_validation.md"
    path.write_text(report, encoding="utf-8")
    return path


def run() -> None:
    prices, source = load_or_fetch_prices()
    if prices.index.min() > pd.Timestamp("1993-02-01"):
        raise RuntimeError("The pre-2005 validation requires SPY history back to inception.")

    benchmark = run_cfg(prices, fraction=0.0, exit_plan="signal_clear")
    main_results = {}
    main_rows = [result_row("Weekly buy & hold", benchmark, "1994-2026", "benchmark")]
    for vehicle in ["derisk_cash", "short_overlay"]:
        for key, label in EXIT_RULES.items():
            result = run_cfg(prices, vehicle=vehicle, exit_plan=key)
            main_results[f"{label} — {vehicle}"] = result
            main_rows.append(result_row(label, result, "1994-2026", vehicle, benchmark))
    main = pd.DataFrame(main_rows)

    early_benchmark = run_cfg(prices, fraction=0.0, exit_plan="signal_clear",
                              start=START, end="2004-12-31")
    early_rows = [result_row("Weekly buy & hold", early_benchmark, "1994-2004", "benchmark")]
    for vehicle in ["derisk_cash", "short_overlay"]:
        for key, label in EXIT_RULES.items():
            result = run_cfg(prices, vehicle=vehicle, exit_plan=key,
                             start=START, end="2004-12-31")
            early_rows.append(result_row(label, result, "1994-2004", vehicle, early_benchmark))
    early = pd.DataFrame(early_rows)

    folds, selected = walk_forward(prices, EXIT_RULES)
    primary = main_results[f"{EXIT_RULES['profit10_reversal']} — derisk_cash"]
    active = active_returns(primary, benchmark)
    crisis = crisis_attribution(active)
    plateau = one_at_a_time_plateau(prices, benchmark)
    stresses = stress_tests(prices, benchmark)
    trials, trial_detail = known_trial_count()
    stats = {**moving_block_bootstrap(active), **deflated_sharpe_probability(active, trials)}
    pbo_candidates = {label: run_cfg(prices, exit_plan=key) for key, label in EXIT_RULES.items()}
    pbo = pbo_from_blocks(pbo_candidates, benchmark)

    artifacts = {
        "spy_hedge_validation_main.csv": main,
        "spy_hedge_validation_early.csv": early,
        "spy_hedge_validation_folds.csv": folds,
        "spy_hedge_validation_anchored_selection.csv": selected,
        "spy_hedge_validation_crisis.csv": crisis,
        "spy_hedge_validation_plateau.csv": plateau,
        "spy_hedge_validation_stress.csv": stresses,
    }
    for filename, frame in artifacts.items():
        frame.to_csv(ROOT / "studies" / filename, index=False)
    save_charts(
        {label: main_results[f"{label} — derisk_cash"] for label in EXIT_RULES.values()},
        benchmark, folds, plateau,
    )
    report = write_report(source, prices, main, early, folds, selected, crisis,
                          plateau, stresses, stats, pbo, trial_detail)
    print(main.sort_values(["Vehicle", "Final Value"], ascending=[True, False]).to_string(index=False))
    print(f"Report: {report}")


if __name__ == "__main__":
    run()

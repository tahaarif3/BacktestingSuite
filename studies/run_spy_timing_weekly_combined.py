"""Run the 2005-2026 SPY weekly-contribution + timing-overlay study.

The matrix combines the four highest-ending timing configurations from
``spy_timing_study.md`` with the strongest tradeable weekly contribution rules
from ``spy_weekly_study_2026.md``.  Hindsight-only contribution timing is
intentionally excluded.
"""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dca.engine import DcaConfig, run_dca
from timing.engine import TimingConfig, run_timing


START = "2005-01-01"
END = "2026-07-30"


OVERLAYS = [
    {
        "name": "Buy & Hold",
        "params": {"strategy": "buy_hold", "exposure_in": 1.0},
    },
    {
        "name": "1.5x >200-SMA / 1x",
        "params": {
            "strategy": "ma", "ma_period": 200,
            "exposure_in": 1.5, "exposure_out": 1.0,
        },
    },
    {
        "name": "2x >200-SMA / cash",
        "params": {
            "strategy": "ma", "ma_period": 200,
            "exposure_in": 2.0, "exposure_out": 0.0,
        },
    },
    {
        "name": "Vol de-risk (50% if vol >20%)",
        "params": {
            "strategy": "vol_derisk", "vol_window": 20,
            "vol_thr": 0.20, "derisk_exposure": 0.5,
            "exposure_in": 1.0,
        },
    },
]


WEEKLY_POLICIES = [
    {
        "name": "Monday / always",
        "params": {"contribution_day": "start", "contribution_buy_rule": "always"},
    },
    {
        "name": "Monday / >75-SMA",
        "params": {
            "contribution_day": "start", "contribution_buy_rule": "above_ma",
            "contribution_ma_type": "sma", "contribution_ma_period": 75,
        },
    },
    {
        "name": "Friday / >100-SMA",
        "params": {
            "contribution_day": "end", "contribution_buy_rule": "above_ma",
            "contribution_ma_type": "sma", "contribution_ma_period": 100,
        },
    },
    {
        "name": "Monday / >100-EMA",
        "params": {
            "contribution_day": "start", "contribution_buy_rule": "above_ma",
            "contribution_ma_type": "ema", "contribution_ma_period": 100,
        },
    },
    {
        "name": "Monday / >100-SMA",
        "params": {
            "contribution_day": "start", "contribution_buy_rule": "above_ma",
            "contribution_ma_type": "sma", "contribution_ma_period": 100,
        },
    },
]


WEEKLY_CONTROLS = [
    DcaConfig(label="Weekly control: Monday / always", amount=25, cadence="weekly"),
    DcaConfig(
        label="Weekly control: Monday / >75-SMA + yield", amount=25, cadence="weekly",
        buy_rule="above_ma", ma_period=75, cash_yield_annual=0.045,
    ),
    DcaConfig(
        label="Weekly control: Friday / >100-SMA", amount=25, cadence="weekly",
        contribution_day="end", buy_rule="above_ma", ma_period=100,
    ),
    DcaConfig(
        label="Weekly control: Monday / >100-EMA + yield", amount=25, cadence="weekly",
        buy_rule="above_ma", ma_type="ema", ma_period=100, cash_yield_annual=0.045,
    ),
    DcaConfig(
        label="Weekly control: Monday / >100-SMA + yield", amount=25, cadence="weekly",
        buy_rule="above_ma", ma_period=100, cash_yield_annual=0.045,
    ),
]


def load_prices() -> pd.DataFrame:
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet")
    prices.index = pd.to_datetime(prices.index)
    return prices[["close"]].sort_index().loc[START:END]


def metric_row(label: str, family: str, summary: dict, **extra) -> dict:
    return {
        "Strategy": label,
        "Family": family,
        "Total Contributed": summary["Total Contributed"],
        "Final Value": summary["Final Value"],
        "Profit": summary["Profit"],
        "IRR": summary["Money-Weighted Return (IRR)"],
        "Max Drawdown": summary["Max Drawdown"],
        "Avg Exposure": summary["Avg Exposure"] if "Avg Exposure" in summary else summary["Avg Time in Market"],
        "Rebalances": summary.get("Rebalances", 0),
        **extra,
    }


def run() -> pd.DataFrame:
    prices = load_prices()
    rows = []
    curves = {}

    for cfg in WEEKLY_CONTROLS:
        result = run_dca(cfg, prices)
        rows.append(metric_row(result.label, "Weekly control", result.summary))
        curves[result.label] = result.value

    common = {
        "start_capital": 0.0,
        "contribution_amount": 25.0,
        "contribution_cadence": "weekly",
        "cost_pct": 0.0005,
        "cash_yield_annual": 0.045,
        "borrow_annual": 0.055,
        "rebalance_band": 0.03,
    }
    for overlay in OVERLAYS:
        for policy in WEEKLY_POLICIES:
            label = f'{overlay["name"]} + {policy["name"]}'
            cfg = TimingConfig(
                label=label,
                **common,
                **overlay["params"],
                **policy["params"],
            )
            result = run_timing(cfg, prices)
            rows.append(metric_row(
                label, "Combined", result.summary,
                Overlay=overlay["name"], WeeklyPolicy=policy["name"],
            ))
            curves[label] = result.value

    frame = pd.DataFrame(rows).sort_values(["IRR", "Final Value"], ascending=False)
    frame.to_csv(ROOT / "studies" / "spy_timing_weekly_combined_results.csv", index=False)

    combined = frame[frame["Family"] == "Combined"].head(10).sort_values("Final Value")
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.barh(combined["Strategy"], combined["Final Value"], color="#2f6fdd")
    ax.set_title("Top combined strategies by ending value")
    ax.set_xlabel("Ending account value ($)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_timing_weekly_combined_value.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 6.5))
    combined_all = frame[frame["Family"] == "Combined"]
    for overlay, group in combined_all.groupby("Overlay"):
        ax.scatter(group["Max Drawdown"] * 100, group["IRR"] * 100, s=55, label=overlay)
    ax.set_title("Return vs. drawdown: combined strategies")
    ax.set_xlabel("Maximum drawdown (%)")
    ax.set_ylabel("Money-weighted return / IRR (%)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_timing_weekly_combined_risk.png", dpi=170)
    plt.close(fig)

    print(frame.to_string(index=False))
    return frame


if __name__ == "__main__":
    run()

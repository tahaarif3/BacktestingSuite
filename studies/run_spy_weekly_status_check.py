"""Equal-capital status check for the SPY weekly/timing study."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dca.engine import _contribution_flags
from timing.engine import TimingConfig, run_timing


START = "2005-01-01"
END = "2026-07-30"
WEEKLY_AMOUNT = 25.0
TOTAL_CAPITAL = 28150.0


def unitized_drawdown(values: list[float], flows: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    nav = np.ones(len(values))
    for t in range(len(values)):
        if t == 0 or values[t - 1] <= 0:
            nav[t] = values[t] / flows[t] if flows[t] > 0 else 1.0
        else:
            nav[t] = nav[t - 1] * ((values[t] - flows[t]) / values[t - 1])
    peak = np.maximum.accumulate(nav)
    return (nav - peak) / np.where(peak == 0, 1, peak)


def run() -> pd.DataFrame:
    prices = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet")[["close"]]
    prices.index = pd.to_datetime(prices.index)
    prices = prices.sort_index().loc[START:END]
    idx = pd.DatetimeIndex(prices.index)
    weekly_flags = _contribution_flags(idx, "weekly", "start", prices["close"].to_numpy())
    friday_flags = _contribution_flags(idx, "weekly", "end", prices["close"].to_numpy())

    common = {
        "start_capital": 0.0,
        "contribution_amount": WEEKLY_AMOUNT,
        "contribution_cadence": "weekly",
        "cost_pct": 0.0005,
        "cash_yield_annual": 0.045,
        "borrow_annual": 0.055,
        "rebalance_band": 0.03,
    }
    configs = [
        TimingConfig(
            label="B&H — $28,150 lump sum",
            strategy="buy_hold", start_capital=TOTAL_CAPITAL,
            cost_pct=0.0005, cash_yield_annual=0.045,
            borrow_annual=0.055, rebalance_band=0.03,
        ),
        TimingConfig(label="B&H — $25 weekly", strategy="buy_hold", **common),
        TimingConfig(
            label="B&H + weekly >75-SMA gate", strategy="buy_hold", **common,
            contribution_buy_rule="above_ma", contribution_ma_period=75,
        ),
        TimingConfig(
            label="Vol de-risk + $25 weekly", strategy="vol_derisk", **common,
            vol_window=20, vol_thr=0.20, derisk_exposure=0.5, exposure_in=1.0,
        ),
        TimingConfig(
            label="2x/cash + Friday >100-SMA gate", strategy="ma", **common,
            ma_period=200, exposure_in=2.0, exposure_out=0.0,
            contribution_day="end", contribution_buy_rule="above_ma",
            contribution_ma_period=100,
        ),
        TimingConfig(
            label="1.5x/1x + weekly >75-SMA gate", strategy="ma", **common,
            ma_period=200, exposure_in=1.5, exposure_out=1.0,
            contribution_buy_rule="above_ma", contribution_ma_period=75,
        ),
    ]

    rows = []
    drawdowns = {}
    for cfg in configs:
        result = run_timing(cfg, prices)
        summary = result.summary
        rows.append({
            "Strategy": result.label,
            "Contribution Pattern": "Lump sum" if cfg.start_capital else "$25 weekly",
            "Total Contributed": summary["Total Contributed"],
            "Final Value": summary["Final Value"],
            "Profit": summary["Profit"],
            "IRR": summary["Money-Weighted Return (IRR)"],
            "Time-Weighted CAGR": summary["Time-Weighted CAGR"],
            "Adjusted Max Drawdown": summary["Cash-Flow Adjusted Max Drawdown"],
            "Avg Exposure": summary["Avg Exposure"],
        })
        if cfg.start_capital:
            flows = np.zeros(len(idx)); flows[0] = cfg.start_capital
        else:
            flags = friday_flags if cfg.contribution_day == "end" else weekly_flags
            flows = flags.astype(float) * cfg.contribution_amount
        drawdowns[result.label] = unitized_drawdown(result.value, flows)

    frame = pd.DataFrame(rows)
    frame.to_csv(ROOT / "studies" / "spy_weekly_status_check_results.csv", index=False)

    colors = ["#111827", "#64748b", "#16a34a", "#dc2626", "#f59e0b", "#2563eb"]
    plot_frame = frame.sort_values("Profit")
    color_map = dict(zip(frame["Strategy"], colors))
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.barh(
        plot_frame["Strategy"], plot_frame["Profit"],
        color=[color_map[x] for x in plot_frame["Strategy"]],
    )
    ax.set_title("Profit after equal $28,150 owner contributions")
    ax.set_xlabel("Final value minus total contributed ($)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_weekly_status_profit.png", dpi=170)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(11, 6.4))
    for label, color in color_map.items():
        ax.plot(idx, drawdowns[label] * 100, label=label, color=color, linewidth=1.35)
    ax.set_title("Cash-flow-adjusted drawdown")
    ax.set_ylabel("Drawdown from strategy NAV peak (%)")
    ax.set_xlabel("Date")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_weekly_status_drawdown.png", dpi=170)
    plt.close(fig)

    print(frame.to_string(index=False))
    return frame


if __name__ == "__main__":
    run()

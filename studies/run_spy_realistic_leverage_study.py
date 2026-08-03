"""Realistic SPY leverage study: margin, liquidation, and daily-reset ETFs."""

from __future__ import annotations

from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timing.engine import TimingConfig, target_exposure
from timing.realistic import (
    RealisticConfig,
    run_realistic,
    synthetic_daily_reset_ohlc,
)


START = "2005-01-01"
END = "2026-07-30"


def load_prices() -> pd.DataFrame:
    frame = pd.read_parquet(ROOT / "data" / "spy_daily_yfinance.parquet")
    frame.index = pd.to_datetime(frame.index)
    return frame[["open", "high", "low", "close"]].sort_index().loc[START:END]


def signal_library(prices: pd.DataFrame) -> dict[str, np.ndarray]:
    close = prices["close"]
    return {
        "Buy & Hold": np.ones(len(prices)),
        "MA 200d daily": target_exposure(TimingConfig(strategy="ma", ma_period=200), close),
        "MA 200d ±2% band": target_exposure(
            TimingConfig(strategy="ma", ma_period=200, band_pct=0.02), close
        ),
        "MA 10-month": target_exposure(
            TimingConfig(strategy="ma", ma_period=210, signal_freq="monthly"), close
        ),
        "Golden cross 50/200": target_exposure(
            TimingConfig(strategy="golden_cross", fast_period=50, slow_period=200), close
        ),
        "Vol target 15%": target_exposure(
            TimingConfig(strategy="vol_target", vol_window=20, vol_target=0.15, vol_cap=1.0), close
        ),
        "Vol de-risk": target_exposure(
            TimingConfig(
                strategy="vol_derisk", vol_window=20, vol_thr=0.20,
                derisk_exposure=0.5, exposure_in=1.0,
            ), close
        ),
    }


def result_row(result, family: str, overlay: str, leverage: float, vehicle: str, **extra) -> dict:
    s = result.summary
    return {
        "Strategy": result.label,
        "Family": family,
        "Overlay": overlay,
        "Leverage": leverage,
        "Vehicle": vehicle,
        "Total Contributed": s["Total Contributed"],
        "Final Value": s["Final Value"],
        "Profit": s["Profit"],
        "IRR": s["IRR"],
        "Time-Weighted CAGR": s["Time-Weighted CAGR"],
        "Max Drawdown": s["Max Drawdown"],
        "Avg Exposure": s["Avg Exposure"],
        "Margin Calls": s["Margin Calls"],
        "Minimum Margin Ratio": s["Minimum Margin Ratio"],
        **extra,
    }


def margin_config(label: str, borrow: float = 0.10, maintenance: float = 0.40, **kw):
    return RealisticConfig(
        label=label,
        start_capital=0,
        contribution_amount=25,
        contribution_cadence="weekly",
        cash_yield_annual=0.045,
        borrow_annual=borrow,
        cost_pct=0.0005,
        rebalance_band=0.03,
        initial_margin=0.50,
        maintenance_margin=maintenance,
        liquidation_lockout_days=20,
        enable_margin_calls=True,
        max_exposure=2.0,
        **kw,
    )


def run() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    prices = load_prices()
    signals = signal_library(prices)
    rows = []
    results = {}

    baseline_cfg = margin_config("Weekly Buy & Hold")
    baseline = run_realistic(baseline_cfg, prices, signals["Buy & Hold"])
    rows.append(result_row(baseline, "Baseline", "Buy & Hold", 1.0, "SPY cash"))
    results[baseline.label] = baseline

    original_specs = [
        (
            "Original 1.5x/1x + >75-SMA gate",
            np.where(signals["MA 200d daily"] > 0, 1.5, 1.0),
            dict(contribution_buy_rule="above_ma", contribution_ma_period=75),
            1.5,
        ),
        (
            "Original 2x/cash + Friday >100-SMA gate",
            signals["MA 200d daily"] * 2.0,
            dict(
                contribution_day="end", contribution_buy_rule="above_ma",
                contribution_ma_period=100,
            ),
            2.0,
        ),
    ]
    for label, exposure, extra_cfg, leverage in original_specs:
        result = run_realistic(margin_config(label, **extra_cfg), prices, exposure)
        rows.append(result_row(result, "Original", label, leverage, "SPY margin"))
        results[label] = result

    for overlay in [
        "MA 200d daily", "MA 200d ±2% band", "MA 10-month",
        "Golden cross 50/200", "Vol target 15%", "Vol de-risk",
    ]:
        for leverage in [1.00, 1.10, 1.25, 1.50, 1.75, 2.00]:
            exposure = np.minimum(2.0, signals[overlay] * leverage)
            label = f"{overlay} × {leverage:.2f} margin"
            result = run_realistic(margin_config(label), prices, exposure)
            rows.append(result_row(result, "Low-DD leverage", overlay, leverage, "SPY margin"))
            results[label] = result

    # Daily-reset ETF approximations. The account itself is unlevered; leverage,
    # financing, expense ratio, and volatility decay live inside the synthetic ETF.
    for leverage, ticker in [(2.0, "SSO-style"), (3.0, "UPRO-style")]:
        etf = synthetic_daily_reset_ohlc(
            prices, leverage=leverage, expense_ratio=0.0089, financing_annual=0.10
        )
        for overlay in [
            "Buy & Hold", "MA 200d daily", "MA 200d ±2% band",
            "MA 10-month", "Golden cross 50/200", "Vol target 15%", "Vol de-risk",
        ]:
            allocation = np.clip(signals[overlay], 0.0, 1.0)
            label = f"{overlay} + synthetic {ticker}"
            cfg = margin_config(label)
            cfg.enable_margin_calls = False
            cfg.max_exposure = 1.0
            cfg.borrow_annual = 0.0
            result = run_realistic(cfg, etf, allocation)
            rows.append(result_row(result, "Daily-reset ETF", overlay, leverage, ticker))
            results[label] = result

    frame = pd.DataFrame(rows).sort_values("Time-Weighted CAGR", ascending=False)
    frame.to_csv(ROOT / "studies" / "spy_realistic_leverage_results.csv", index=False)

    etf_sensitivity_rows = []
    for leverage, ticker in [(2.0, "SSO-style"), (3.0, "UPRO-style")]:
        for financing in [0.055, 0.08, 0.10, 0.12]:
            etf = synthetic_daily_reset_ohlc(
                prices, leverage=leverage, expense_ratio=0.0089,
                financing_annual=financing,
            )
            for overlay in ["Buy & Hold", "Vol target 15%", "MA 200d ±2% band"]:
                label = f"{overlay} + synthetic {ticker}"
                cfg = margin_config(label)
                cfg.enable_margin_calls = False
                cfg.max_exposure = 1.0
                cfg.borrow_annual = 0.0
                result = run_realistic(cfg, etf, np.clip(signals[overlay], 0.0, 1.0))
                etf_sensitivity_rows.append(result_row(
                    result, "ETF sensitivity", overlay, leverage, ticker,
                    EmbeddedFinancing=financing, ExpenseRatio=0.0089,
                ))
    pd.DataFrame(etf_sensitivity_rows).to_csv(
        ROOT / "studies" / "spy_daily_reset_etf_sensitivity.csv", index=False
    )

    # Financing and house-maintenance sensitivity for margin strategies.
    sensitivity_rows = []
    margin_specs = []
    for _, row in frame[frame["Vehicle"] == "SPY margin"].iterrows():
        overlay = row["Overlay"]
        leverage = float(row["Leverage"])
        if row["Family"] == "Original" and "1.5x/1x" in row["Strategy"]:
            exposure = np.where(signals["MA 200d daily"] > 0, 1.5, 1.0)
        elif row["Family"] == "Original":
            exposure = signals["MA 200d daily"] * 2.0
        else:
            exposure = np.minimum(2.0, signals[overlay] * leverage)
        extra_cfg = {}
        if row["Family"] == "Original" and "1.5x/1x" in row["Strategy"]:
            extra_cfg = {"contribution_buy_rule": "above_ma", "contribution_ma_period": 75}
        elif row["Family"] == "Original":
            extra_cfg = {
                "contribution_day": "end", "contribution_buy_rule": "above_ma",
                "contribution_ma_period": 100,
            }
        margin_specs.append((row["Strategy"], overlay, leverage, exposure, extra_cfg))

    for label, overlay, leverage, exposure, extra_cfg in margin_specs:
        for borrow in [0.08, 0.10, 0.12]:
            for maintenance in [0.25, 0.30, 0.40]:
                cfg = margin_config(label, borrow=borrow, maintenance=maintenance, **extra_cfg)
                result = run_realistic(cfg, prices, exposure)
                sensitivity_rows.append(result_row(
                    result, "Sensitivity", overlay, leverage, "SPY margin",
                    BorrowRate=borrow, MaintenanceMargin=maintenance,
                ))
    sensitivity = pd.DataFrame(sensitivity_rows)
    sensitivity.to_csv(ROOT / "studies" / "spy_realistic_leverage_sensitivity.csv", index=False)

    shock_rows = []
    for leverage in [1.00, 1.10, 1.25, 1.50, 1.75, 2.00]:
        for maintenance in [0.25, 0.30, 0.40]:
            numerator = 1.0 - maintenance * leverage
            trigger = max(0.0, numerator / (leverage * (1.0 - maintenance)))
            shock_rows.append({
                "Exposure": leverage,
                "Maintenance Margin": maintenance,
                "Instantaneous Decline to Margin Call": trigger,
            })
    shocks = pd.DataFrame(shock_rows)
    shocks.to_csv(ROOT / "studies" / "spy_margin_shock_thresholds.csv", index=False)

    # Permanent level-shift gap stress immediately before the 2020 selloff,
    # while the 200-day trend strategies are still in their leveraged regime. The selected
    # day's open is forced 10/20/30% below the prior close and all later OHLC
    # values are scaled by the same factor, preserving subsequent daily returns.
    gap_rows = []
    gap_date = pd.Timestamp("2020-02-20")
    gap_i = prices.index.get_loc(gap_date)
    gap_specs = [
        ("Weekly Buy & Hold", "Buy & Hold", 1.0),
        ("Original 1.5x/1x", "original_1.5", 1.5),
        ("Original 2x/cash", "original_2", 2.0),
        ("Vol target 15% × 1.25", "Vol target 15%", 1.25),
        ("MA 200d ±2% band × 1.25", "MA 200d ±2% band", 1.25),
    ]
    for gap in [0.10, 0.20, 0.30]:
        shocked = prices.copy()
        desired_open = shocked["close"].iloc[gap_i - 1] * (1.0 - gap)
        scale = desired_open / shocked["open"].iloc[gap_i]
        shocked.iloc[gap_i:, :] *= scale
        shocked_signals = signal_library(shocked)
        for label, key, leverage in gap_specs:
            if key == "original_1.5":
                exposure = np.where(shocked_signals["MA 200d daily"] > 0, 1.5, 1.0)
                extra = {"contribution_buy_rule": "above_ma", "contribution_ma_period": 75}
            elif key == "original_2":
                exposure = shocked_signals["MA 200d daily"] * 2.0
                extra = {
                    "contribution_day": "end", "contribution_buy_rule": "above_ma",
                    "contribution_ma_period": 100,
                }
            else:
                exposure = np.minimum(2.0, shocked_signals[key] * leverage)
                extra = {}
            result = run_realistic(margin_config(label, **extra), shocked, exposure)
            gap_rows.append(result_row(
                result, "Gap stress", key, leverage,
                "SPY cash" if leverage == 1 else "SPY margin",
                GapShock=gap, GapDate=gap_date.strftime("%Y-%m-%d"),
            ))
    gap_frame = pd.DataFrame(gap_rows)
    gap_frame.to_csv(ROOT / "studies" / "spy_realistic_gap_stress.csv", index=False)

    # Charts.
    margin_frame = frame[frame["Vehicle"].isin(["SPY margin", "SPY cash"])]
    fig, ax = plt.subplots(figsize=(10.5, 7))
    scatter = ax.scatter(
        margin_frame["Max Drawdown"] * 100,
        margin_frame["Time-Weighted CAGR"] * 100,
        c=margin_frame["Avg Exposure"] * 100,
        s=65 + margin_frame["Margin Calls"] * 35,
        cmap="viridis",
        alpha=0.85,
    )
    ax.set_title("Realistic margin strategies: return vs. drawdown")
    ax.set_xlabel("Cash-flow-adjusted maximum drawdown (%)")
    ax.set_ylabel("Time-weighted CAGR (%)")
    ax.grid(alpha=0.2)
    fig.colorbar(scatter, ax=ax, label="Average market exposure (%)")
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_realistic_margin_risk.png", dpi=170)
    plt.close(fig)

    top = frame.sort_values("Profit", ascending=False).head(12).sort_values("Profit")
    fig, ax = plt.subplots(figsize=(11, 7))
    ax.barh(top["Strategy"], top["Profit"], color="#2563eb")
    ax.set_title("Top realistic strategies: profit after equal $28,150 contributions")
    ax.set_xlabel("Profit ($)")
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_realistic_leverage_profit.png", dpi=170)
    plt.close(fig)

    primary_top = margin_frame.sort_values("Time-Weighted CAGR", ascending=False).head(5)["Strategy"]
    sens_plot = sensitivity[
        (sensitivity["Strategy"].isin(primary_top))
        & (sensitivity["MaintenanceMargin"] == 0.40)
    ]
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    for label, group in sens_plot.groupby("Strategy"):
        group = group.sort_values("BorrowRate")
        ax.plot(group["BorrowRate"] * 100, group["Time-Weighted CAGR"] * 100, marker="o", label=label)
    ax.axhline(
        baseline.summary["Time-Weighted CAGR"] * 100,
        color="#111827", linestyle="--", linewidth=1.5, label="Weekly Buy & Hold",
    )
    ax.set_title("Financing-cost sensitivity at 40% house maintenance")
    ax.set_xlabel("Annual margin financing rate (%)")
    ax.set_ylabel("Time-weighted CAGR (%)")
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "studies" / "spy_realistic_financing_sensitivity.png", dpi=170)
    plt.close(fig)

    print(frame.head(30).to_string(index=False))
    return frame, sensitivity, shocks


if __name__ == "__main__":
    run()

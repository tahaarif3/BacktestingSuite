"""Portfolio-level performance metrics."""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from analytics.metrics import PerformanceMetrics as PM


def _safe(x: float) -> float:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return 0.0
    return float(x)


def summarize(daily: pd.DataFrame, trades: List[Dict[str, Any]], initial_capital: float) -> Dict[str, Any]:
    equity = daily["equity"]
    total_return = equity.iloc[-1] / initial_capital - 1.0 if len(equity) else 0.0
    cagr = PM.calculate_cagr(equity)
    sharpe = PM.calculate_sharpe_ratio(equity)
    sortino = PM.calculate_sortino_ratio(equity)
    max_dd = PM.calculate_max_drawdown(equity)
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    pnls = [t["net_pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    r_multiples = [t["r_multiple"] for t in trades]
    holding = [t["holding_days"] for t in trades]

    # worst calendar month / year on the equity curve
    monthly = equity.resample("ME").last().pct_change().dropna() if len(equity) else pd.Series(dtype=float)
    yearly = equity.resample("YE").last().pct_change().dropna() if len(equity) else pd.Series(dtype=float)

    exposure = daily["gross_exposure"].mean() if len(daily) else 0.0
    avg_positions = daily["open_positions"].mean() if len(daily) else 0.0
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9) if len(equity) > 1 else 1.0
    turnover = (len(trades) / years) if years else 0.0

    return {
        "Total Return": _safe(total_return),
        "CAGR": _safe(cagr),
        "Max Drawdown": _safe(max_dd),
        "Sharpe Ratio": _safe(sharpe),
        "Sortino Ratio": _safe(sortino),
        "Calmar Ratio": _safe(calmar),
        "Win Rate": _safe(len(wins) / len(trades)) if trades else 0.0,
        "Profit Factor": _safe(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "Expectancy ($)": _safe(np.mean(pnls)) if pnls else 0.0,
        "Avg Win ($)": _safe(np.mean(wins)) if wins else 0.0,
        "Avg Loss ($)": _safe(np.mean(losses)) if losses else 0.0,
        "Avg R-Multiple": _safe(np.mean(r_multiples)) if r_multiples else 0.0,
        "Exposure": _safe(exposure),
        "Avg Positions": _safe(avg_positions),
        "Trades / Year": _safe(turnover),
        "Total Trades": len(trades),
        "Avg Holding (days)": _safe(np.mean(holding)) if holding else 0.0,
        "Worst Month": _safe(monthly.min()) if len(monthly) else 0.0,
        "Worst Year": _safe(yearly.min()) if len(yearly) else 0.0,
    }


def regime_breakdown(daily: pd.DataFrame, spy: pd.DataFrame) -> Dict[str, Any]:
    """Split daily returns by SPY-above/below its 200-day MA, and by calendar year."""
    eq = daily["equity"]
    ret = eq.pct_change().fillna(0.0)
    spy_ma200 = spy["close"].rolling(200).mean().reindex(eq.index)
    above = (spy["close"].reindex(eq.index) > spy_ma200)

    def _agg(mask):
        r = ret[mask]
        if len(r) == 0:
            return {"days": 0, "cum_return": 0.0, "ann_return": 0.0}
        cum = (1 + r).prod() - 1
        ann = (1 + r).prod() ** (252 / len(r)) - 1 if len(r) > 0 else 0.0
        return {"days": int(len(r)), "cum_return": _safe(cum), "ann_return": _safe(ann)}

    by_year = []
    for yr, r in ret.groupby(ret.index.year):
        cum = (1 + r).prod() - 1
        by_year.append({"year": int(yr), "return": _safe(cum), "days": int(len(r))})

    return {
        "spy_above_200ma": _agg(above.fillna(False)),
        "spy_below_200ma": _agg(~above.fillna(True)),
        "by_year": by_year,
    }

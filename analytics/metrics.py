import pandas as pd
import numpy as np
from typing import Dict, Any


class PerformanceMetrics:
    """
    Calculates advanced performance analytics for backtest results.
    """

    @staticmethod
    def calculate_cagr(equity_curve: pd.Series) -> float:
        """Calculates Compound Annual Growth Rate (CAGR)."""
        if equity_curve.empty or len(equity_curve) < 2:
            return 0.0
        days = (equity_curve.index[-1] - equity_curve.index[0]).days
        if days <= 0:
            return 0.0
        years = days / 365.25
        return float((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1.0 / years) - 1.0)

    @staticmethod
    def calculate_sharpe_ratio(equity_curve: pd.Series) -> float:
        """Calculates Sharpe Ratio assuming 0% risk-free rate."""
        returns = equity_curve.pct_change().fillna(0.0)
        std = returns.std()
        if std == 0 or len(returns) < 2:
            return 0.0
        return float((returns.mean() / std) * np.sqrt(252))

    @staticmethod
    def calculate_sortino_ratio(equity_curve: pd.Series) -> float:
        """Calculates Sortino Ratio utilizing downside standard deviation."""
        returns = equity_curve.pct_change().fillna(0.0)
        # Downside returns (positive returns set to 0.0)
        downside_returns = np.minimum(returns, 0.0)
        downside_std = np.sqrt(np.mean(downside_returns ** 2))
        
        if downside_std == 0 or len(returns) < 2:
            return 0.0
            
        # Annualized values
        ann_return = returns.mean() * 252
        ann_downside_std = downside_std * np.sqrt(252)
        return float(ann_return / ann_downside_std)

    @staticmethod
    def calculate_max_drawdown(equity_curve: pd.Series) -> float:
        """Calculates maximum peak-to-trough drawdown (returns as negative decimal)."""
        if equity_curve.empty:
            return 0.0
        peaks = equity_curve.cummax()
        drawdowns = (equity_curve - peaks) / peaks
        return float(drawdowns.min())

    @staticmethod
    def calculate_win_rate(trades_df: pd.DataFrame) -> float:
        """Calculates percentage of trades with positive P&L."""
        if trades_df.empty:
            return 0.0
        winning_trades = trades_df[trades_df["pnl_usd"] > 1e-8]
        return float(len(winning_trades) / len(trades_df))

    @staticmethod
    def calculate_profit_factor(trades_df: pd.DataFrame) -> float:
        """Calculates Profit Factor (Gross Profits / Gross Losses)."""
        if trades_df.empty:
            return 0.0
        gross_profit = trades_df[trades_df["pnl_usd"] > 1e-8]["pnl_usd"].sum()
        gross_loss = abs(trades_df[trades_df["pnl_usd"] < -1e-8]["pnl_usd"].sum())
        if gross_loss == 0:
            return float('inf') if gross_profit > 0 else 1.0
        return float(gross_profit / gross_loss)

    @staticmethod
    def calculate_exposure_time(portfolio_df: pd.DataFrame) -> float:
        """Calculates percentage of time bars spent with an active position."""
        if portfolio_df.empty:
            return 0.0
        active_bars = portfolio_df[portfolio_df["active_position"].abs() > 1e-8]
        return float(len(active_bars) / len(portfolio_df))

    @staticmethod
    def get_benchmark_equity(prices: pd.Series, initial_capital: float) -> pd.Series:
        """Generates a buy-and-hold benchmark equity curve starting from Day 1."""
        returns = prices.pct_change().fillna(0.0)
        cum_growth = (1.0 + returns).cumprod()
        return initial_capital * cum_growth

    @classmethod
    def get_advanced_summary(cls, portfolio_df: pd.DataFrame, trades_df: pd.DataFrame) -> Dict[str, Any]:
        """Compiles advanced performance statistics into a summary dictionary."""
        equity = portfolio_df["equity"]
        return {
            "Total Return": float((equity.iloc[-1] / equity.iloc[0]) - 1.0) if not equity.empty else 0.0,
            "CAGR": cls.calculate_cagr(equity),
            "Sharpe Ratio": cls.calculate_sharpe_ratio(equity),
            "Sortino Ratio": cls.calculate_sortino_ratio(equity),
            "Max Drawdown": cls.calculate_max_drawdown(equity),
            "Win Rate": cls.calculate_win_rate(trades_df),
            "Profit Factor": cls.calculate_profit_factor(trades_df),
            "Exposure Time": cls.calculate_exposure_time(portfolio_df),
            "Total Trades": len(trades_df),
        }


def extract_trades(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """
    Parses chronological transaction logs and reconstructs discrete round-trip trades
    using a weighted average cost basis state machine.
    """
    df = portfolio_df.sort_index()

    # Determine trade execution prices
    exec_prices = df["open"] if "open" in df.columns else df["close"]

    position = 0.0
    avg_entry_price = 0.0
    entry_time = None
    closed_trades = []

    for t, row in df.iterrows():
        q_trade = float(row["trades"])
        if abs(q_trade) < 1e-8:
            continue

        p_trade = float(exec_prices.loc[t])

        if position == 0.0:
            # Position entry
            position = q_trade
            avg_entry_price = p_trade
            entry_time = t
        elif np.sign(q_trade) == np.sign(position):
            # Scale in (increase position)
            new_pos = position + q_trade
            avg_entry_price = (position * avg_entry_price + q_trade * p_trade) / new_pos
            position = new_pos
        else:
            # Scale out or reverse position
            # Qty closed is the minimum of absolute trade size or absolute position size
            q_closed = np.sign(position) * min(abs(q_trade), abs(position))
            pnl_usd = 0.0
            
            if position > 0:
                pnl_usd = abs(q_closed) * (p_trade - avg_entry_price)
            else:
                pnl_usd = abs(q_closed) * (avg_entry_price - p_trade)

            cost_basis = abs(q_closed) * avg_entry_price
            pnl_pct = pnl_usd / cost_basis if cost_basis > 0 else 0.0

            closed_trades.append({
                "entry_time": entry_time,
                "exit_time": t,
                "direction": "Long" if position > 0 else "Short",
                "size": abs(q_closed),
                "entry_price": avg_entry_price,
                "exit_price": p_trade,
                "pnl_usd": pnl_usd,
                "pnl_pct": pnl_pct,
                "duration_days": int((t - entry_time).days)
            })

            position = position - q_closed
            q_rem = q_trade + q_closed

            if abs(position) < 1e-8:
                position = 0.0
                if abs(q_rem) > 1e-8:
                    # Flip position to opposite direction
                    position = q_rem
                    avg_entry_price = p_trade
                    entry_time = t
                else:
                    avg_entry_price = 0.0
                    entry_time = None

    # Close out any remaining open positions on the final day for complete trade accounting
    if abs(position) > 1e-8:
        last_idx = df.index[-1]
        p_last = float(df["close"].iloc[-1])
        pnl_usd = 0.0
        
        if position > 0:
            pnl_usd = abs(position) * (p_last - avg_entry_price)
        else:
            pnl_usd = abs(position) * (avg_entry_price - p_last)

        cost_basis = abs(position) * avg_entry_price
        pnl_pct = pnl_usd / cost_basis if cost_basis > 0 else 0.0

        closed_trades.append({
            "entry_time": entry_time,
            "exit_time": last_idx,
            "direction": "Long" if position > 0 else "Short",
            "size": abs(position),
            "entry_price": avg_entry_price,
            "exit_price": p_last,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "duration_days": int((last_idx - entry_time).days)
        })

    return pd.DataFrame(closed_trades)

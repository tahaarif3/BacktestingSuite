import pandas as pd
import numpy as np


class ExecutionModel:
    """
    Simulates transaction costs (slippage and commissions) for order execution in a vectorized manner.
    """

    def __init__(
        self,
        slippage_pct: float = 0.0,
        slippage_abs: float = 0.0,
        commission_pct: float = 0.0,
        commission_per_share: float = 0.0,
        min_commission: float = 0.0
    ):
        """
        Args:
            slippage_pct: Slippage as a percentage of the asset price (e.g. 0.0005 for 0.05%).
            slippage_abs: Absolute slippage per share in currency units (e.g. $0.01 per share).
            commission_pct: Commission as a percentage of notional trade value (e.g. 0.001 for 0.1%).
            commission_per_share: Commission rate per traded share (e.g. $0.005 per share).
            min_commission: Minimum commission charged per execution transaction.
        """
        self.slippage_pct = slippage_pct
        self.slippage_abs = slippage_abs
        self.commission_pct = commission_pct
        self.commission_per_share = commission_per_share
        self.min_commission = min_commission

    def calculate_slippage(self, prices: pd.Series, trades: pd.Series) -> pd.Series:
        """
        Calculates the total slippage cost for each trade.
        
        Args:
            prices: Series of asset closing or execution prices.
            trades: Series of traded shares (positive for buy, negative for sell).
            
        Returns:
            pd.Series: Series representing slippage cost for each timestamp.
        """
        # Slippage cost = |shares| * (slippage_abs + execution_price * slippage_pct)
        return trades.abs() * (self.slippage_abs + prices * self.slippage_pct)

    def calculate_commission(self, prices: pd.Series, trades: pd.Series) -> pd.Series:
        """
        Calculates the total commission cost for each trade, enforcing minimum commissions.
        
        Args:
            prices: Series of asset closing or execution prices.
            trades: Series of traded shares.
            
        Returns:
            pd.Series: Series representing commission cost for each timestamp.
        """
        # Base commission = |shares| * (commission_per_share + price * commission_pct)
        base_commission = trades.abs() * (self.commission_per_share + prices * self.commission_pct)

        # Enforce minimum commission if trade size is greater than zero
        if self.min_commission > 0:
            commission_cost = np.where(
                trades.abs() > 1e-8,
                np.maximum(base_commission, self.min_commission),
                0.0
            )
            return pd.Series(commission_cost, index=trades.index)

        return base_commission

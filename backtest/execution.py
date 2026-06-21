import pandas as pd
import numpy as np
from domain.interfaces import IExecutionModel


class ExecutionModel(IExecutionModel):
    """
    Simulates transaction costs (slippage and commissions) for order execution.
    Conforms to the domain IExecutionModel interface.
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

    def calculate_slippage(self, price: float, shares: float) -> float:
        """
        Calculates the total slippage cost for a trade.
        Supports both scalar float and pandas Series/numpy arrays.
        """
        return abs(shares) * (self.slippage_abs + price * self.slippage_pct)

    def calculate_commission(self, price: float, shares: float) -> float:
        """
        Calculates the total commission cost for a trade, enforcing minimum commissions.
        Supports both scalar float and pandas Series/numpy arrays.
        """
        if isinstance(price, (pd.Series, np.ndarray)):
            # Vectorized calculation
            base_commission = abs(shares) * (self.commission_per_share + price * self.commission_pct)
            if self.min_commission > 0:
                commission_cost = np.where(
                    abs(shares) > 1e-8,
                    np.maximum(base_commission, self.min_commission),
                    0.0
                )
                if isinstance(shares, pd.Series):
                    return pd.Series(commission_cost, index=shares.index)
                return commission_cost
            return base_commission
        else:
            # Scalar calculation
            base_commission = abs(shares) * (self.commission_per_share + price * self.commission_pct)
            if self.min_commission > 0:
                if abs(shares) > 1e-8:
                    return float(max(base_commission, self.min_commission))
                return 0.0
            return float(base_commission)


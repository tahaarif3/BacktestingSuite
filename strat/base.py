from abc import ABC, abstractmethod
import pandas as pd


class BaseStrategy(ABC):
    """
    Abstract Base Class for defining trading strategies.
    """

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Takes cleaned market data and returns a DataFrame containing a 'signal' column.
        
        Args:
            data: DataFrame containing historical market data (OHLCV).
            
        Returns:
            pd.DataFrame: The DataFrame with an added 'signal' column (1 for Buy, -1 for Sell, 0 for Flat).
        """
        pass

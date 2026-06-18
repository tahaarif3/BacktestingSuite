import os
import pandas as pd
import yfinance as yf
from typing import Optional

# Alpaca imports (wrapped in a try-except block or imported directly since we expect it in requirements)
try:
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
except ImportError:
    # Fallback or placeholder for environments where alpaca-py is not installed yet
    StockHistoricalDataClient = None
    StockBarsRequest = None
    TimeFrame = None
    TimeFrameUnit = None


# Data Acquisition Module for retrieving historical market data
class DataFetcher:
    """
    A class to fetch historical financial market data using yfinance and Alpaca API.
    """

    def __init__(self, alpaca_api_key: Optional[str] = None, alpaca_secret_key: Optional[str] = None):
        """
        Initialize the DataFetcher.
        
        Args:
            alpaca_api_key: Optional Alpaca API Key ID. If not provided, will look for APCA_API_KEY_ID env var.
            alpaca_secret_key: Optional Alpaca Secret Key. If not provided, will look for APCA_API_SECRET_KEY env var.
        """
        self.alpaca_api_key = alpaca_api_key or os.environ.get("APCA_API_KEY_ID")
        self.alpaca_secret_key = alpaca_secret_key or os.environ.get("APCA_API_SECRET_KEY")
        self._alpaca_client = None

    @property
    def alpaca_client(self):
        """Lazy initialization of Alpaca Client."""
        if self._alpaca_client is None:
            if not self.alpaca_api_key or not self.alpaca_secret_key:
                raise ValueError(
                    "Alpaca API credentials are required. Set APCA_API_KEY_ID and APCA_API_SECRET_KEY environment variables."
                )
            if StockHistoricalDataClient is None:
                raise ImportError("alpaca-py package is not installed or import failed.")
            self._alpaca_client = StockHistoricalDataClient(
                api_key=self.alpaca_api_key, secret_key=self.alpaca_secret_key
            )
        return self._alpaca_client

    # Fetch historical daily and intraday OHLCV data from yfinance API
    def fetch_yfinance(
        self, symbol: str, start: str, end: str, interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Fetch historical stock data from yfinance.
        
        Args:
            symbol: The ticker symbol (e.g. 'SPY').
            start: Start date string (YYYY-MM-DD).
            end: End date string (YYYY-MM-DD).
            interval: Data interval (e.g. '1d', '5m', '1m', '1h').
            
        Returns:
            pd.DataFrame: DataFrame containing stock data.
        """
        print(f"Fetching {symbol} from yfinance (Interval: {interval}, Range: {start} to {end})...")
        
        # yfinance download
        # auto_adjust=True makes sure Close is adjusted for splits & dividends
        df = yf.download(
            tickers=symbol,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False
        )
        
        if df.empty:
            raise ValueError(f"No data returned for ticker {symbol} from yfinance.")
            
        return df

    def _map_alpaca_timeframe(self, interval: str) -> "TimeFrame":
        """Maps standard interval strings to Alpaca TimeFrame objects."""
        if TimeFrame is None or TimeFrameUnit is None:
            raise ImportError("alpaca-py package is not installed.")
            
        clean_interval = interval.lower().strip()
        if clean_interval in ("1d", "daily"):
            return TimeFrame.Day
        elif clean_interval in ("1h", "1hour", "hour"):
            return TimeFrame.Hour
        elif clean_interval in ("1m", "1min", "minute"):
            return TimeFrame.Minute
        
        # Custom timeframes (e.g. '5m', '15m', '30m')
        # Check if it ends with 'm' or 'min' or 'h'
        import re
        match = re.match(r"(\d+)\s*(m|min|h|hour|d|day)", clean_interval)
        if match:
            value = int(match.group(1))
            unit_str = match.group(2)
            if unit_str in ("m", "min"):
                return TimeFrame(value, TimeFrameUnit.Minute)
            elif unit_str in ("h", "hour"):
                return TimeFrame(value, TimeFrameUnit.Hour)
            elif unit_str in ("d", "day"):
                return TimeFrame(value, TimeFrameUnit.Day)
                
        raise ValueError(f"Unsupported Alpaca timeframe interval: {interval}")

    # Fetch historical daily and intraday bar data from Alpaca API
    def fetch_alpaca(
        self, symbol: str, start: str, end: str, interval: str = "1d"
    ) -> pd.DataFrame:
        """
        Fetch historical stock data from Alpaca.
        
        Args:
            symbol: The ticker symbol (e.g. 'SPY').
            start: Start date string or ISO timestamp (YYYY-MM-DD).
            end: End date string or ISO timestamp (YYYY-MM-DD).
            interval: Data interval (e.g. '1d', '5m', '1m', '1h').
            
        Returns:
            pd.DataFrame: DataFrame containing stock data.
        """
        print(f"Fetching {symbol} from Alpaca (Interval: {interval}, Range: {start} to {end})...")
        
        timeframe = self._map_alpaca_timeframe(interval)
        
        # Convert start and end strings to pandas Datetime objects
        start_dt = pd.to_datetime(start)
        end_dt = pd.to_datetime(end)
        
        request_params = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=timeframe,
            start=start_dt,
            end=end_dt
        )
        
        bars = self.alpaca_client.get_stock_bars(request_params)
        df = bars.df
        
        if df is None or df.empty:
            raise ValueError(f"No data returned for ticker {symbol} from Alpaca.")
            
        # Standard Alpaca multi-index is (symbol, timestamp). Reset symbol since we fetch single ticker
        if isinstance(df.index, pd.MultiIndex):
            df = df.xs(symbol, level='symbol')
            
        return df

    # Save the retrieved DataFrame locally in Parquet format
    def save_to_parquet(self, df: pd.DataFrame, filepath: str) -> None:
        """
        Save DataFrame to Parquet format.
        
        Args:
            df: The DataFrame to save.
            filepath: Path to the target Parquet file.
        """
        # Ensure directories exist
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        
        print(f"Saving data to Parquet: {filepath}")
        df.to_parquet(filepath, engine='pyarrow')

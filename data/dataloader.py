import pandas as pd
from typing import Optional, Union


# DataLoader Module for loading, cleaning, and preprocessing cached market data
class DataLoader:
    """
    Loads and cleans historical data from cached Parquet files.
    """

    def __init__(self, filepath: Optional[str] = None):
        """
        Initialize DataLoader.
        
        Args:
            filepath: Optional default path to the Parquet file.
        """
        self.filepath = filepath

    # Load cached Parquet data from local disk
    def load_data(self, filepath: Optional[str] = None) -> pd.DataFrame:
        """
        Read the Parquet file from disk.
        
        Args:
            filepath: Path to the Parquet file. If None, uses the one from init.
            
        Returns:
            pd.DataFrame: Raw loaded DataFrame.
        """
        path = filepath or self.filepath
        if not path:
            raise ValueError("No filepath specified for loading data.")
        
        print(f"Loading data from Parquet file: {path}")
        return pd.read_parquet(path)

    # Standardize column casing, handle MultiIndex columns, rename adjusted close, remove duplicates, and impute NaNs
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean the market data DataFrame:
        - Handle MultiIndex columns (flatten them if they exist).
        - Standardize column names to lowercase (e.g. open, high, low, close, volume).
        - If 'adj close' exists, map it to 'close'.
        - Set index to datetime and sort it.
        - Handle missing values (forward fill for prices, fillna(0) for volume).
        - Drop duplicates in the index.
        
        Args:
            df: Raw input DataFrame.
            
        Returns:
            pd.DataFrame: Cleaned DataFrame.
        """
        if df.empty:
            return df
            
        # Copy vs View (NumPy Video 4): Explicitly create a copy of the dataframe.
        # This copies the underlying NumPy arrays in memory, avoiding modifications to the original data 
        # structure and preventing pandas 'SettingWithCopyWarning'.
        df = df.copy()
        
        # 1. Handle MultiIndex columns (e.g., when downloaded via yfinance with ticker name)
        if isinstance(df.columns, pd.MultiIndex):
            # Flatten columns. E.g., ('Close', 'SPY') becomes 'Close'
            # We assume the first level is the price field (Open, High, Low, Close, etc.)
            df.columns = df.columns.get_level_values(0)
            
        # 2. Standardize column names to lower case
        df.columns = [str(col).lower().strip().replace(" ", "_") for col in df.columns]
        
        # 3. Handle 'adj_close' or 'adj close' if they exist and close is not already auto-adjusted
        # If both 'close' and 'adj_close' exist, we rename 'close' to 'unadj_close' and 'adj_close' to 'close'
        if "adj_close" in df.columns and "close" in df.columns:
            df = df.rename(columns={"close": "unadj_close", "adj_close": "close"})
        elif "adj_close" in df.columns and "close" not in df.columns:
            df = df.rename(columns={"adj_close": "close"})
            
        # 4. Standardize index
        # Ensure the index is a datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
            
        df.index.name = "timestamp"
        
        # Drop duplicates in the index, keeping the first
        df = df[~df.index.duplicated(keep="first")]
        
        # Sorting (NumPy Video 7): Sort the index chronologically.
        # Pandas uses NumPy's underlying sorting algorithms (such as quicksort or mergesort) to order indices.
        df = df.sort_index()
        
        # 5. Clean missing values
        # For typical OHLC columns, forward fill
        price_cols = [c for c in ["open", "high", "low", "close", "unadj_close", "vwap"] if c in df.columns]
        df[price_cols] = df[price_cols].ffill().bfill()
        
        # For volume, fill missing with 0
        if "volume" in df.columns:
            df["volume"] = df["volume"].fillna(0)
            
        # Drop any remaining NaNs in standard OHLC columns
        essential_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
        df = df.dropna(subset=essential_cols)
        
        return df

    # Retrieve a slice of the cleaned data based on the start and end timestamps
    def get_data_range(
        self,
        df: pd.DataFrame,
        start_date: Optional[Union[str, pd.Timestamp]] = None,
        end_date: Optional[Union[str, pd.Timestamp]] = None
    ) -> pd.DataFrame:
        """
        Filter the DataFrame to a specific date/time range.
        
        Args:
            df: Cleaned input DataFrame.
            start_date: Start date string or Timestamp (inclusive). If None, start from beginning.
            end_date: End date string or Timestamp (inclusive). If None, go to end.
            
        Returns:
            pd.DataFrame: Filtered DataFrame.
        """
        if df.empty:
            return df
            
        # Standardize timezone handling if index is timezone-aware
        # If the input dates are timezone naive, localize them to match the index if the index is timezone aware
        tz = df.index.tz
        
        if start_date is not None:
            start_ts = pd.to_datetime(start_date)
            if tz is not None and start_ts.tz is None:
                start_ts = start_ts.tz_localize(tz)
            # Searching and Filtering (NumPy Videos 8 & 9): Boolean Indexing/Masking.
            # Performs a vectorized comparison returning a boolean mask (NumPy boolean array) to filter rows.
            df = df[df.index >= start_ts]
            
        if end_date is not None:
            end_ts = pd.to_datetime(end_date)
            if tz is not None and end_ts.tz is None:
                end_ts = end_ts.tz_localize(tz)
            # Searching and Filtering (NumPy Videos 8 & 9): Boolean Indexing/Masking.
            # Vectorized comparison to filter rows up to the end timestamp.
            df = df[df.index <= end_ts]
            
        return df

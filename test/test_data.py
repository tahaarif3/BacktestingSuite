# Unit tests to verify the behavior of DataFetcher and DataLoader
import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from data.fetcher import DataFetcher
from data.dataloader import DataLoader

# ----------------- FIXTURES -----------------

@pytest.fixture
def sample_market_data():
    """Generates standard daily market data for testing cleaning and loading."""
    dates = pd.date_range(start="2023-01-01", end="2023-01-10", freq="D")
    # NumPy Arrays (NumPy Video 1): Pandas constructs DataFrames backed by NumPy 
    # float64 and int64 arrays under the hood.
    # NumPy Video 3 (Universal Functions & Constants): We use NumPy's np.nan constant 
    # to represent missing data elements for testing the loader's imputation logic.
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, np.nan, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
            "High": [102.0, 103.0, 104.0, 105.0, np.nan, 107.0, 108.0, 109.0, 110.0, 111.0],
            "Low": [99.0, 100.0, 98.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0],
            "Close": [101.0, 102.0, 103.0, 104.0, 104.5, 106.0, 107.0, 108.0, 109.0, 110.0],
            "Volume": [1000, 1500, 1200, np.nan, 1800, 2000, 2100, 2200, 2300, 2400],
        },
        index=dates,
    )
    return df


@pytest.fixture
def sample_multiindex_data():
    """Generates a yfinance style MultiIndex DataFrame."""
    dates = pd.date_range(start="2023-01-01", end="2023-01-03", freq="D")
    columns = pd.MultiIndex.from_tuples(
        [
            ("Open", "SPY"),
            ("High", "SPY"),
            ("Low", "SPY"),
            ("Close", "SPY"),
            ("Volume", "SPY"),
        ]
    )
    data = [
        [100.0, 102.0, 99.0, 101.0, 1000],
        [101.0, 103.0, 100.0, 102.0, 1500],
        [102.0, 104.0, 101.0, 103.0, 1200],
    ]
    return pd.DataFrame(data, index=dates, columns=columns)


# Test suite for validating yfinance and Alpaca fetching, parameters mapping, and Parquet caching using MagicMock
# ----------------- TEST DATAFETCHER -----------------

def test_fetcher_init():
    """Test environment variable fallback for Alpaca credentials."""
    with patch.dict(os.environ, {"APCA_API_KEY_ID": "env_key", "APCA_API_SECRET_KEY": "env_secret"}):
        fetcher = DataFetcher()
        assert fetcher.alpaca_api_key == "env_key"
        assert fetcher.alpaca_secret_key == "env_secret"


def test_fetcher_init_with_params():
    """Test explicit credentials passed to DataFetcher."""
    fetcher = DataFetcher(alpaca_api_key="param_key", alpaca_secret_key="param_secret")
    assert fetcher.alpaca_api_key == "param_key"
    assert fetcher.alpaca_secret_key == "param_secret"


@patch("data.fetcher.yf.download")
def test_fetch_yfinance(mock_download, sample_market_data):
    """Test fetch_yfinance calls download and returns data."""
    mock_download.return_value = sample_market_data
    
    fetcher = DataFetcher()
    df = fetcher.fetch_yfinance(symbol="SPY", start="2023-01-01", end="2023-01-10")
    
    mock_download.assert_called_once_with(
        tickers="SPY",
        start="2023-01-01",
        end="2023-01-10",
        interval="1d",
        auto_adjust=True,
        progress=False,
    )
    assert not df.empty
    assert len(df) == 10


@patch("data.fetcher.yf.download")
def test_fetch_yfinance_empty_error(mock_download):
    """Test fetch_yfinance raises ValueError when download returns empty df."""
    mock_download.return_value = pd.DataFrame()
    
    fetcher = DataFetcher()
    with pytest.raises(ValueError, match="No data returned for ticker SPY from yfinance"):
        fetcher.fetch_yfinance(symbol="SPY", start="2023-01-01", end="2023-01-05")


@patch("data.fetcher.StockHistoricalDataClient")
def test_fetch_alpaca(mock_client_class, sample_market_data):
    """Test fetch_alpaca calls client methods and formats response."""
    # Set up mock client & response
    mock_client_inst = MagicMock()
    mock_client_class.return_value = mock_client_inst
    
    # Mock return value of client.get_stock_bars
    mock_bars = MagicMock()
    # Mock bars.df to return multiindexed dataframe
    dates = pd.date_range(start="2023-01-01", end="2023-01-03", freq="D")
    columns = ["open", "high", "low", "close", "volume"]
    index = pd.MultiIndex.from_tuples(
        [("SPY", dates[0]), ("SPY", dates[1]), ("SPY", dates[2])],
        names=["symbol", "timestamp"],
    )
    mock_df = pd.DataFrame(
        [
            [100.0, 102.0, 99.0, 101.0, 1000],
            [101.0, 103.0, 100.0, 102.0, 1500],
            [102.0, 104.0, 101.0, 103.0, 1200],
        ],
        index=index,
        columns=columns,
    )
    mock_bars.df = mock_df
    mock_client_inst.get_stock_bars.return_value = mock_bars

    fetcher = DataFetcher(alpaca_api_key="key", alpaca_secret_key="secret")
    df = fetcher.fetch_alpaca(symbol="SPY", start="2023-01-01", end="2023-01-03", interval="1d")

    assert mock_client_inst.get_stock_bars.called
    assert "timestamp" == df.index.name or df.index.name is None
    assert len(df) == 3
    # Check index resets (multiindex removed)
    assert not isinstance(df.index, pd.MultiIndex)
    assert list(df.columns) == columns


def test_map_alpaca_timeframe():
    """Test timeframe mapping logic in DataFetcher."""
    fetcher = DataFetcher()
    # Daily
    tf_day = fetcher._map_alpaca_timeframe("1d")
    assert tf_day.value == "1Day"
    # Minute
    tf_min = fetcher._map_alpaca_timeframe("1m")
    assert tf_min.value == "1Min"
    # Custom
    tf_5m = fetcher._map_alpaca_timeframe("5m")
    assert tf_5m.value == "5Min"
    
    # Unrecognized
    with pytest.raises(ValueError, match="Unsupported Alpaca timeframe interval"):
        fetcher._map_alpaca_timeframe("invalid_tf")


@patch("pandas.DataFrame.to_parquet")
@patch("os.makedirs")
def test_save_to_parquet(mock_makedirs, mock_to_parquet, sample_market_data):
    """Test save_to_parquet writes data via pandas."""
    fetcher = DataFetcher()
    fetcher.save_to_parquet(sample_market_data, "fake_path/file.parquet")
    
    mock_makedirs.assert_called_once()
    mock_to_parquet.assert_called_once_with("fake_path/file.parquet", engine="pyarrow")


# Test suite for validating file loading, column standardization, ffill/bfill, and datetime filters
# ----------------- TEST DATALOADER -----------------

def test_dataloader_init():
    """Test DataLoader initialization."""
    loader = DataLoader("path.parquet")
    assert loader.filepath == "path.parquet"


@patch("pandas.read_parquet")
def test_dataloader_load_data(mock_read_parquet, sample_market_data):
    """Test DataLoader reads parquet file from disk."""
    mock_read_parquet.return_value = sample_market_data
    
    loader = DataLoader("fake_path.parquet")
    df = loader.load_data()
    
    mock_read_parquet.assert_called_once_with("fake_path.parquet")
    assert len(df) == 10


def test_dataloader_clean_data(sample_market_data):
    """Test cleaning operations (casing, timezone, duplicates, sorting, ffill)."""
    # Create duplicate dates in input data to test drop duplicates
    dates = list(sample_market_data.index)
    dates[2] = dates[1] # Duplicate index entry
    sample_market_data.index = dates
    
    loader = DataLoader()
    cleaned_df = loader.clean_data(sample_market_data)
    
    # Assert columns renamed to lower case
    assert list(cleaned_df.columns) == ["open", "high", "low", "close", "volume"]
    # Assert index name set to timestamp
    assert cleaned_df.index.name == "timestamp"
    # Assert duplicates removed
    assert len(cleaned_df) == 9
    # Assert sorted chronologically
    assert cleaned_df.index.is_monotonic_increasing
    # Assert nulls in price column are forward/backward filled
    assert not cleaned_df["open"].isnull().any()
    assert not cleaned_df["high"].isnull().any()
    assert not cleaned_df["volume"].isnull().any()


def test_dataloader_clean_multiindex(sample_multiindex_data):
    """Test flattening of MultiIndexed columns."""
    loader = DataLoader()
    cleaned_df = loader.clean_data(sample_multiindex_data)
    
    # Assert column level names flattened
    assert not isinstance(cleaned_df.columns, pd.MultiIndex)
    assert list(cleaned_df.columns) == ["open", "high", "low", "close", "volume"]


def test_dataloader_clean_adj_close():
    """Test that adj_close is renamed to close, and original close to unadj_close."""
    dates = pd.date_range("2023-01-01", periods=3)
    df = pd.DataFrame(
        {
            "Open": [100, 101, 102],
            "Close": [100, 101, 102],
            "Adj Close": [98, 99, 100],
            "Volume": [100, 100, 100]
        },
        index=dates
    )
    
    loader = DataLoader()
    cleaned = loader.clean_data(df)
    
    assert "close" in cleaned.columns
    assert "unadj_close" in cleaned.columns
    # Check that close corresponds to the original 'Adj Close'
    assert list(cleaned["close"]) == [98, 99, 100]
    assert list(cleaned["unadj_close"]) == [100, 101, 102]


def test_dataloader_get_data_range(sample_market_data):
    """Test date range filtering."""
    loader = DataLoader()
    cleaned_df = loader.clean_data(sample_market_data)
    
    # Filter range
    filtered = loader.get_data_range(cleaned_df, start_date="2023-01-03", end_date="2023-01-06")
    
    assert len(filtered) == 4
    assert filtered.index[0] == pd.to_datetime("2023-01-03")
    assert filtered.index[-1] == pd.to_datetime("2023-01-06")
    
    # Filter with tz-aware index to verify handling
    cleaned_df.index = cleaned_df.index.tz_localize("UTC")
    filtered_tz = loader.get_data_range(cleaned_df, start_date="2023-01-03", end_date="2023-01-06")
    
    assert len(filtered_tz) == 4
    assert filtered_tz.index[0] == pd.to_datetime("2023-01-03").tz_localize("UTC")

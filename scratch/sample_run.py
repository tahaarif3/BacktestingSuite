# Manual verification script to fetch daily and intraday SPY data, verify parquet writing, and dataloader operations
import os
import sys
import pandas as pd

# Add the project root to path so we can import from data
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import DataFetcher
from data.dataloader import DataLoader

def main():
    print("=== SPY Backtest Data Acquisition Verification ===")
    
    # Initialize Fetcher and Loader
    fetcher = DataFetcher()
    loader = DataLoader()
    
    # Define date ranges
    # 1 year of daily data
    daily_start = (pd.Timestamp.now() - pd.Timedelta(days=365)).strftime("%Y-%m-%d")
    daily_end = pd.Timestamp.now().strftime("%Y-%m-%d")
    
    # 5 days of intraday data (use a 5m interval)
    intraday_start = (pd.Timestamp.now() - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
    intraday_end = pd.Timestamp.now().strftime("%Y-%m-%d")
    
    print(f"Daily Range: {daily_start} to {daily_end}")
    print(f"Intraday Range: {intraday_start} to {intraday_end}")
    
    # ----------------- YFINANCE FETCH & LOAD -----------------
    print("\n--- Testing yfinance ---")
    try:
        # Fetch daily
        yf_daily_raw = fetcher.fetch_yfinance("SPY", start=daily_start, end=daily_end, interval="1d")
        daily_path = os.path.join("data", "spy_daily_yfinance.parquet")
        fetcher.save_to_parquet(yf_daily_raw, daily_path)
        
        # Load and clean daily
        yf_daily_loaded = loader.load_data(daily_path)
        yf_daily_cleaned = loader.clean_data(yf_daily_loaded)
        print(f"Cleaned yfinance Daily Data Shape: {yf_daily_cleaned.shape}")
        print("First 3 rows:")
        print(yf_daily_cleaned.head(3))
        
        # Fetch intraday (5-minute interval)
        yf_intra_raw = fetcher.fetch_yfinance("SPY", start=intraday_start, end=intraday_end, interval="5m")
        intra_path = os.path.join("data", "spy_5m_yfinance.parquet")
        fetcher.save_to_parquet(yf_intra_raw, intra_path)
        
        # Load and clean intraday
        yf_intra_loaded = loader.load_data(intra_path)
        yf_intra_cleaned = loader.clean_data(yf_intra_loaded)
        print(f"Cleaned yfinance Intraday Data Shape: {yf_intra_cleaned.shape}")
        print("First 3 rows:")
        print(yf_intra_cleaned.head(3))
        
    except Exception as e:
        print(f"Error testing yfinance: {e}")
        
    # ----------------- ALPACA FETCH & LOAD (OPTIONAL) -----------------
    print("\n--- Testing Alpaca ---")
    alpaca_key = os.environ.get("APCA_API_KEY_ID")
    alpaca_secret = os.environ.get("APCA_API_SECRET_KEY")
    
    if not alpaca_key or not alpaca_secret:
        print("Alpaca credentials APCA_API_KEY_ID and/or APCA_API_SECRET_KEY not found in environment.")
        print("Skipping Alpaca live integration tests. (Alpaca mock unit tests are verified).")
    else:
        try:
            # Fetch daily
            alpaca_daily_raw = fetcher.fetch_alpaca("SPY", start=daily_start, end=daily_end, interval="1d")
            alpaca_daily_path = os.path.join("data", "spy_daily_alpaca.parquet")
            fetcher.save_to_parquet(alpaca_daily_raw, alpaca_daily_path)
            
            # Load and clean daily
            alpaca_daily_loaded = loader.load_data(alpaca_daily_path)
            alpaca_daily_cleaned = loader.clean_data(alpaca_daily_loaded)
            print(f"Cleaned Alpaca Daily Data Shape: {alpaca_daily_cleaned.shape}")
            print("First 3 rows:")
            print(alpaca_daily_cleaned.head(3))
            
            # Fetch intraday
            # Alpaca requires ISO format time strings or datetimes, fetcher handles conversion
            alpaca_intra_raw = fetcher.fetch_alpaca("SPY", start=intraday_start, end=intraday_end, interval="5m")
            alpaca_intra_path = os.path.join("data", "spy_5m_alpaca.parquet")
            fetcher.save_to_parquet(alpaca_intra_raw, alpaca_intra_path)
            
            # Load and clean intraday
            alpaca_intra_loaded = loader.load_data(alpaca_intra_path)
            alpaca_intra_cleaned = loader.clean_data(alpaca_intra_loaded)
            print(f"Cleaned Alpaca Intraday Data Shape: {alpaca_intra_cleaned.shape}")
            print("First 3 rows:")
            print(alpaca_intra_cleaned.head(3))
            
        except Exception as e:
            print(f"Error testing Alpaca: {e}")

if __name__ == "__main__":
    main()

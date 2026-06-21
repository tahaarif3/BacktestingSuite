import os
import sys

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.fetcher import DataFetcher

def main():
    fetcher = DataFetcher()
    # Fetch 5 years of daily SPY data: June 21, 2021 to June 21, 2026
    start_date = "2021-06-21"
    end_date = "2026-06-21"
    
    df = fetcher.fetch_yfinance(
        symbol="SPY",
        start=start_date,
        end=end_date,
        interval="1d"
    )
    
    # Save to data/spy_daily_5y.parquet
    target_path = os.path.join("data", "spy_daily_5y.parquet")
    fetcher.save_to_parquet(df, target_path)
    
    print(f"Successfully fetched and saved {len(df)} daily SPY bars to {target_path}")

if __name__ == "__main__":
    main()

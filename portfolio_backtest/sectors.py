"""Static sector classification for common large-caps.

HONEST LIMITATION: this is a *current* static map, not point-in-time historical
sector membership. It's enough to exercise the sector-cap logic on a large-cap
watchlist; unknown tickers fall back to "Unknown" (which the engine treats as a
single shared bucket, so cap it deliberately).
"""

from __future__ import annotations

SECTORS = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AVGO": "Technology",
    "ORCL": "Technology", "CRM": "Technology", "ADBE": "Technology", "AMD": "Technology",
    "QCOM": "Technology", "INTC": "Technology", "CSCO": "Technology", "TXN": "Technology",
    "IBM": "Technology", "NOW": "Technology", "MU": "Technology", "AMAT": "Technology",
    # Communication Services
    "GOOGL": "Communication", "GOOG": "Communication", "META": "Communication",
    "NFLX": "Communication", "DIS": "Communication", "CMCSA": "Communication", "T": "Communication",
    "VZ": "Communication", "TMUS": "Communication",
    # Consumer Discretionary
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary", "HD": "Consumer Discretionary",
    "MCD": "Consumer Discretionary", "NKE": "Consumer Discretionary", "SBUX": "Consumer Discretionary",
    "LOW": "Consumer Discretionary", "BKNG": "Consumer Discretionary", "TJX": "Consumer Discretionary",
    # Consumer Staples
    "COST": "Consumer Staples", "WMT": "Consumer Staples", "PG": "Consumer Staples",
    "KO": "Consumer Staples", "PEP": "Consumer Staples", "MDLZ": "Consumer Staples",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials", "GS": "Financials",
    "MS": "Financials", "V": "Financials", "MA": "Financials", "AXP": "Financials",
    "BLK": "Financials", "SPGI": "Financials", "C": "Financials",
    # Health Care
    "LLY": "Health Care", "UNH": "Health Care", "JNJ": "Health Care", "MRK": "Health Care",
    "ABBV": "Health Care", "PFE": "Health Care", "TMO": "Health Care", "ABT": "Health Care",
    "DHR": "Health Care", "AMGN": "Health Care",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy", "EOG": "Energy",
    # Industrials
    "CAT": "Industrials", "BA": "Industrials", "HON": "Industrials", "GE": "Industrials",
    "UPS": "Industrials", "RTX": "Industrials", "DE": "Industrials", "LMT": "Industrials",
    # Utilities / Materials / Real Estate
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities",
    "LIN": "Materials", "SHW": "Materials", "FCX": "Materials",
    "AMT": "Real Estate", "PLD": "Real Estate",
}


def sector_of(ticker: str) -> str:
    return SECTORS.get(ticker.upper(), "Unknown")

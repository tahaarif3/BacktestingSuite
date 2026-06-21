import os
import pytest
import pandas as pd
from datetime import datetime
from analytics.reports import generate_html_report

def test_generate_html_report(tmp_path):
    # Construct mock portfolio data
    dates = pd.date_range(start="2020-01-01", periods=10, freq="D")
    portfolio_df = pd.DataFrame({
        "open": [100.0] * 10,
        "high": [100.0] * 10,
        "low": [100.0] * 10,
        "close": [100.0] * 10,
        "equity": [100000.0 + i * 100 for i in range(10)],
        "active_position": [1.0] * 10
    }, index=dates)
    
    # Construct mock trades data
    trades_df = pd.DataFrame({
        "entry_time": [dates[0], dates[3]],
        "exit_time": [dates[2], dates[5]],
        "direction": ["Long", "Short"],
        "size": [10.0, 5.0],
        "entry_price": [100.0, 101.0],
        "exit_price": [102.0, 99.0],
        "pnl_usd": [200.0, 100.0],
        "pnl_pct": [0.02, 0.01],
        "duration_days": [2, 2]
    })

    output_file = os.path.join(tmp_path, "test_report.html")
    
    # Run the report generator
    report_path = generate_html_report(
        portfolio_df=portfolio_df,
        trades_df=trades_df,
        strategy_name="TEST SMA STRATEGY",
        strategy_params={"fast_window": 10, "slow_window": 50},
        output_path=output_file
    )
    
    assert os.path.exists(report_path)
    
    # Verify content
    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert "TEST SMA STRATEGY" in content
        assert "Backtest Report" in content
        assert "<th>Entry Time</th>" in content
        assert "class=\"metric-value\"" in content
        # Ensure charts are embedded as base64 images
        assert "src=\"data:image/png;base64," in content

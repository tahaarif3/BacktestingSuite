import os
import base64
import pandas as pd
from datetime import datetime
from typing import Dict, Any
from analytics.metrics import PerformanceMetrics
from analytics.plots import generate_backtest_report_plots

def generate_html_report(
    portfolio_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    strategy_name: str,
    strategy_params: Dict[str, Any],
    output_path: str
) -> str:
    """
    Orchestrates the creation of a high-fidelity, self-contained HTML report.
    Generates Matplotlib plots, encodes them to base64, compiles advanced statistics,
    and saves a beautifully styled slate-modern dashboard to disk.
    """
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    # 1. Generate metrics summary
    summary = PerformanceMetrics.get_advanced_summary(portfolio_df, trades_df)

    # 2. Generate benchmark curve and plots
    initial_capital = portfolio_df["equity"].iloc[0]
    benchmark_curve = PerformanceMetrics.get_benchmark_equity(portfolio_df["close"], initial_capital)
    
    # We save plots to a temporary directory in output_dir, then read them, and delete them
    temp_plots_dir = os.path.join(output_dir, "temp_plots")
    os.makedirs(temp_plots_dir, exist_ok=True)
    
    plot_paths = generate_backtest_report_plots(portfolio_df, benchmark_curve, temp_plots_dir)

    # 3. Helper to convert images to inline base64
    def file_to_base64(file_path: str) -> str:
        if not os.path.exists(file_path):
            return ""
        with open(file_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")
        return f"data:image/png;base64,{encoded}"

    equity_b64 = file_to_base64(plot_paths["equity_comparison"])
    drawdown_b64 = file_to_base64(plot_paths["drawdown_chart"])
    rolling_b64 = file_to_base64(plot_paths["rolling_returns"])

    # Clean up temp plots
    for path in plot_paths.values():
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    try:
        os.rmdir(temp_plots_dir)
    except Exception:
        pass

    # 4. Format metrics for template display
    def fmt_pct(val) -> str:
        return f"{val * 100:.2f}%"

    def fmt_curr(val) -> str:
        return f"${val:,.2f}"

    def fmt_dec(val) -> str:
        return f"{val:.4f}"

    tot_return_str = fmt_pct(summary.get("Total Return", 0.0))
    cagr_str = fmt_pct(summary.get("CAGR", 0.0))
    sharpe_str = fmt_dec(summary.get("Sharpe Ratio", 0.0))
    sortino_str = fmt_dec(summary.get("Sortino Ratio", 0.0))
    mdd_str = fmt_pct(summary.get("Max Drawdown", 0.0))
    win_rate_str = fmt_pct(summary.get("Win Rate", 0.0))
    pf_str = fmt_dec(summary.get("Profit Factor", 0.0)) if summary.get("Profit Factor", 0.0) != float('inf') else "∞"
    exposure_str = fmt_pct(summary.get("Exposure Time", 0.0))
    total_trades_str = str(summary.get("Total Trades", 0))

    initial_equity_str = fmt_curr(portfolio_df["equity"].iloc[0])
    final_equity_str = fmt_curr(portfolio_df["equity"].iloc[-1])

    # 5. Build trade logs HTML table
    trades_rows = []
    if trades_df.empty:
        trades_rows.append("<tr><td colspan='9' style='text-align: center;'>No trades executed during this run.</td></tr>")
    else:
        # Take up to last 100 trades for display length limitation
        display_trades = trades_df.tail(100)
        for idx, row in display_trades.iterrows():
            entry_str = row["entry_time"].strftime("%Y-%m-%d %H:%M") if hasattr(row["entry_time"], "strftime") else str(row["entry_time"])
            exit_str = row["exit_time"].strftime("%Y-%m-%d %H:%M") if hasattr(row["exit_time"], "strftime") else str(row["exit_time"])
            dir_class = "direction-long" if row["direction"] == "Long" else "direction-short"
            pnl_class = "pnl-positive" if row["pnl_usd"] >= 0 else "pnl-negative"
            
            row_html = f"""
            <tr>
                <td>{entry_str}</td>
                <td>{exit_str}</td>
                <td><span class="direction-badge {dir_class}">{row["direction"]}</span></td>
                <td>{row["size"]:.1f}</td>
                <td>{fmt_curr(row["entry_price"])}</td>
                <td>{fmt_curr(row["exit_price"])}</td>
                <td class="{pnl_class}">{fmt_curr(row["pnl_usd"])}</td>
                <td class="{pnl_class}">{fmt_pct(row["pnl_pct"])}</td>
                <td>{int(row["duration_days"])}</td>
            </tr>
            """
            trades_rows.append(row_html)

    trades_table_body = "\n".join(trades_rows)

    # Strategy params formatting
    params_html = "".join([f"<span class='param-tag'><strong>{k}</strong>: {v}</span>" for k, v in strategy_params.items()])

    # HTML Template
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SPY Backtest Report - {strategy_name}</title>
    <style>
        :root {{
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --primary: #0284c7;
            --primary-light: #e0f2fe;
            --success: #10b981;
            --success-light: #d1fae5;
            --danger: #ef4444;
            --danger-light: #fee2e2;
            --border-color: #e2e8f0;
            --accent: #4f46e5;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            padding: 0;
            line-height: 1.5;
        }}

        .container {{
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
        }}

        header {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px 32px;
            margin-bottom: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }}

        .header-title h1 {{
            margin: 0 0 8px 0;
            font-size: 24px;
            font-weight: 800;
            letter-spacing: -0.025em;
            color: var(--text-main);
        }}

        .header-title .strategy-info {{
            font-size: 14px;
            color: var(--text-muted);
            margin-bottom: 12px;
        }}

        .params-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}

        .param-tag {{
            background-color: #f1f5f9;
            border: 1px solid var(--border-color);
            padding: 4px 10px;
            font-size: 12px;
            border-radius: 6px;
            color: #334155;
        }}

        .timestamp {{
            font-size: 12px;
            color: var(--text-muted);
            background-color: #f1f5f9;
            padding: 6px 12px;
            border-radius: 20px;
            font-weight: 600;
        }}

        /* Metrics grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 32px;
        }}

        .metric-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}

        .metric-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
        }}

        .metric-title {{
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            font-weight: 700;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}

        .metric-value {{
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.03em;
            margin-bottom: 4px;
        }}

        .metric-card.primary {{ border-top: 4px solid var(--primary); }}
        .metric-card.success {{ border-top: 4px solid var(--success); }}
        .metric-card.danger {{ border-top: 4px solid var(--danger); }}
        .metric-card.accent {{ border-top: 4px solid var(--accent); }}

        /* Charts section */
        .charts-container {{
            display: flex;
            flex-direction: column;
            gap: 24px;
            margin-bottom: 32px;
        }}

        .chart-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            text-align: center;
        }}

        .chart-card img {{
            max-width: 100%;
            height: auto;
            border-radius: 8px;
        }}

        /* Table */
        .table-card {{
            background-color: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 24px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            overflow-x: auto;
        }}

        .table-card h2 {{
            margin-top: 0;
            margin-bottom: 20px;
            font-size: 18px;
            font-weight: 700;
            color: var(--text-main);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}

        th {{
            background-color: #f1f5f9;
            color: #475569;
            font-weight: 700;
            text-align: left;
            padding: 12px 16px;
            border-bottom: 2px solid var(--border-color);
        }}

        td {{
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-color);
            color: #334155;
        }}

        tr:hover td {{
            background-color: #f8fafc;
        }}

        .direction-badge {{
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
        }}

        .direction-long {{
            background-color: var(--success-light);
            color: #065f46;
        }}

        .direction-short {{
            background-color: var(--danger-light);
            color: #991b1b;
        }}

        .pnl-positive {{
            color: #047857;
            font-weight: 600;
        }}

        .pnl-negative {{
            color: #b91c1c;
            font-weight: 600;
        }}
        
        @media (max-width: 768px) {{
            header {{
                flex-direction: column;
                align-items: flex-start;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="header-title">
                <h1>{strategy_name} Backtest Report</h1>
                <div class="strategy-info">Initial Capital: {initial_equity_str} | Final Capital: {final_equity_str}</div>
                <div class="params-list">
                    {params_html}
                </div>
            </div>
            <div class="timestamp">
                Run Date: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            </div>
        </header>

        <!-- Metric Grid -->
        <div class="metrics-grid">
            <div class="metric-card success">
                <div class="metric-title">Total Return</div>
                <div class="metric-value" style="color: var(--success);">{tot_return_str}</div>
            </div>
            <div class="metric-card primary">
                <div class="metric-title">CAGR</div>
                <div class="metric-value">{cagr_str}</div>
            </div>
            <div class="metric-card primary">
                <div class="metric-title">Sharpe Ratio</div>
                <div class="metric-value">{sharpe_str}</div>
            </div>
            <div class="metric-card primary">
                <div class="metric-title">Sortino Ratio</div>
                <div class="metric-value">{sortino_str}</div>
            </div>
            <div class="metric-card danger">
                <div class="metric-title">Max Drawdown</div>
                <div class="metric-value" style="color: var(--danger);">{mdd_str}</div>
            </div>
            <div class="metric-card accent">
                <div class="metric-title">Win Rate</div>
                <div class="metric-value">{win_rate_str}</div>
            </div>
            <div class="metric-card accent">
                <div class="metric-title">Profit Factor</div>
                <div class="metric-value">{pf_str}</div>
            </div>
            <div class="metric-card accent">
                <div class="metric-title">Total Trades</div>
                <div class="metric-value">{total_trades_str}</div>
            </div>
        </div>

        <!-- Diagnostic Charts -->
        <div class="charts-container">
            <div class="chart-card">
                <img src="{equity_b64}" alt="Equity Curve vs. Benchmark">
            </div>
            <div class="chart-card">
                <img src="{drawdown_b64}" alt="Drawdown Profile">
            </div>
            <div class="chart-card">
                <img src="{rolling_b64}" alt="Rolling Returns Comparison">
            </div>
        </div>

        <!-- Trades Log -->
        <div class="table-card">
            <h2>Executed Trades Log (Last 100 Trades)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Direction</th>
                        <th>Size</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>PnL ($)</th>
                        <th>PnL (%)</th>
                        <th>Duration (Days)</th>
                    </tr>
                </thead>
                <tbody>
                    {trades_table_body}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path

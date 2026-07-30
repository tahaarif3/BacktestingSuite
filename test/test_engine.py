import pytest
import pandas as pd
from datetime import datetime
from domain.models import Bar
from backtest.position_sizing import (
    ATRPercentRiskSizer,
    FixedSharesSizer,
    FixedFractionalSizer,
    VolatilityBasedSizer,
)
from backtest.execution import ExecutionModel
from backtest.portfolio import Portfolio

def test_fixed_shares_sizer_single():
    sizer = FixedSharesSizer(fixed_shares=50)
    bar = Bar(datetime(2020, 1, 1), 100.0, 100.0, 100.0, 100.0, 1000)
    assert sizer.size_position(signal=1.0, price=100.0, current_equity=100000.0, current_bar=bar) == 50.0
    assert sizer.size_position(signal=-1.0, price=100.0, current_equity=100000.0, current_bar=bar) == -50.0
    assert sizer.size_position(signal=0.0, price=100.0, current_equity=100000.0, current_bar=bar) == 0.0

def test_fixed_fractional_sizer_single():
    # Allocating 25% of equity (100k) = 25k. Price is 100. Shares = 250.
    sizer = FixedFractionalSizer(fraction=0.25, initial_capital=100000.0)
    bar = Bar(datetime(2020, 1, 1), 100.0, 100.0, 100.0, 100.0, 1000)
    assert sizer.size_position(signal=1.0, price=100.0, current_equity=100000.0, current_bar=bar) == 250.0
    assert sizer.size_position(signal=0.0, price=100.0, current_equity=100000.0, current_bar=bar) == 0.0

def test_volatility_based_sizer_single():
    sizer = VolatilityBasedSizer(target_risk_per_trade=1000.0, window=10)
    bar = Bar(datetime(2020, 1, 1), 100.0, 105.0, 95.0, 100.0, 1000) # ATR/true range is 10.0
    
    # We populate history
    for i in range(15):
        sizer._history.append(Bar(datetime(2020, 1, 1), 100.0, 105.0, 95.0, 100.0, 1000))
        
    shares = sizer.size_position(signal=1.0, price=100.0, current_equity=100000.0, current_bar=bar)
    # Expected ATR estimate is close to 10.0.
    # Risk per share = 10.0. Shares = 1000 / 10 = 100.
    assert pytest.approx(shares, abs=5.0) == 100.0


def test_atr_percent_risk_sizer_latches_entry_size():
    sizer = ATRPercentRiskSizer(
        risk_fraction=0.005, window=14, stop_multiple=2.0
    )
    start = pd.Timestamp("2020-01-01")
    for i in range(15):
        bar = Bar(
            start + pd.Timedelta(days=i),
            100.0,
            105.0,
            95.0,
            100.0,
            1000,
        )
        signal = 1.0 if i == 14 else 0.0
        shares = sizer.size_position(
            signal, 100.0, 100000.0, bar
        )

    # $500 risk / ($10 ATR * 2) = 25 shares.
    assert shares == pytest.approx(25.0)
    next_bar = Bar(
        start + pd.Timedelta(days=15),
        100.0,
        120.0,
        80.0,
        100.0,
        1000,
    )
    assert sizer.size_position(
        1.0, 100.0, 100000.0, next_bar
    ) == pytest.approx(25.0)

def test_execution_model_costs():
    # 1% slippage, $0.1 absolute slippage
    # 0.2% commission, $0.05 per share commission, $1.0 min commission
    exec_model = ExecutionModel(
        slippage_pct=0.01,
        slippage_abs=0.1,
        commission_pct=0.002,
        commission_per_share=0.05,
        min_commission=1.0
    )
    
    # Buy 100 shares at price 100
    slippage = exec_model.calculate_slippage(price=100.0, shares=100.0)
    # slippage = 100 * (0.1 + 100 * 0.01) = 100 * 1.1 = 110.0
    assert pytest.approx(slippage, abs=1e-4) == 110.0
    
    commission = exec_model.calculate_commission(price=100.0, shares=100.0)
    # commission = 100 * (0.05 + 100 * 0.002) = 100 * 0.25 = 25.0
    assert pytest.approx(commission, abs=1e-4) == 25.0
    
    # Min commission triggers on small trade
    commission_small = exec_model.calculate_commission(price=100.0, shares=1.0)
    # commission = 1 * (0.05 + 100 * 0.002) = 0.25 -> triggers min of 1.0
    assert pytest.approx(commission_small, abs=1e-4) == 1.0

def test_portfolio_properties():
    bars = [
        Bar(datetime(2020, 1, 1), 100.0, 100.0, 100.0, 100.0, 1000),
        Bar(datetime(2020, 1, 2), 101.0, 101.0, 101.0, 101.0, 1000)
    ]
    portfolio = Portfolio(
        data=bars,
        cash=[100000.0, 101000.0],
        positions=[0.0, 0.0],
        equity_curve=[100000.0, 101000.0],
        trades=[0.0, 0.0],
        slippage_cost=[0.0, 0.0],
        commission_cost=[0.0, 0.0],
        target_positions=[0.0, 0.0],
        signals=[0.0, 0.0]
    )
    
    assert portfolio.total_return == pytest.approx(0.01)
    assert portfolio.annualized_return > 0.0

    assert portfolio.max_drawdown == 0.0
    assert len(portfolio.daily_returns) == 2

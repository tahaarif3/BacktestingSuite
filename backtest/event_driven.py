from typing import List
from domain.interfaces import IStrategy, IPositionSizer, IExecutionModel
from domain.models import Bar
from backtest.portfolio import Portfolio


class EventDrivenEngine:
    """
    Chronological event-driven backtesting engine that simulates realistic bar-by-bar
    portfolio dynamics, execution costs, and dynamic position sizing.
    Conforms to Clean Architecture principles.
    """

    def __init__(
        self,
        strategy: IStrategy,
        position_sizer: IPositionSizer,
        execution_model: IExecutionModel,
        initial_capital: float = 100000.0,
        execution_timing: str = "next_open",
        min_trade_shares: float = 1e-8
    ):
        """
        Args:
            strategy: Strategy conforming to IStrategy.
            position_sizer: Sizer conforming to IPositionSizer.
            execution_model: Cost calculator conforming to IExecutionModel.
            initial_capital: Starting cash balance.
            execution_timing: "next_open" to trade at the next bar's Open,
                              "next_close" to trade at the next bar's Close.
            min_trade_shares: Minimum change in position shares required to execute a trade.
        """
        self.strategy = strategy
        self.position_sizer = position_sizer
        self.execution_model = execution_model
        self.initial_capital = initial_capital
        self.min_trade_shares = min_trade_shares
        
        if execution_timing not in ("next_open", "next_close"):
            raise ValueError("execution_timing must be either 'next_open' or 'next_close'.")
        self.execution_timing = execution_timing

    def run(self, data: List[Bar], signals: List[float] = None) -> Portfolio:
        """
        Executes the backtest chronologically bar-by-bar (simulating event loops).
        
        Args:
            data: List of clean domain Bar objects.
            signals: Optional list of pre-calculated signals. If None, strategy will generate them.
            
        Returns:
            Portfolio: Portfolio instance containing the backtest results.
        """
        if not data:
            raise ValueError("Cannot run backtest on empty data.")

        # 1. Generate signals using the strategy if not provided
        if signals is None:
            signals = self.strategy.generate_signals(data)

        if len(signals) != len(data):
            raise ValueError("Strategy signals length does not match data length.")

        n_rows = len(data)
        
        # Lists to record results
        target_positions = [0.0] * n_rows
        active_positions = [0.0] * n_rows
        trades_list = [0.0] * n_rows
        slippage_costs = [0.0] * n_rows
        commission_costs = [0.0] * n_rows
        cash_list = [self.initial_capital] * n_rows
        holdings_list = [0.0] * n_rows
        equity_list = [self.initial_capital] * n_rows

        # Initial state
        cash = self.initial_capital
        position = 0.0  # active shares held

        # Chronological execution loop (Event loop)
        for t in range(n_rows):
            if t == 0:
                # Day 0: Record initial state (cannot execute trades since no signal from t-1 exists)
                cash_list[0] = cash
                active_positions[0] = position
                holdings_list[0] = 0.0
                equity_list[0] = cash
                continue

            # State from the previous bar (end of t-1)
            prev_signal = signals[t - 1]
            prev_bar = data[t - 1]
            prev_close = prev_bar.close
            prev_equity = equity_list[t - 1]

            # 3. Dynamic Position Sizing (no look-ahead)
            # Size position using information available at the close of day t-1
            target_shares = self.position_sizer.size_position(
                signal=prev_signal,
                price=prev_close,
                current_equity=prev_equity,
                current_bar=prev_bar
            )
            target_positions[t] = target_shares

            # 4. Order Execution & Slippage/Commissions
            # Calculate trade shares (changes in active position)
            trade_shares = target_shares - position

            # Enforce minimum trade shares threshold
            if abs(trade_shares) < self.min_trade_shares:
                trade_shares = 0.0
                target_shares = position

            # Determine execution price based on timing configuration
            current_bar = data[t]
            if self.execution_timing == "next_open":
                exec_price = current_bar.open
            else:
                exec_price = current_bar.close

            # Calculate transaction costs using ExecutionModel
            if abs(trade_shares) > 1e-8:
                slippage = self.execution_model.calculate_slippage(exec_price, trade_shares)
                commission = self.execution_model.calculate_commission(exec_price, trade_shares)
            else:
                slippage = 0.0
                commission = 0.0

            transaction_cost = slippage + commission

            # 5. Update Portfolio Cash Account
            cash = cash - (trade_shares * exec_price) - transaction_cost
            position = target_shares

            # 6. Mark to Market portfolio value
            current_close = current_bar.close
            holdings = position * current_close
            equity = cash + holdings

            # Record state
            active_positions[t] = position
            trades_list[t] = trade_shares
            slippage_costs[t] = slippage
            commission_costs[t] = commission
            cash_list[t] = cash
            holdings_list[t] = holdings
            equity_list[t] = equity

        return Portfolio(
            data=data,
            cash=cash_list,
            positions=active_positions,
            equity_curve=equity_list,
            trades=trades_list,
            slippage_cost=slippage_costs,
            commission_cost=commission_costs,
            target_positions=target_positions,
            signals=signals
        )

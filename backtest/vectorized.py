import pandas as pd
from strat.base import BaseStrategy
from backtest.position_sizing import BasePositionSizer
from backtest.execution import ExecutionModel
from backtest.portfolio import Portfolio


class VectorizedEngine:
    """
    Core backtesting engine that simulates trading portfolios vectorially using Pandas/NumPy.
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        position_sizer: BasePositionSizer,
        execution_model: ExecutionModel,
        initial_capital: float = 100000.0
    ):
        """
        Args:
            strategy: The trading strategy instance defining generate_signals.
            position_sizer: The position sizing model to translate signals to shares.
            execution_model: The transaction cost model (slippage & commission).
            initial_capital: Initial portfolio cash allocation.
        """
        self.strategy = strategy
        self.position_sizer = position_sizer
        self.execution_model = execution_model
        self.initial_capital = initial_capital

    def run(self, data: pd.DataFrame) -> Portfolio:
        """
        Orchestrates and executes the vectorized backtest on the input DataFrame.
        
        Args:
            data: DataFrame containing historical market data (OHLCV).
            
        Returns:
            Portfolio: Portfolio instance representing the results of the backtest.
        """
        if data.empty:
            raise ValueError("Cannot run backtest on empty data.")
        if "close" not in data.columns:
            raise ValueError("Input data must contain a 'close' price column.")

        # Copy data to avoid side-effects on original DataFrame
        df = data.copy()

        # 1. Generate signals using the strategy
        df = self.strategy.generate_signals(df)

        # Double check signal column is present
        if "signal" not in df.columns:
            raise ValueError("Strategy failed to generate a 'signal' column.")

        prices = df["close"]

        # 2. Determine target position sizes (shares) based on signals
        target_positions = self.position_sizer.size_positions(df)

        # 3. Shift target positions by 1 to prevent Look-Ahead Bias
        # (A signal at day T is executed at the close/open of T+1)
        active_positions = target_positions.shift(1).fillna(0.0)

        # 4. Calculate daily changes in position (Turnover)
        # First day trades from 0 to the initial active position
        first_position = active_positions.iloc[0] if not active_positions.empty else 0.0
        trades = active_positions.diff().fillna(first_position)

        # 5. Apply ExecutionModel to compute slippage and commission costs
        slippage_cost = self.execution_model.calculate_slippage(prices, trades)
        commission_cost = self.execution_model.calculate_commission(prices, trades)
        total_transaction_cost = slippage_cost + commission_cost

        # 6. Calculate daily cash flow and cash balance
        # Buying shares (-trades * price) decreases cash; selling (+trades * price) increases cash
        cash_flow = -(trades * prices) - total_transaction_cost
        cash = self.initial_capital + cash_flow.cumsum()

        # 7. Compute daily holdings value (active shares * current price)
        holdings = active_positions * prices

        # 8. Compute daily marked-to-market portfolio equity (cash + holdings)
        equity = cash + holdings

        # Populate dataframe with simulation results for inspection
        df["target_position"] = target_positions
        df["active_position"] = active_positions
        df["trades"] = trades
        df["slippage_cost"] = slippage_cost
        df["commission_cost"] = commission_cost
        df["cash"] = cash
        df["holdings"] = holdings
        df["equity"] = equity

        return Portfolio(
            data=df,
            cash=cash,
            positions=active_positions,
            equity_curve=equity
        )

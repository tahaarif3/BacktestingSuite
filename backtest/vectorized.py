# ==============================================================================
# DEPRECATED/INACTIVE: VectorizedEngine (Commented out for reference)
# ==============================================================================
# import pandas as pd
# from strat.base import BaseStrategy
# from backtest.position_sizing import BasePositionSizer
# from backtest.execution import ExecutionModel
# from backtest.portfolio import Portfolio
# 
# class VectorizedEngine:
#     """
#     Core backtesting engine that simulates trading portfolios vectorially using Pandas/NumPy.
#     """
#     def __init__(
#         self,
#         strategy: BaseStrategy,
#         position_sizer: BasePositionSizer,
#         execution_model: ExecutionModel,
#         initial_capital: float = 100000.0
#     ):
#         self.strategy = strategy
#         self.position_sizer = position_sizer
#         self.execution_model = execution_model
#         self.initial_capital = initial_capital
# 
#     def run(self, data: pd.DataFrame) -> Portfolio:
#         if data.empty:
#             raise ValueError("Cannot run backtest on empty data.")
#         if "close" not in data.columns:
#             raise ValueError("Input data must contain a 'close' price column.")
# 
#         df = data.copy()
#         df = self.strategy.generate_signals(df)
#         if "signal" not in df.columns:
#             raise ValueError("Strategy failed to generate a 'signal' column.")
# 
#         prices = df["close"]
#         target_positions = self.position_sizer.size_positions(df)
#         active_positions = target_positions.shift(1).fillna(0.0)
#         first_position = active_positions.iloc[0] if not active_positions.empty else 0.0
#         trades = active_positions.diff().fillna(first_position)
# 
#         slippage_cost = self.execution_model.calculate_slippage(prices, trades)
#         commission_cost = self.execution_model.calculate_commission(prices, trades)
#         total_transaction_cost = slippage_cost + commission_cost
# 
#         cash_flow = -(trades * prices) - total_transaction_cost
#         cash = self.initial_capital + cash_flow.cumsum()
#         holdings = active_positions * prices
#         equity = cash + holdings
# 
#         df["target_position"] = target_positions
#         df["active_position"] = active_positions
#         df["trades"] = trades
#         df["slippage_cost"] = slippage_cost
#         df["commission_cost"] = commission_cost
#         df["cash"] = cash
#         df["holdings"] = holdings
#         df["equity"] = equity
# 
#         return Portfolio(
#             data=df,
#             cash=cash,
#             positions=active_positions,
#             equity_curve=equity
#         )

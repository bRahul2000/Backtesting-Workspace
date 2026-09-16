"""Run a known 100/95/110 example without market data or a UI."""
from __future__ import annotations

import pandas as pd

from engine.backtester import run_backtest
from engine.models import Candle, Direction, Signal
from strategies.base import Strategy


class _OneSignal(Strategy):
    def reset(self) -> None:
        self.count = 0

    def on_candle(self, candle: Candle) -> Signal | None:
        self.count += 1
        return Signal(Direction.LONG, stop_loss=95, take_profit=110) if self.count == 1 else None


def run_known_example():
    """Expected: next-open entry 100, quantity 20, net PnL 200, final 10200."""
    data = pd.DataFrame([
        {"timestamp": "2025-01-01T00:00:00Z", "open": 100, "high": 101,
         "low": 99, "close": 100, "volume": 1},
        {"timestamp": "2025-01-01T00:15:00Z", "open": 100, "high": 111,
         "low": 99, "close": 105, "volume": 1},
    ])
    return run_backtest(data, _OneSignal())


if __name__ == "__main__":
    result = run_known_example()
    trade = result.trades[0]
    print(f"Entry {trade.entry_price}, stop {trade.stop_loss}, target {trade.take_profit}")
    print(f"Quantity {trade.quantity}, net PnL {trade.pnl}, balance {result.final_balance}")

"""Performance statistics computed only from completed, net-of-cost trades."""
from __future__ import annotations

from dataclasses import dataclass
from math import inf

from engine.models import BacktestResult


@dataclass(frozen=True)
class PerformanceMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    total_return_percent: float
    profit_factor: float | None
    average_trade: float
    average_winner: float
    average_loser: float
    largest_winner: float
    largest_loser: float
    average_r_multiple: float
    expectancy_dollars: float
    expectancy_r: float
    max_drawdown_dollars: float
    max_drawdown_percent: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    average_bars_held: float
    final_balance: float
    average_planned_risk: float
    average_realized_losing_r: float
    largest_losing_r: float


def calculate_metrics(result: BacktestResult) -> PerformanceMetrics:
    trades = result.trades
    winners = [trade for trade in trades if trade.pnl > 1e-9]
    losers = [trade for trade in trades if trade.pnl < -1e-9]
    gross_profit = sum(trade.pnl for trade in winners)
    gross_loss = sum(trade.pnl for trade in losers)
    count = len(trades)
    net = sum(trade.pnl for trade in trades)
    streak_wins = streak_losses = max_wins = max_losses = 0
    for trade in trades:
        if trade.pnl > 1e-9:
            streak_wins += 1
            streak_losses = 0
        elif trade.pnl < -1e-9:
            streak_losses += 1
            streak_wins = 0
        else:
            streak_wins = streak_losses = 0
        max_wins = max(max_wins, streak_wins)
        max_losses = max(max_losses, streak_losses)
    return PerformanceMetrics(
        total_trades=count,
        winning_trades=len(winners),
        losing_trades=len(losers),
        breakeven_trades=count - len(winners) - len(losers),
        win_rate_percent=len(winners) / count * 100 if count else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=net,
        total_return_percent=net / result.settings.starting_balance * 100,
        profit_factor=(gross_profit / abs(gross_loss) if losers else
                       inf if winners else None),
        average_trade=net / count if count else 0.0,
        average_winner=gross_profit / len(winners) if winners else 0.0,
        average_loser=gross_loss / len(losers) if losers else 0.0,
        largest_winner=max((trade.pnl for trade in winners), default=0.0),
        largest_loser=min((trade.pnl for trade in losers), default=0.0),
        average_r_multiple=sum(trade.r_multiple for trade in trades) / count if count else 0.0,
        expectancy_dollars=net / count if count else 0.0,
        expectancy_r=sum(trade.r_multiple for trade in trades) / count if count else 0.0,
        max_drawdown_dollars=max(point.drawdown_dollars for point in result.equity_curve),
        max_drawdown_percent=max(point.drawdown_percent for point in result.equity_curve),
        max_consecutive_wins=max_wins,
        max_consecutive_losses=max_losses,
        average_bars_held=sum(trade.bars_held for trade in trades) / count if count else 0.0,
        final_balance=result.final_balance,
        average_planned_risk=sum(trade.planned_risk for trade in trades) / count if count else 0.0,
        average_realized_losing_r=(sum(trade.realized_r for trade in losers) / len(losers)
                                   if losers else 0.0),
        largest_losing_r=min((trade.realized_r for trade in losers), default=0.0),
    )

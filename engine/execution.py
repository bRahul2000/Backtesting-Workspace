"""Fill rules and position sizing.

Commission is charged on entry and exit notional. Slippage worsens both fills:
long entry/short exit increase; short entry/long exit decrease. The default
quantity uses estimated loss per unit at a normal stop fill, including costs.
The legacy price-distance quantity remains selectable. Adverse opening gaps
can exceed the planned risk under either calculation.
An opening gap through a stop fills at the open; a gap beyond a target fills at
the target (conservative). For ambiguous intrabar touches, the setting decides.
"""
from __future__ import annotations

import math

from engine.models import (
    BacktestSettings, Candle, Direction, Position, RiskCalculation, RiskMode, SameBarResolution,
    Signal, Trade,
)


def validate_settings(settings: BacktestSettings) -> None:
    values = (
        settings.starting_balance, settings.risk_percent,
        settings.fixed_risk_dollars, settings.risk_reward_ratio,
        settings.commission_percent, settings.slippage_percent,
        settings.max_leverage, settings.min_quantity,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Backtest settings must be finite numbers.")
    if settings.starting_balance <= 0 or settings.risk_reward_ratio <= 0:
        raise ValueError("Starting balance and risk/reward ratio must be positive.")
    if settings.risk_percent <= 0 or settings.fixed_risk_dollars <= 0:
        raise ValueError("Risk amount and risk percentage must be positive.")
    if not 0 <= settings.commission_percent < 100 or not 0 <= settings.slippage_percent < 100:
        raise ValueError("Commission and slippage percentages must be between 0 and 100.")
    if settings.max_leverage <= 0 or settings.min_quantity < 0:
        raise ValueError("Maximum leverage must be positive and minimum quantity nonnegative.")
    if not isinstance(settings.risk_mode, RiskMode) or not isinstance(settings.same_bar_resolution, SameBarResolution):
        raise ValueError("Unknown risk mode or same-bar resolution.")
    if not isinstance(settings.risk_calculation, RiskCalculation):
        raise ValueError("Unknown risk calculation mode.")


def slipped_price(price: float, direction: Direction, entry: bool, percent: float) -> float:
    sign = 1 if (direction is Direction.LONG) == entry else -1
    return price * (1 + sign * percent / 100)


def estimated_stop_loss_per_unit(entry: float, stop: float, direction: Direction,
                                 settings: BacktestSettings) -> float:
    """Net loss per unit at the stop, assuming no opening gap through it."""
    stop_fill = slipped_price(stop, direction, False, settings.slippage_percent)
    price_loss = entry - stop_fill if direction is Direction.LONG else stop_fill - entry
    commissions = (entry + stop_fill) * settings.commission_percent / 100
    return price_loss + commissions


def open_position(
    signal: Signal, signal_time, entry_time, open_price: float, bar_index: int,
    trade_id: int, balance: float, settings: BacktestSettings,
) -> Position:
    if not isinstance(signal.direction, Direction):
        raise ValueError("Signal direction must be LONG or SHORT.")
    entry = slipped_price(open_price, signal.direction, True, settings.slippage_percent)
    stop = float(signal.stop_loss)
    target = signal.take_profit
    if not all(math.isfinite(value) and value > 0 for value in (entry, stop)):
        raise ValueError("Entry and stop must be finite positive prices.")
    if signal.direction is Direction.LONG and stop >= entry:
        raise ValueError("LONG stop must be below the next candle's slipped entry.")
    if signal.direction is Direction.SHORT and stop <= entry:
        raise ValueError("SHORT stop must be above the next candle's slipped entry.")
    distance = abs(entry - stop)
    budget = (balance * settings.risk_percent / 100
              if settings.risk_mode is RiskMode.PERCENT_EQUITY
              else settings.fixed_risk_dollars)
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("No positive equity or risk budget is available for entry.")
    loss_per_unit = estimated_stop_loss_per_unit(entry, stop, signal.direction, settings)
    if not math.isfinite(loss_per_unit) or loss_per_unit <= 0:
        raise ValueError("Estimated stop loss per unit is invalid.")
    sizing_distance = (distance if settings.risk_calculation is RiskCalculation.PRICE_DISTANCE
                       else loss_per_unit)
    quantity = budget / sizing_distance
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Calculated position quantity is invalid.")
    maximum_exposure = balance * settings.max_leverage
    if not math.isfinite(maximum_exposure) or maximum_exposure <= 0:
        raise ValueError("No positive notional exposure is available for entry.")
    max_quantity = maximum_exposure / entry
    leverage_capped = quantity > max_quantity
    if leverage_capped:
        quantity = max_quantity
    if not math.isfinite(quantity) or quantity <= 0:
        raise ValueError("Leverage limit leaves no positive position quantity.")
    if settings.min_quantity and quantity < settings.min_quantity:
        raise ValueError(
            f"Quantity {quantity:.8g} is below the configured minimum {settings.min_quantity:.8g}."
        )
    if target is None:
        target = entry + distance * settings.risk_reward_ratio * (1 if signal.direction is Direction.LONG else -1)
    target = float(target)
    if not math.isfinite(target) or target <= 0:
        raise ValueError("Take profit must be a finite positive price.")
    if signal.direction is Direction.LONG and target <= entry:
        raise ValueError("LONG target must be above entry.")
    if signal.direction is Direction.SHORT and target >= entry:
        raise ValueError("SHORT target must be below entry.")
    return Position(
        trade_id, signal.direction, signal_time, entry_time, entry,
        stop, target, quantity, budget, entry * quantity * settings.commission_percent / 100,
        bar_index, quantity * loss_per_unit, leverage_capped,
    )


def exit_decision(position: Position, candle: Candle, setting: SameBarResolution) -> tuple[float, str] | None:
    if position.direction is Direction.LONG:
        if candle.open <= position.stop_loss:
            return candle.open, "Stop loss (opening gap)"
        if candle.open >= position.take_profit:
            return position.take_profit, "Take profit (opening gap)"
        stop_hit = candle.low <= position.stop_loss
        target_hit = candle.high >= position.take_profit
    else:
        if candle.open >= position.stop_loss:
            return candle.open, "Stop loss (opening gap)"
        if candle.open <= position.take_profit:
            return position.take_profit, "Take profit (opening gap)"
        stop_hit = candle.high >= position.stop_loss
        target_hit = candle.low <= position.take_profit
    if stop_hit and target_hit:
        if setting is SameBarResolution.TP_FIRST:
            return position.take_profit, "Take profit (ambiguous bar, TP First)"
        return position.stop_loss, "Stop loss (ambiguous bar, SL First)"
    if stop_hit:
        return position.stop_loss, "Stop loss"
    if target_hit:
        return position.take_profit, "Take profit"
    return None


def close_position(position: Position, candle: Candle, bar_index: int,
                   raw_exit_price: float, reason: str, settings: BacktestSettings) -> Trade:
    exit_price = slipped_price(raw_exit_price, position.direction, False, settings.slippage_percent)
    exit_commission = exit_price * position.quantity * settings.commission_percent / 100
    direction_sign = 1 if position.direction is Direction.LONG else -1
    gross = direction_sign * (exit_price - position.entry_price) * position.quantity
    net = gross - position.entry_commission - exit_commission
    return Trade(
        position.trade_id, position.direction, position.signal_time, position.entry_time,
        position.entry_price, position.stop_loss, position.take_profit, candle.timestamp,
        exit_price, reason, position.quantity, position.initial_risk, net,
        net / (position.entry_price * position.quantity) * 100,
        net / position.initial_risk, bar_index - position.entry_bar_index + 1,
        position.entry_commission, exit_commission,
        position.estimated_stop_loss, position.leverage_capped,
    )

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

import pandas as pd

from engine.models import (
    BacktestSettings, Candle, Direction, EntryModel, PendingOrder, Position,
    RiskCalculation, RiskMode, SameBarResolution, Signal, Trade,
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
        setup_id=signal.setup_id,
    )


def create_pending_order(
    signal: Signal, candle: Candle, bar_index: int, balance: float,
    settings: BacktestSettings,
) -> PendingOrder:
    """Fix quantity from the planned trigger before any later fill or gap."""
    if not isinstance(signal.direction, Direction):
        raise ValueError("Pending direction must be LONG or SHORT.")
    if isinstance(signal.pending_expiry_bars, bool) or not isinstance(signal.pending_expiry_bars, int) or signal.pending_expiry_bars < 1:
        raise ValueError("Pending expiry bars must be a positive integer.")
    if signal.take_profit is not None:
        raise ValueError("Pending stop targets are derived from the actual fill; omit an explicit take profit.")
    if signal.pending_entry_price is None:
        raise ValueError("Pending stop entry requires a trigger price.")
    trigger = float(signal.pending_entry_price)
    stop_value = signal.pending_stop_price if signal.pending_stop_price is not None else signal.stop_loss
    if stop_value is None:
        raise ValueError("Pending stop entry requires a structural stop price.")
    stop = float(stop_value)
    if signal.stop_loss is not None and signal.pending_stop_price is not None and float(signal.stop_loss) != stop:
        raise ValueError("Pending stop price conflicts with stop loss.")
    if not all(math.isfinite(value) and value > 0 for value in (trigger, stop)):
        raise ValueError("Pending trigger and stop must be finite positive prices.")
    if signal.direction is Direction.LONG and trigger <= candle.close:
        raise ValueError("LONG stop-entry trigger must be above the signal candle close.")
    if signal.direction is Direction.SHORT and trigger >= candle.close:
        raise ValueError("SHORT stop-entry trigger must be below the signal candle close.")
    signal_time = candle.timestamp + pd.Timedelta(minutes=15)
    planned_signal = Signal(signal.direction, stop_loss=stop, setup_id=signal.setup_id)
    planned = open_position(planned_signal, signal_time, signal_time, trigger,
                            bar_index, 0, balance, settings)
    return PendingOrder(
        direction=signal.direction, signal_time=signal_time,
        created_time=signal_time, trigger_price=trigger, stop_price=stop,
        expiry_time=candle.timestamp + pd.Timedelta(minutes=15 * signal.pending_expiry_bars),
        created_bar_index=bar_index,
        expiry_bar_index=bar_index + signal.pending_expiry_bars,
        quantity=planned.quantity, planned_risk=planned.initial_risk,
        estimated_stop_loss=planned.estimated_stop_loss,
        leverage_capped=planned.leverage_capped, setup_id=signal.setup_id,
    )


def fill_pending_order(order: PendingOrder, candle: Candle, bar_index: int,
                       trade_id: int, settings: BacktestSettings) -> Position | None:
    """Fill only when a later candle crosses the trigger; never resize."""
    if order.direction is Direction.LONG:
        if candle.high < order.trigger_price:
            return None
        base_fill = max(order.trigger_price, candle.open)
        gap = candle.open > order.trigger_price
    else:
        if candle.low > order.trigger_price:
            return None
        base_fill = min(order.trigger_price, candle.open)
        gap = candle.open < order.trigger_price
    entry = slipped_price(base_fill, order.direction, True, settings.slippage_percent)
    distance = (entry - order.stop_price if order.direction is Direction.LONG
                else order.stop_price - entry)
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("Actual pending fill has no positive risk distance to the structural stop.")
    target = entry + settings.risk_reward_ratio * distance * (1 if order.direction is Direction.LONG else -1)
    if not math.isfinite(target) or target <= 0:
        raise ValueError("Actual pending fill produces an invalid take profit.")
    return Position(
        trade_id, order.direction, order.signal_time, candle.timestamp, entry,
        order.stop_price, target, order.quantity, order.planned_risk,
        entry * order.quantity * settings.commission_percent / 100,
        bar_index, order.estimated_stop_loss, order.leverage_capped,
        entry_model=EntryModel.STOP_ENTRY_PENDING,
        pending_trigger_price=order.trigger_price,
        pending_created_time=order.created_time,
        pending_expiry_time=order.expiry_time,
        pending_expiry_bar_index=order.expiry_bar_index,
        gap_through_trigger=gap,
        entry_gap_amount=abs(base_fill - order.trigger_price),
        setup_id=order.setup_id,
    )


def exit_decision(position: Position, candle: Candle, setting: SameBarResolution,
                  *, entered_intrabar: bool = False) -> tuple[float, str] | None:
    if position.direction is Direction.LONG:
        if not entered_intrabar and candle.open <= position.stop_loss:
            return candle.open, "Stop loss (opening gap)"
        if not entered_intrabar and candle.open >= position.take_profit:
            return position.take_profit, "Take profit (opening gap)"
        stop_hit = candle.low <= position.stop_loss
        target_hit = candle.high >= position.take_profit
    else:
        if not entered_intrabar and candle.open >= position.stop_loss:
            return candle.open, "Stop loss (opening gap)"
        if not entered_intrabar and candle.open <= position.take_profit:
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
        position.entry_model, position.pending_trigger_price,
        position.pending_created_time, position.pending_expiry_time,
        position.pending_expiry_bar_index, position.gap_through_trigger,
        position.entry_gap_amount, position.setup_id,
    )

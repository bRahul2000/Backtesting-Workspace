from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from enum import Enum
import math

from brokers.base_broker import BrokerInstrumentProfile


class GoldDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class GoldQuoteBar:
    bid_open: float
    bid_high: float
    bid_low: float
    bid_close: float
    ask_open: float
    ask_high: float
    ask_low: float
    ask_close: float


def entry_price(bar: GoldQuoteBar, direction: GoldDirection) -> float:
    return bar.ask_open if direction is GoldDirection.LONG else bar.bid_open


def normalize_price(price: float, spec: BrokerInstrumentProfile) -> float:
    require_complete_spec(spec)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Price must be finite and positive.")
    digits = max(0, int(round(-math.log10(spec.point))))
    return round(price, digits)


def require_complete_spec(spec: BrokerInstrumentProfile) -> None:
    required = ("tick_size", "tick_value_loss", "contract_size", "minimum_volume",
                "volume_step", "maximum_volume", "point")
    missing = [name for name in required if getattr(spec, name) is None]
    if missing:
        raise ValueError("Gold broker specification is incomplete: " + ", ".join(missing))


def round_volume(volume: float, spec: BrokerInstrumentProfile) -> float:
    require_complete_spec(spec)
    if not math.isfinite(volume) or volume < 0:
        raise ValueError("Volume must be finite and nonnegative.")
    steps = (Decimal(str(volume)) / Decimal(str(spec.volume_step))).to_integral_value(rounding=ROUND_DOWN)
    rounded = float(steps * Decimal(str(spec.volume_step)))
    if rounded < spec.minimum_volume:
        return 0.0
    return min(rounded, spec.maximum_volume)


def validate_stop_distance(entry: float, stop: float, direction: GoldDirection,
                           spec: BrokerInstrumentProfile) -> None:
    require_complete_spec(spec)
    distance = abs(entry - stop)
    if distance < spec.stops_level * spec.point:
        raise ValueError("Stop distance is below the broker stops level.")
    if direction is GoldDirection.LONG and stop >= entry:
        raise ValueError("Long stop must be below entry.")
    if direction is GoldDirection.SHORT and stop <= entry:
        raise ValueError("Short stop must be above entry.")


def loss_per_lot(entry: float, stop: float, direction: GoldDirection,
                 spec: BrokerInstrumentProfile, *, spread: float = 0.0,
                 commission_per_lot: float = 0.0) -> float:
    require_complete_spec(spec)
    if spread < 0 or commission_per_lot < 0:
        raise ValueError("Spread and commission must be nonnegative.")
    validate_stop_distance(entry, stop, direction, spec)
    price_distance = abs(entry - stop) + spread
    ticks = price_distance / spec.tick_size
    return ticks * spec.tick_value_loss + commission_per_lot


def pnl_from_prices(entry: float, exit: float, direction: GoldDirection,
                    lots: float, spec: BrokerInstrumentProfile) -> float:
    require_complete_spec(spec)
    if lots <= 0:
        raise ValueError("Lots must be positive.")
    price_change = (exit - entry) if direction is GoldDirection.LONG else (entry - exit)
    return price_change / spec.tick_size * spec.tick_value_loss * lots


def margin_required(lots: float, margin_per_lot: float) -> float:
    if lots <= 0 or margin_per_lot <= 0:
        raise ValueError("Lots and margin per lot must be positive.")
    return lots * margin_per_lot


def calculate_lot_size(equity: float, risk_percent: float, entry: float, stop: float,
                       direction: GoldDirection, spec: BrokerInstrumentProfile, *,
                       spread: float = 0.0, commission_per_lot: float = 0.0,
                       margin_per_lot: float | None = None) -> float:
    budget = equity * risk_percent / 100
    if budget <= 0 or not math.isfinite(budget):
        raise ValueError("Equity and risk percentage must produce a positive budget.")
    raw = budget / loss_per_lot(entry, stop, direction, spec, spread=spread,
                                commission_per_lot=commission_per_lot)
    if margin_per_lot is not None:
        if margin_per_lot <= 0:
            raise ValueError("Margin per lot must be positive.")
        raw = min(raw, equity / margin_per_lot)
    lots = round_volume(raw, spec)
    if lots == 0:
        raise ValueError("Risk budget produces less than the minimum volume.")
    return lots


def exit_price(bar: GoldQuoteBar, direction: GoldDirection, stop: float, target: float,
               *, stop_first: bool = True) -> tuple[float, str] | None:
    if direction is GoldDirection.LONG:
        stop_hit, target_hit = bar.bid_low <= stop, bar.bid_high >= target
    else:
        stop_hit, target_hit = bar.ask_high >= stop, bar.ask_low <= target
    if stop_hit and target_hit:
        return (stop, "stop") if stop_first else (target, "target")
    if stop_hit:
        return stop, "stop"
    if target_hit:
        return target, "target"
    return None
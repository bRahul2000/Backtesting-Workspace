from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InstrumentProfile:
    instrument_id: str
    symbol: str
    broker_symbol: str | None
    asset_class: str
    price_precision: int | None
    tick_size: float | None
    tick_value: float | None
    contract_size: float | None
    minimum_volume: float | None
    volume_step: float | None
    maximum_volume: float | None
    trading_hours: str | None
    weekend_behavior: str | None
    leverage_rule: str | None
    margin_rule: str | None
    spread_model: str | None
    commission_model: str | None
    swap_model: str | None
    notes: tuple[str, ...] = ()
    point: float | None = None
    tick_value_profit: float | None = None
    tick_value_loss: float | None = None
    stops_level: int | None = None
    freeze_level: int | None = None
    margin_calculation_mode: str | None = None
    margin_initial: float | None = None
    margin_maintenance: float | None = None
    swap_long: float | None = None
    swap_short: float | None = None
    swap_mode: str | None = None
    trading_sessions: tuple[str, ...] = ()
    broker_profile_id: str | None = None
    captured_at_utc: str | None = None
    source: str | None = None

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(
            field for field in (
                "price_precision", "tick_size", "tick_value", "contract_size",
                "minimum_volume", "volume_step", "maximum_volume", "trading_hours",
                "weekend_behavior", "leverage_rule", "margin_rule", "spread_model",
                "commission_model", "swap_model",
                "point", "tick_value_profit", "tick_value_loss", "stops_level",
                "freeze_level", "margin_calculation_mode", "margin_initial",
                "margin_maintenance", "swap_long", "swap_short", "swap_mode",
            )
            if getattr(self, field) is None
        )

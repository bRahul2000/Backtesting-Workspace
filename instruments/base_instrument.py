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

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        return tuple(
            field for field in (
                "price_precision", "tick_size", "tick_value", "contract_size",
                "minimum_volume", "volume_step", "maximum_volume", "trading_hours",
                "weekend_behavior", "leverage_rule", "margin_rule", "spread_model",
                "commission_model", "swap_model",
            )
            if getattr(self, field) is None
        )

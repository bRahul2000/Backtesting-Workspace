from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Any


@dataclass(frozen=True)
class BrokerInstrumentProfile:
    instrument_id: str
    broker_symbol: str
    spread_model: str | None = None
    default_spread_price: float | None = None
    commission_model: str | None = None
    commission_value: float | None = None
    slippage_model: str | None = None
    contract_size: float | None = None
    tick_size: float | None = None
    tick_value: float | None = None
    minimum_volume: float | None = None
    volume_step: float | None = None
    maximum_volume: float | None = None
    leverage: float | None = None
    margin_rule: str | None = None
    swap_rule: str | None = None
    known: bool = True
    notes: tuple[str, ...] = ()
    price_precision: int | None = None
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
    description: str | None = None
    capture_timestamp_utc: str | None = None
    source: str | None = None


@dataclass(frozen=True)
class BrokerProfile:
    broker_id: str
    name: str
    account_type: str
    instruments: dict[str, BrokerInstrumentProfile] = field(default_factory=dict)

    def instrument(self, instrument_id: str) -> BrokerInstrumentProfile:
        try:
            return self.instruments[instrument_id]
        except KeyError as exc:
            raise KeyError(f"Broker {self.broker_id} has no profile for {instrument_id}.") from exc

    def fingerprint(self) -> str:
        payload = json.dumps(self, default=lambda obj: obj.__dict__, sort_keys=True)
        return sha256(payload.encode("utf-8")).hexdigest()

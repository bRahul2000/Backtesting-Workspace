from __future__ import annotations

import json
from pathlib import Path

from instruments.base_instrument import InstrumentProfile

XAUUSD = InstrumentProfile(
    instrument_id="XAUUSD",
    symbol="XAU/USD",
    broker_symbol="XAUUSD",
    asset_class="commodity",
    price_precision=None,
    tick_size=None,
    tick_value=None,
    contract_size=None,
    minimum_volume=None,
    volume_step=None,
    maximum_volume=None,
    trading_hours=None,
    weekend_behavior="Expected weekday market with weekend closure; exact broker hours not loaded",
    leverage_rule=None,
    margin_rule=None,
    spread_model=None,
    commission_model=None,
    swap_model=None,
    notes=("Framework placeholder only. Unknown Exness Gold specifications are intentionally unset.",),
)


def load_xauusd_profile(path: str | Path) -> InstrumentProfile:
    """Load an XAUUSD instrument profile from an MT5 symbol snapshot."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("symbol") not in {"XAUUSD", "XAUUSDm"}:
        raise ValueError("Snapshot symbol must be XAUUSD or XAUUSDm.")
    required = ("digits", "point", "tick_size", "contract_size", "volume_min",
                "volume_max", "volume_step")
    missing = [key for key in required if payload.get(key) is None]
    if missing:
        raise ValueError("Snapshot is missing required fields: " + ", ".join(missing))
    return InstrumentProfile(
        instrument_id="XAUUSD", symbol="XAU/USD", broker_symbol=payload["symbol"],
        asset_class="commodity", price_precision=payload["digits"],
        tick_size=payload["tick_size"], tick_value=payload.get("tick_value_loss"),
        contract_size=payload["contract_size"], minimum_volume=payload["volume_min"],
        volume_step=payload["volume_step"], maximum_volume=payload["volume_max"],
        trading_hours="; ".join(payload.get("trading_sessions", [])) or None,
        weekend_behavior="Broker sessions from MT5 snapshot",
        leverage_rule=str(payload.get("margin_calculation_mode")) if payload.get("margin_calculation_mode") is not None else None,
        margin_rule=str(payload.get("margin_initial")) if payload.get("margin_initial") is not None else None,
        spread_model="Captured Bid/Ask snapshot", commission_model=None,
        swap_model=str(payload.get("swap_mode")) if payload.get("swap_mode") is not None else None,
        notes=("Loaded from an MT5 symbol specification snapshot.",),
        point=payload["point"], tick_value_profit=payload.get("tick_value_profit"),
        tick_value_loss=payload.get("tick_value_loss"),
        stops_level=payload.get("stops_level"), freeze_level=payload.get("freeze_level"),
        margin_calculation_mode=str(payload.get("margin_calculation_mode")) if payload.get("margin_calculation_mode") is not None else None,
        margin_initial=payload.get("margin_initial"),
        margin_maintenance=payload.get("margin_maintenance"),
        swap_long=payload.get("swap_long"), swap_short=payload.get("swap_short"),
        swap_mode=str(payload.get("swap_mode")) if payload.get("swap_mode") is not None else None,
        trading_sessions=tuple(payload.get("trading_sessions", [])),
        broker_profile_id=payload.get("profile_id"),
        captured_at_utc=payload.get("capture_timestamp_utc"),
        source=payload.get("source"),
    )

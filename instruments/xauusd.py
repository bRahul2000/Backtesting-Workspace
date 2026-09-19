from __future__ import annotations

import json
from pathlib import Path

from instruments.base_instrument import InstrumentProfile
from services.gold_spec import PROFILE_ID, load_mt5_gold_snapshot

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
    payload = load_mt5_gold_snapshot(path)
    if isinstance(payload.get("symbol"), str):
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
            weekend_behavior="Broker sessions from MT5 snapshot", leverage_rule=None,
            margin_rule="Captured margin_initial is zero; true margin remains unverified",
            spread_model="Captured Bid/Ask snapshot", commission_model=None,
            swap_model=str(payload.get("swap_mode")) if payload.get("swap_mode") is not None else None,
            notes=("Loaded from an MT5 symbol specification snapshot.",), point=payload["point"],
            tick_value_profit=payload.get("tick_value_profit"), tick_value_loss=payload.get("tick_value_loss"),
            stops_level=payload.get("stops_level"), freeze_level=payload.get("freeze_level"),
            margin_calculation_mode=str(payload.get("margin_calculation_mode")) if payload.get("margin_calculation_mode") is not None else None,
            margin_initial=payload.get("margin_initial"), margin_maintenance=payload.get("margin_maintenance"),
            swap_long=payload.get("swap_long"), swap_short=payload.get("swap_short"),
            swap_mode=str(payload.get("swap_mode")) if payload.get("swap_mode") is not None else None,
            trading_sessions=tuple(payload.get("trading_sessions", [])), broker_profile_id=PROFILE_ID,
            captured_at_utc=payload.get("capture_timestamp_utc"), source=payload.get("source"),
        )
    symbol = payload["symbol"]
    contract = payload["contract"]
    volume = payload["volume"]
    trading = payload["trading"]
    margin = payload.get("margin", {})
    swap = payload.get("swap", {})
    required = ("digits", "point")
    missing = [key for key in required if symbol.get(key) is None]
    missing.extend(key for key in ("tick_size", "contract_size") if contract.get(key) is None)
    missing.extend(key for key in ("minimum", "maximum", "step") if volume.get(key) is None)
    if missing:
        raise ValueError("Snapshot is missing required fields: " + ", ".join(missing))
    sessions = tuple(
        f"{item['day']} {item['from']}-{item['to']}"
        for item in payload.get("trading_sessions", [])
    )
    return InstrumentProfile(
        instrument_id="XAUUSD", symbol="XAU/USD", broker_symbol=symbol["name"],
        asset_class="commodity", price_precision=symbol["digits"],
        tick_size=contract["tick_size"], tick_value=contract.get("tick_value_loss"),
        contract_size=contract["contract_size"], minimum_volume=volume["minimum"],
        volume_step=volume["step"], maximum_volume=volume["maximum"],
        trading_hours="; ".join(sessions) or None,
        weekend_behavior="Broker sessions from MT5 snapshot",
        leverage_rule=None,
        margin_rule="Captured margin_initial is zero; true margin remains unverified",
        spread_model="Captured Bid/Ask snapshot", commission_model=None,
        swap_model=str(swap.get("mode")) if swap.get("mode") is not None else None,
        notes=("Loaded from an MT5 symbol specification snapshot.",),
        point=symbol["point"], tick_value_profit=contract.get("tick_value_profit"),
        tick_value_loss=contract.get("tick_value_loss"),
        stops_level=trading.get("stops_level_points"), freeze_level=trading.get("freeze_level_points"),
        margin_calculation_mode=str(trading.get("trade_calc_mode")),
        margin_initial=margin.get("initial"), margin_maintenance=margin.get("maintenance"),
        swap_long=swap.get("long"), swap_short=swap.get("short"),
        swap_mode=str(swap.get("mode")) if swap.get("mode") is not None else None,
        trading_sessions=sessions, broker_profile_id=PROFILE_ID,
        captured_at_utc=payload.get("capture", {}).get("timestamp_utc"),
        source="MT5 SymbolInfo capture; broker identity verified from snapshot",
    )

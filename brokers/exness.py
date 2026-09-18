from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from brokers.base_broker import BrokerInstrumentProfile, BrokerProfile

EXNESS = BrokerProfile(
    broker_id="EXNESS_STANDARD",
    name="Exness",
    account_type="Standard",
    instruments={
        "BTCUSD": BrokerInstrumentProfile(
            instrument_id="BTCUSD",
            broker_symbol="BTCUSDm",
            spread_model="SYNTHETIC_FIXED_BID_ASK",
            default_spread_price=10.0,
            commission_model="SEPARATE_COMMISSION_USD",
            commission_value=0.0,
            slippage_model="Audited engine percentage slippage; benchmark 0",
            contract_size=1.0,
            tick_size=0.01,
            tick_value=None,
            minimum_volume=0.01,
            volume_step=0.01,
            maximum_volume=200.0,
            leverage=1.0,
            margin_rule="Audited backtester leverage cap for migration benchmark",
            swap_rule="Not applied to validated intraday V3 benchmark",
            known=True,
            notes=("Bid source candles; Ask = Bid + configured spread for long entry/short exit.",),
        ),
        "XAUUSD": BrokerInstrumentProfile(
            instrument_id="XAUUSD",
            broker_symbol="XAUUSD",
            known=False,
            notes=("Placeholder. Exact Exness Gold contract/tick/spread/margin/swap values not loaded.",),
        ),
    },
)


def load_exness_xauusd_profile(path: str | Path) -> BrokerProfile:
    """Return a copy of Exness with XAUUSD populated from an MT5 snapshot."""
    from instruments.xauusd import load_xauusd_profile

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    instrument = load_xauusd_profile(path)
    broker = BrokerInstrumentProfile(
        instrument_id="XAUUSD", broker_symbol=payload["symbol"], known=True,
        spread_model="CAPTURED_BID_ASK", default_spread_price=payload.get("spread"),
        commission_model="MT5 symbol specification", contract_size=instrument.contract_size,
        tick_size=instrument.tick_size, tick_value=instrument.tick_value,
        minimum_volume=instrument.minimum_volume, volume_step=instrument.volume_step,
        maximum_volume=instrument.maximum_volume, leverage=payload.get("leverage"),
        margin_rule=str(payload.get("margin_calculation_mode")) if payload.get("margin_calculation_mode") is not None else None,
        swap_rule=str(payload.get("swap_mode")) if payload.get("swap_mode") is not None else None,
        price_precision=instrument.price_precision, point=instrument.point,
        tick_value_profit=instrument.tick_value_profit, tick_value_loss=instrument.tick_value_loss,
        stops_level=instrument.stops_level, freeze_level=instrument.freeze_level,
        margin_calculation_mode=instrument.margin_calculation_mode,
        margin_initial=instrument.margin_initial, margin_maintenance=instrument.margin_maintenance,
        swap_long=instrument.swap_long, swap_short=instrument.swap_short,
        swap_mode=instrument.swap_mode, trading_sessions=instrument.trading_sessions,
        description=payload.get("description"), capture_timestamp_utc=instrument.captured_at_utc,
        source=instrument.source,
    )
    return replace(EXNESS, instruments={**EXNESS.instruments, "XAUUSD": broker})

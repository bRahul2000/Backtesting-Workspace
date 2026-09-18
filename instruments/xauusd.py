from __future__ import annotations

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

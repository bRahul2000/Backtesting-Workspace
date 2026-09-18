from __future__ import annotations

from instruments.base_instrument import InstrumentProfile

BTCUSD = InstrumentProfile(
    instrument_id="BTCUSD",
    symbol="BTC/USD",
    broker_symbol="BTCUSDm",
    asset_class="crypto",
    price_precision=2,
    tick_size=0.01,
    tick_value=None,  # deliberately not guessed; audited engine sizes in BTC quantity
    contract_size=1.0,  # 1 lot = 1 BTC from the calibrated Exness profile
    minimum_volume=0.01,
    volume_step=0.01,
    maximum_volume=200.0,
    trading_hours="Sunday–Saturday, 00:00–24:00 displayed MT5 specification",
    weekend_behavior="Trading enabled per observed BTCUSDm specification",
    leverage_rule="Backtester migration benchmark uses max_leverage=1.0",
    margin_rule="Audited engine leverage cap; broker-native margin conversion not generalized yet",
    spread_model="Synthetic Bid/Ask replay; validated reference spread $10/BTC",
    commission_model="$0 separate commission for frozen V3 benchmark",
    swap_model="Existing Exness BTC profile records points; not applied to current intraday benchmark",
    notes=("Chart/source candles are treated as Bid in the audited synthetic replay.",),
)

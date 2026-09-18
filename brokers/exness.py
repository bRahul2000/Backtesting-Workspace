from __future__ import annotations

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

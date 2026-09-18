from brokers.exness import EXNESS
from instruments.btcusd import BTCUSD
from instruments.xauusd import XAUUSD


def test_btc_profile_preserves_audited_exness_assumptions():
    assert BTCUSD.broker_symbol == "BTCUSDm"
    assert BTCUSD.contract_size == 1.0
    assert BTCUSD.minimum_volume == 0.01
    assert BTCUSD.volume_step == 0.01
    profile = EXNESS.instrument("BTCUSD")
    assert profile.default_spread_price == 10.0
    assert profile.commission_value == 0.0
    assert profile.contract_size == 1.0
    assert profile.known


def test_gold_profile_is_explicitly_incomplete_not_guessed():
    assert XAUUSD.broker_symbol == "XAUUSD"
    assert XAUUSD.tick_size is None
    assert XAUUSD.tick_value is None
    assert XAUUSD.contract_size is None
    assert "tick_size" in XAUUSD.unknown_fields
    assert not EXNESS.instrument("XAUUSD").known

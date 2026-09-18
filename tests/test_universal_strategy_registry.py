from strategies.base_strategy import ParameterType, StrategyStatus
from strategies.registry import discover_builtin_strategies


def test_registry_discovers_frozen_and_rejected_v3_components():
    registry = discover_builtin_strategies()
    ids = {item.metadata.strategy_id: item for item in registry.all()}
    assert ids["BTC_V3_A4_PULLBACK_LONG_FROZEN"].metadata.status is StrategyStatus.FROZEN
    assert ids["BTC_V3_T3_BREAKOUT_SHORT_FROZEN"].metadata.status is StrategyStatus.FROZEN
    assert ids["BTC_V3_CORE_V1_FROZEN"].metadata.status is StrategyStatus.FROZEN
    assert ids["BTC_V3_R2_RANGE_LIQUIDITY_SWEEP"].metadata.status is StrategyStatus.REJECTED
    assert ids["BTC_V3_M1_MOMENTUM_EXPANSION"].metadata.status is StrategyStatus.REJECTED
    assert ids["BTC_V3_MR1_INTRADAY_OVERSHOOT"].metadata.status is StrategyStatus.REJECTED


def test_frozen_parameters_are_read_only():
    descriptor = discover_builtin_strategies().get("BTC_V3_A4_PULLBACK_LONG_FROZEN")
    body = next(p for p in descriptor.parameters if p.name == "confirmation_min_body_percent")
    assert body.parameter_type is ParameterType.PERCENTAGE
    assert body.default == 0.70
    assert body.frozen
    try:
        body.validate(0.71)
    except ValueError:
        pass
    else:
        raise AssertionError("Frozen parameter accepted a changed value")


def test_registry_filters_by_instrument():
    registry = discover_builtin_strategies()
    assert registry.for_instrument("BTCUSD")
    assert not registry.for_instrument("XAUUSD")

from strategies.base_strategy import StrategyStatus
from strategies.registry import discover_builtin_strategies


def test_metadata_has_required_identity_fields_and_hash():
    for descriptor in discover_builtin_strategies().all():
        meta = descriptor.metadata
        assert meta.strategy_id
        assert meta.name
        assert meta.version
        assert isinstance(meta.status, StrategyStatus)
        assert meta.category
        assert meta.supported_instruments
        assert meta.supported_timeframes
        assert meta.description
        assert meta.created_date
        assert len(meta.strategy_fingerprint) == 64

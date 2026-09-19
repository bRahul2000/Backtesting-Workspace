import json
from pathlib import Path

from core.fingerprints import sha256_file
from strategies.base_strategy import StrategyStatus, parameter_fingerprint
from strategies.registry import discover_builtin_strategies
from ui.universal_workspace import (
    comparison_frame, compatible_strategies, format_price, verify_reproduction,
)


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_filters_registry_by_instrument_and_status():
    btc = compatible_strategies("BTCUSD")
    gold = compatible_strategies("XAUUSDm")
    assert btc
    assert all("BTCUSD" in item.metadata.supported_instruments for item in btc)
    assert not gold
    assert all(item.metadata.status is not StrategyStatus.REJECTED for item in btc)
    assert any(item.metadata.status is StrategyStatus.FROZEN for item in btc)


def test_workspace_uses_instrument_price_precision():
    assert format_price(4378.1234, "XAUUSDm") == "4,378.123"
    assert format_price(4378.1234, "BTCUSD") == "4,378.12"


def test_frozen_descriptor_rejects_parameter_override():
    descriptor = next(item for item in compatible_strategies("BTCUSD")
                      if item.metadata.status is StrategyStatus.FROZEN)
    frozen = next(parameter for parameter in descriptor.parameters if parameter.frozen)
    try:
        descriptor.create({frozen.name: frozen.default + 1})
    except ValueError as error:
        assert "Frozen parameter" in str(error) or "read-only" in str(error)
    else:
        raise AssertionError("Frozen parameter override was accepted")


def test_experiment_comparison_reports_metrics_without_ranking():
    frame = comparison_frame([
        {"run_id": "BT-1", "instrument": "BTCUSD", "strategy_name": "Core",
         "strategy_status": "FROZEN", "dataset_role": "DEVELOPMENT",
         "results_json": {"total_trades": 10, "profit_factor": 1.2}},
        {"run_id": "BT-2", "instrument": "XAUUSDm", "strategy_name": "Gold",
         "strategy_status": "RESEARCH", "dataset_role": "DEVELOPMENT",
         "results_json": {"total_trades": 11, "profit_factor": 1.1}},
    ])
    assert frame["Trades"].tolist() == [10, 11]
    assert "Winner" not in frame.columns


def test_reproduce_run_blocks_changed_dependency(tmp_path):
    descriptor = discover_builtin_strategies().get("BTC_V3_CORE_V1_FROZEN")
    dataset = tmp_path / "data.csv"
    dataset.write_text("content")
    row = {
        "strategy_fingerprint": descriptor.metadata.strategy_fingerprint,
        "dataset_fingerprint": sha256_file(dataset),
        "broker_fingerprint": "broker",
        "instrument_fingerprint": "instrument",
        "parameter_fingerprint": parameter_fingerprint({}),
        "config_json": json.dumps({"strategy_parameters": {}}),
    }
    ok, message = verify_reproduction(row, descriptor, dataset, "broker", "instrument")
    assert ok is True
    assert "permitted" in message
    row["dataset_fingerprint"] = "changed"
    ok, message = verify_reproduction(row, descriptor, dataset, "broker", "instrument")
    assert ok is False
    assert message.startswith("REPRODUCTION BLOCKED")

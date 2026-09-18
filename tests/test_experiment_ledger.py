from experiments.ledger import ExperimentLedger


def test_ledger_allocates_reproducible_run_ids_and_counts_forward(tmp_path):
    ledger = ExperimentLedger(tmp_path / "experiments.sqlite3")
    common = dict(
        strategy_id="S1", strategy_name="Strategy", strategy_status="RESEARCH",
        strategy_fingerprint="sf", parameter_fingerprint="pf", dataset_fingerprint="df",
        broker_fingerprint="bf", broker_profile="EXNESS_STANDARD", instrument="BTCUSD",
        date_start="2025-01-01", date_end="2025-02-01", config={}, notes="",
        instrument_fingerprint="if",
    )
    first = ledger.start_run(dataset_role="DEVELOPMENT", **common)
    second = ledger.start_run(dataset_role="FORWARD_VALIDATION", **common)
    assert first.endswith("000001")
    assert second.endswith("000002")
    ledger.finish_run(second, {"trades": 3})
    assert ledger.forward_run_count("S1") == 1
    assert '"trades": 3' in ledger.get(second)["results_json"]
    assert ledger.get(second)["instrument_fingerprint"] == "if"

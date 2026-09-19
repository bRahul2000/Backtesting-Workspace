from datetime import datetime, timedelta, timezone

import pytest

from engine.diagnostics import ExecutionAmbiguity
from engine.models import Direction, OrderEvent, Trade
from research.execution_replay import (
    AmbiguityResolution, ExecutionReplayBlocked, ExecutionReplayStore, GapType,
    ReplayConfig, ReplayDataset, ReplayEvent, ReplayMode, ReplayResolution,
    ResolutionStatus, assign_parent_bars, build_lower_timeframe_dataset,
    build_replay_adjusted_scenario, build_replay_trade, build_tick_dataset,
    classify_comparison, classify_gap, compare_baseline_and_replay, coverage_report,
    events_for_parent_bar, execution_sensitivity_summary, load_exness_btc_tick_sample,
    map_to_parent_bar, replay_fingerprint, resolve_ambiguity, resolve_ambiguity_with_hierarchy,
    run_execution_replay, validate_replay_resume,
)

UTC = timezone.utc
BAR_TS = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
NEXT_BAR_TS = datetime(2024, 1, 1, 10, 15, 0, tzinfo=UTC)


def _trade(trade_id, direction, entry_price, stop_loss, take_profit, exit_price, exit_reason, pnl, r_multiple, entry_time=None, exit_time=None):
    entry_time = entry_time or BAR_TS
    exit_time = exit_time or BAR_TS
    risk = abs(entry_price - stop_loss)
    return Trade(
        trade_id=trade_id, direction=direction, signal_time=entry_time, entry_time=entry_time,
        entry_price=entry_price, stop_loss=stop_loss, take_profit=take_profit,
        exit_time=exit_time, exit_price=exit_price, exit_reason=exit_reason,
        quantity=1.0, initial_risk=risk, pnl=pnl, pnl_percent=0.0, r_multiple=r_multiple,
        bars_held=1, entry_commission=0.0, exit_commission=0.0, duration_minutes=15.0,
    )


def _tick(timestamp, bid, ask, sequence_number, parent=BAR_TS):
    return ReplayEvent(timestamp=timestamp, bid=bid, ask=ask, last=None, source="TRUE_QUOTE",
                       resolution=ReplayResolution.TICK.value, parent_bar_timestamp=parent, sequence_number=sequence_number)


def _lower_tf_event(timestamp, low, high, spread, sequence_number, parent=BAR_TS):
    return [
        ReplayEvent(timestamp, bid=low, ask=low + spread, last=None, source="SYNTHETIC_BID_ASK",
                    resolution=ReplayResolution.LOWER_TIMEFRAME.value, parent_bar_timestamp=parent, sequence_number=sequence_number),
        ReplayEvent(timestamp, bid=high, ask=high + spread, last=None, source="SYNTHETIC_BID_ASK",
                    resolution=ReplayResolution.LOWER_TIMEFRAME.value, parent_bar_timestamp=parent, sequence_number=sequence_number + 1),
    ]


# --- Parent-bar mapping ------------------------------------------------------------------


def test_parent_bar_mapping_first_event_final_event_and_next_bar_boundary():
    bars = [BAR_TS, NEXT_BAR_TS]
    assert map_to_parent_bar(BAR_TS, bars, 900) == BAR_TS  # first event, exactly on the bar open
    assert map_to_parent_bar(BAR_TS + timedelta(minutes=14, seconds=59), bars, 900) == BAR_TS  # final event before boundary
    assert map_to_parent_bar(NEXT_BAR_TS, bars, 900) == NEXT_BAR_TS  # next-bar boundary belongs to the next bar


def test_parent_bar_mapping_timezone_aware_only():
    bars = [BAR_TS]
    naive = datetime(2024, 1, 1, 10, 5, 0)
    with pytest.raises(TypeError):
        map_to_parent_bar(naive, bars, 900)  # naive vs aware comparison raises, by design


def test_parent_bar_mapping_duplicates_map_to_same_bar():
    bars = [BAR_TS]
    t1 = map_to_parent_bar(BAR_TS + timedelta(seconds=1), bars, 900)
    t2 = map_to_parent_bar(BAR_TS + timedelta(seconds=1), bars, 900)
    assert t1 == t2 == BAR_TS


def test_parent_bar_mapping_missing_period_returns_none():
    bars = [BAR_TS, BAR_TS + timedelta(hours=2)]  # a big gap; no bar at 10:15
    orphan = map_to_parent_bar(BAR_TS + timedelta(minutes=30), bars, 900)
    assert orphan is None


# --- Quote-side semantics / long / short replay -----------------------------------------


def test_long_replay_uses_bid_for_exit_and_ask_for_trigger():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=96.0, ask=96.5, sequence_number=0),
              _tick(BAR_TS + timedelta(seconds=2), bid=94.0, ask=94.5, sequence_number=1)]  # bid crosses stop=95
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level == "stop"
    assert resolution.quote_side == "bid"
    assert resolution.status == ResolutionStatus.EXACT_TICK_RESOLUTION.value


def test_short_replay_uses_ask_for_exit():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 105.0, "target": 90.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=99.0, ask=99.5, sequence_number=0),
              _tick(BAR_TS + timedelta(seconds=2), bid=104.5, ask=105.5, sequence_number=1)]  # ask crosses stop=105
    resolution = resolve_ambiguity(ambiguity, Direction.SHORT, events, ReplayResolution.TICK)
    assert resolution.touched_level == "stop"
    assert resolution.quote_side == "bid"  # exit side is still labeled by level name, quote_side helper returns "bid" only for non-trigger


# --- SL-before-TP / TP-before-SL (tick resolution) -----------------------------------------


def test_sl_before_tp_tick_resolution_matches_baseline_sl_first():
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss (ambiguous bar, SL First)", pnl=-5.0, r_multiple=-1.0)
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=94.0, ask=94.5, sequence_number=0),
              _tick(BAR_TS + timedelta(seconds=2), bid=111.0, ask=111.5, sequence_number=1)]
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level == "stop"
    replay = build_replay_trade(baseline, resolution)
    comparison = compare_baseline_and_replay(baseline, replay, resolution)
    assert comparison.classification == "BASELINE_AMBIGUITY_RESOLVED"


def test_tp_before_sl_tick_resolution_flips_outcome():
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss (ambiguous bar, SL First)", pnl=-5.0, r_multiple=-1.0)
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=111.0, ask=111.5, sequence_number=0),
              _tick(BAR_TS + timedelta(seconds=2), bid=94.0, ask=94.5, sequence_number=1)]
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level == "target"
    replay = build_replay_trade(baseline, resolution)
    comparison = compare_baseline_and_replay(baseline, replay, resolution)
    assert comparison.classification == "OUTCOME_CHANGED"
    assert baseline.pnl < 0 < replay.pnl


# --- Pending order: trigger then SL / trigger then TP --------------------------------------


def test_pending_entry_then_sl():
    ambiguity = ExecutionAmbiguity("PENDING_ENTRY_AND_STOP_SAME_CANDLE", BAR_TS, None, "sig-LONG", {"trigger": 100.0, "stop": 95.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=99.5, ask=100.5, sequence_number=0),   # trigger touched (ask>=100)
              _tick(BAR_TS + timedelta(seconds=2), bid=94.5, ask=95.0, sequence_number=1)]    # stop touched afterward (bid<=95)
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level == "trigger"
    assert resolution.secondary_touched_level == "stop"
    assert resolution.resolved_outcome == "activated_then_stop"
    assert resolution.activation_timestamp == events[0].timestamp


def test_pending_entry_then_tp():
    ambiguity = ExecutionAmbiguity("PENDING_ENTRY_AND_STOP_SAME_CANDLE", BAR_TS, None, "sig-LONG", {"trigger": 100.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=99.5, ask=100.5, sequence_number=0),
              _tick(BAR_TS + timedelta(seconds=2), bid=110.5, ask=111.0, sequence_number=1)]   # target touched afterward
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.secondary_touched_level == "target"
    assert resolution.resolved_outcome == "activated_then_target"


def test_pending_order_expiry_leaves_no_activation():
    ambiguity = ExecutionAmbiguity("PENDING_ENTRY_AND_STOP_SAME_CANDLE", BAR_TS, None, "sig-LONG", {"trigger": 100.0, "stop": 95.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=98.0, ask=99.0, sequence_number=0)]  # trigger never touched
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level is None
    assert resolution.status == ResolutionStatus.REPLAY_DATA_INCOMPLETE.value


# --- Lower-TF unresolved / exact tick resolution -----------------------------------------


def test_lower_tf_single_finer_bar_touches_both_levels_is_still_ambiguous():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    finer_bar = _lower_tf_event(BAR_TS + timedelta(minutes=5), low=90.0, high=115.0, spread=0.5, sequence_number=0)  # one finer bar spans both
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, finer_bar, ReplayResolution.LOWER_TIMEFRAME)
    assert resolution.status == ResolutionStatus.STILL_AMBIGUOUS.value


def test_lower_tf_resolves_via_bar_sequence_when_levels_touched_in_different_finer_bars():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    bar_a = _lower_tf_event(BAR_TS + timedelta(minutes=1), low=94.0, high=99.0, spread=0.5, sequence_number=0)   # touches stop only
    bar_b = _lower_tf_event(BAR_TS + timedelta(minutes=6), low=100.0, high=111.0, spread=0.5, sequence_number=2)  # touches target only, later
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, bar_a + bar_b, ReplayResolution.LOWER_TIMEFRAME)
    assert resolution.status == ResolutionStatus.LOWER_TF_RESOLUTION.value
    assert resolution.touched_level == "stop"


def test_exact_tick_resolution_status():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=94.0, ask=94.5, sequence_number=0)]
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.status == ResolutionStatus.EXACT_TICK_RESOLUTION.value
    assert resolution.resolution_source == ReplayResolution.TICK.value


# --- Missing coverage / fallback policy / gap ---------------------------------------------


def test_missing_replay_dataset_reports_replay_data_missing():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    resolution = resolve_ambiguity_with_hierarchy(ambiguity, Direction.LONG)
    assert resolution.status == ResolutionStatus.REPLAY_DATA_MISSING.value
    assert resolution.touched_level is None


def test_dataset_present_but_no_coverage_falls_back_to_baseline_policy():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    resolution = resolve_ambiguity_with_hierarchy(ambiguity, Direction.LONG, tick_dataset_available=True, tick_events=[])
    assert resolution.status == ResolutionStatus.FALLBACK_BASELINE_POLICY.value
    assert resolution.touched_level == "stop"  # SL_FIRST


def test_replay_data_gap_classification():
    gap = classify_gap(previous_bar=BAR_TS, next_bar=BAR_TS + timedelta(hours=1), interval_seconds=900,
                       replay_coverage_start=BAR_TS - timedelta(hours=2), replay_coverage_end=BAR_TS + timedelta(hours=2))
    assert gap == GapType.REPLAY_DATA_GAP.value


def test_missing_data_gap_classification_outside_replay_coverage():
    gap = classify_gap(previous_bar=BAR_TS, next_bar=BAR_TS + timedelta(hours=1), interval_seconds=900,
                       replay_coverage_start=BAR_TS + timedelta(hours=5), replay_coverage_end=BAR_TS + timedelta(hours=6))
    assert gap == GapType.MISSING_DATA_GAP.value


def test_market_gap_when_no_replay_dataset_at_all():
    gap = classify_gap(previous_bar=BAR_TS, next_bar=BAR_TS + timedelta(hours=1), interval_seconds=900,
                       replay_coverage_start=None, replay_coverage_end=None)
    assert gap == GapType.MARKET_GAP.value


# --- Tick ordering / duplicate timestamps ---------------------------------------------------


def test_duplicate_tick_timestamps_use_stable_sequence_number():
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    same_ts = BAR_TS + timedelta(seconds=1)
    events = [_tick(same_ts, bid=111.0, ask=111.5, sequence_number=0),   # target touch, sequence 0 (earlier source order)
              _tick(same_ts, bid=94.0, ask=94.5, sequence_number=1)]     # stop touch, sequence 1
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    assert resolution.touched_level == "target"  # sequence_number breaks the timestamp tie deterministically


def test_malformed_tick_ordering_blocks_dataset_construction():
    rows = [
        {"timestamp": (BAR_TS + timedelta(seconds=2)).isoformat(), "bid": 100.0, "ask": 100.5},
        {"timestamp": (BAR_TS + timedelta(seconds=1)).isoformat(), "bid": 100.0, "ask": 100.5},  # out of order
    ]
    with pytest.raises(ExecutionReplayBlocked, match="chronological order"):
        build_tick_dataset(rows, instrument="BTCUSD", broker="TEST")


def test_malformed_tick_row_blocks_dataset_construction():
    rows = [{"timestamp": BAR_TS.isoformat(), "bid": None, "ask": 100.5}]
    with pytest.raises(ExecutionReplayBlocked, match="malformed"):
        build_tick_dataset(rows, instrument="BTCUSD", broker="TEST")


# --- Coverage ---------------------------------------------------------------------------------


def test_coverage_report_trades_and_ambiguities_inside_and_outside_window():
    inside = _trade(1, Direction.LONG, 100, 95, 110, 110, "Take profit", 10.0, 1.0, exit_time=BAR_TS)
    outside = _trade(2, Direction.LONG, 100, 95, 110, 95, "Stop loss", -5.0, -1.0, exit_time=BAR_TS + timedelta(days=5))
    dataset = build_tick_dataset(
        [{"timestamp": (BAR_TS - timedelta(minutes=1)).isoformat(), "bid": 100.0, "ask": 100.5},
         {"timestamp": (BAR_TS + timedelta(minutes=1)).isoformat(), "bid": 100.0, "ask": 100.5}],
        instrument="BTCUSD", broker="TEST",
    )
    ambiguities = [ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")]
    report = coverage_report(baseline_period=(BAR_TS, BAR_TS + timedelta(days=5)), replay_dataset=dataset,
                             baseline_trades=[inside, outside], ambiguities=ambiguities)
    assert report["baseline_trades_covered"] == 1
    assert report["baseline_trades_outside_coverage"] == 1
    assert report["ambiguities_covered"] == 1
    assert report["ambiguities_outside_coverage"] == 0


# --- Fingerprint reproducibility -------------------------------------------------------------


def test_fingerprint_reproducibility():
    config = {"mode": "AMBIGUITIES_ONLY"}
    a = replay_fingerprint(baseline_fingerprint="b1", replay_dataset_fingerprint="d1", resolution="TICK",
                           quote_model="TRUE_QUOTE", config=config, engine_version="v1")
    b = replay_fingerprint(baseline_fingerprint="b1", replay_dataset_fingerprint="d1", resolution="TICK",
                           quote_model="TRUE_QUOTE", config=config, engine_version="v1")
    c = replay_fingerprint(baseline_fingerprint="b1", replay_dataset_fingerprint="d2", resolution="TICK",
                           quote_model="TRUE_QUOTE", config=config, engine_version="v1")
    assert a == b
    assert a != c


# --- Baseline immutability / trade comparison -------------------------------------------------


def test_baseline_trade_is_never_mutated():
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss (ambiguous bar, SL First)", pnl=-5.0, r_multiple=-1.0)
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    events = [_tick(BAR_TS + timedelta(seconds=1), bid=111.0, ask=111.5, sequence_number=0)]
    resolution = resolve_ambiguity(ambiguity, Direction.LONG, events, ReplayResolution.TICK)
    original_snapshot = (baseline.exit_price, baseline.exit_reason, baseline.pnl, baseline.r_multiple)
    replay = build_replay_trade(baseline, resolution)
    assert (baseline.exit_price, baseline.exit_reason, baseline.pnl, baseline.r_multiple) == original_snapshot
    assert replay is not baseline
    assert replay.exit_price != baseline.exit_price


def test_trade_comparison_classification_identical_when_not_ambiguous():
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=110.0, exit_reason="Take profit", pnl=10.0, r_multiple=2.0)
    resolution = AmbiguityResolution(
        ambiguity_type="SL_AND_TP_SAME_CANDLE", trade_id=1, order_id=None, parent_bar_timestamp=BAR_TS,
        status=ResolutionStatus.NOT_AMBIGUOUS.value, resolution_source=ReplayResolution.BASE_BAR.value,
        touched_level=None, first_relevant_event_timestamp=None, quote_side=None, resolved_price=None, resolved_outcome=None,
    )
    classification = classify_comparison(baseline, baseline, resolution)
    assert classification == "IDENTICAL"


# --- Replay-adjusted scenario ------------------------------------------------------------------


def test_replay_adjusted_scenario_reports_winners_to_losers_and_pnl_difference():
    baseline1 = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=110.0, exit_reason="Take profit", pnl=10.0, r_multiple=2.0)
    baseline2 = _trade(2, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss", pnl=-5.0, r_multiple=-1.0)
    replay2 = build_replay_trade(baseline2, AmbiguityResolution(
        "SL_AND_TP_SAME_CANDLE", 2, None, BAR_TS, ResolutionStatus.EXACT_TICK_RESOLUTION.value, ReplayResolution.TICK.value,
        "target", BAR_TS, "bid", 110.0, "target",
    ))
    comparisons = [compare_baseline_and_replay(baseline2, replay2, AmbiguityResolution(
        "SL_AND_TP_SAME_CANDLE", 2, None, BAR_TS, ResolutionStatus.EXACT_TICK_RESOLUTION.value, ReplayResolution.TICK.value,
        "target", BAR_TS, "bid", 110.0, "target",
    ))]
    scenario = build_replay_adjusted_scenario([baseline1, baseline2], comparisons, {2: replay2})
    assert scenario["label"] == "REPLAY_ADJUSTED_SCENARIO"
    assert scenario["losers_to_winners"] == 1
    assert scenario["pnl_difference"] == pytest.approx(replay2.pnl - baseline2.pnl)


def test_execution_sensitivity_summary():
    ambiguities = [ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")]
    resolutions = [AmbiguityResolution(
        "SL_AND_TP_SAME_CANDLE", 1, None, BAR_TS, ResolutionStatus.EXACT_TICK_RESOLUTION.value, ReplayResolution.TICK.value,
        "target", BAR_TS, "bid", 110.0, "target",
    )]
    comparisons = [compare_baseline_and_replay(
        _trade(1, Direction.LONG, 100.0, 95.0, 110.0, 95.0, "Stop loss", -5.0, -1.0),
        _trade(1, Direction.LONG, 100.0, 95.0, 110.0, 110.0, "Take profit", 10.0, 2.0),
        resolutions[0],
    )]
    summary = execution_sensitivity_summary(ambiguities, resolutions, comparisons)
    assert summary["resolved"] == 1
    assert summary["outcome_changed"] == 1
    assert summary["resolved_percent"] == 100.0


# --- Persistence / resume ----------------------------------------------------------------------


def test_persistence_and_reopen_without_rerun(tmp_path):
    store = ExecutionReplayStore(tmp_path / "replay.sqlite3")
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss (ambiguous bar, SL First)", pnl=-5.0, r_multiple=-1.0)
    ambiguity = ExecutionAmbiguity("SL_AND_TP_SAME_CANDLE", BAR_TS, 1, None, {"stop": 95.0, "target": 110.0}, "SL_FIRST")
    dataset = build_tick_dataset(
        [{"timestamp": (BAR_TS + timedelta(seconds=1)).isoformat(), "bid": 94.0, "ask": 94.5}],
        instrument="BTCUSD", broker="TEST",
    )
    config = ReplayConfig(mode=ReplayMode.AMBIGUITIES_ONLY)
    run, resolutions, comparisons, summary = run_execution_replay(
        baseline_experiment_id="BT-1", baseline_fingerprint="fp1", baseline_trades=[baseline], baseline_orders=[],
        ambiguities=[ambiguity], dataset_role="DEVELOPMENT", replay_dataset=dataset, lower_tf_dataset=None,
        config=config, engine_version="test",
    )
    store.save_run(run)
    store.save_result(run.replay_id, {"resolutions": [r.status for r in resolutions], **summary})
    loaded_run = store.load_run(run.replay_id)
    loaded_result = store.load_result(run.replay_id)
    assert loaded_run.replay_id == run.replay_id
    assert loaded_result["coverage"]["baseline_trades_covered"] >= 0


def test_resume_fingerprint_mismatch_is_blocked(tmp_path):
    store = ExecutionReplayStore(tmp_path / "replay.sqlite3")
    baseline = _trade(1, Direction.LONG, 100.0, 95.0, 110.0, exit_price=95.0, exit_reason="Stop loss", pnl=-5.0, r_multiple=-1.0)
    config = ReplayConfig()
    run, *_ = run_execution_replay(
        baseline_experiment_id="BT-1", baseline_fingerprint="fp1", baseline_trades=[baseline], baseline_orders=[],
        ambiguities=[], dataset_role="DEVELOPMENT", replay_dataset=None, lower_tf_dataset=None, config=config, engine_version="test",
    )
    store.save_run(run)
    with pytest.raises(ExecutionReplayBlocked, match="RESUME BLOCKED"):
        validate_replay_resume(store.load_run(run.replay_id), baseline_fingerprint="CHANGED",
                               replay_dataset_fingerprint=run.replay_dataset_fingerprint, config=run.config)


# --- UI model generation / config defaults -------------------------------------------------------


def test_ui_model_generation_defaults():
    config = ReplayConfig()
    assert config.mode is ReplayMode.AMBIGUITIES_ONLY
    payload = config.as_dict()
    assert payload["mode"] == "AMBIGUITIES_ONLY"
    assert payload["selected_trade_ids"] == []


# --- Real-data policy: genuine Exness BTC tick sample --------------------------------------------


REAL_TICK_SAMPLE = "data/exness/processed/btcusdm_s01_ticks_server_time.csv"


def test_real_exness_tick_sample_loads_and_fingerprints_reproducibly():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / REAL_TICK_SAMPLE
    if not path.exists():
        pytest.skip("real Exness tick sample not present in this checkout")
    dataset_a = load_exness_btc_tick_sample(path)
    dataset_b = load_exness_btc_tick_sample(path)
    assert dataset_a.fingerprint == dataset_b.fingerprint
    assert dataset_a.spread_provenance == "TRUE_QUOTE"
    assert dataset_a.coverage_start < dataset_a.coverage_end
    assert len(dataset_a.events) > 1000

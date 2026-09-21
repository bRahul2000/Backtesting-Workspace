"""BTC Core V2 Phase E — D2 stability and integration.

The phase rests on three pieces of machinery: D2 must be provably unchanged, the
sensitivity arms must move exactly one threshold each, and the two integration
policies must differ only in the rule they are meant to differ in. All three are
pinned here, including the negative result that Policy 2 cannot suppress
anything on this data — that has to be a measured fact, not a silent no-op.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from engine.models import Candle, Direction, Signal
from research import core_v2_phase_e as phase_e
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies import btc_core_v2_phase_e_variants as variants
from strategies.btc_core_v2_phase_d_families import (
    CoreWithFamily, D2_SETUP_ID, D2A4ShortMirror,
)
from strategies.btc_v3_a4_pullback_long import MINIMUM_NORMALIZED_H1_SLOPE, frozen_parameters
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
STAMP = pd.Timestamp("2024-03-01T12:00:00Z")


# --- D2 is frozen for this phase --------------------------------------------------


def test_the_d2_baseline_implementation_is_unchanged():
    assert variants.d2_implementation_hash() == variants.D2_IMPLEMENTATION_HASH
    assert variants.assert_d2_unchanged() == variants.D2_IMPLEMENTATION_HASH


def test_a_changed_d2_is_refused(monkeypatch):
    monkeypatch.setattr(variants, "D2_IMPLEMENTATION_HASH", "0" * 64)
    with pytest.raises(RuntimeError, match="D2 baseline implementation changed"):
        variants.assert_d2_unchanged()


def test_every_sensitivity_arm_is_a_separate_wrapper_not_an_edit_to_d2():
    for _, (_, _, builder) in variants.SENSITIVITY_ARMS.items():
        assert issubclass(builder, D2A4ShortMirror)
        assert builder is not D2A4ShortMirror


# --- one threshold each ------------------------------------------------------------


@pytest.mark.parametrize("value", variants.BODY_THRESHOLDS)
def test_the_body_arm_moves_only_the_confirmation_body_minimum(value):
    frozen, params = asdict(frozen_parameters()), asdict(variants.D2BodyVariant(value).params)
    assert params.pop("confirmation_min_body_percent") == value
    frozen.pop("confirmation_min_body_percent")
    assert params == frozen


@pytest.mark.parametrize("offset,expected", ((-2.0, (28.0, 50.0)), (0.0, (30.0, 52.0)),
                                             (2.0, (32.0, 54.0))))
def test_the_rsi_arm_shifts_the_mirrored_band_without_changing_its_width(offset, expected):
    variant = variants.D2RsiBandVariant(offset)
    assert variant.mirrored_band == expected
    assert expected[1] - expected[0] == 22.0
    frozen, params = asdict(frozen_parameters()), asdict(variant.params)
    for name in ("confirmation_rsi_min", "confirmation_rsi_max"):
        assert params.pop(name) == frozen.pop(name) - offset
    assert params == frozen


@pytest.mark.parametrize("value", variants.SLOPE_THRESHOLDS)
def test_the_slope_arm_moves_only_the_slope_threshold(value):
    variant = variants.D2SlopeVariant(value)
    assert variant.slope_threshold == value
    assert asdict(variant.params) == asdict(frozen_parameters())


def test_the_baseline_arm_of_every_family_is_the_frozen_d2_value():
    assert variants.ARM_BASELINE["BODY"] == frozen_parameters().confirmation_min_body_percent
    assert variants.ARM_BASELINE["RSI"] == 0.0
    assert variants.ARM_BASELINE["SLOPE"] == MINIMUM_NORMALIZED_H1_SLOPE


def test_the_slope_arm_actually_gates_on_its_own_threshold():
    from strategies.confirmed_h1_regime import H1RegimeValue

    #--- separation |90-100| / 10 = 1.00, exactly the frozen minimum, and
    #--- |slope| / atr = 1.2 / 10 = 0.12: above 0.10, below 0.15.
    h1 = H1RegimeValue(hour=STAMP, close=95.0, fast_ema=90.0, slow_ema=100.0,
                       slow_ema_lookback=101.2, atr=10.0)
    assert h1.slope == pytest.approx(-1.2)
    assert h1.separation_atr == pytest.approx(1.0)
    loose, tight = variants.D2SlopeVariant(0.10), variants.D2SlopeVariant(0.15)
    assert loose._context_valid(h1, 90.0, 100.0, 25.0) is True
    assert tight._context_valid(h1, 90.0, 100.0, 25.0) is False


def test_the_reward_multiple_is_never_perturbed():
    for arm, (_, values, builder) in variants.SENSITIVITY_ARMS.items():
        for value in values:
            assert builder(value).params.reward_multiple == 3.0


def test_the_mirrored_parameter_inventory_names_the_three_perturbed_thresholds():
    names = [name for name, _ in variants.MIRRORED_PARAMETERS]
    assert "confirmation_min_body_percent" in names
    assert "mirrored_rsi_band" in names
    assert "minimum_normalized_h1_slope" in names
    assert "reward_multiple" in names


# --- the two integration policies ---------------------------------------------------


def test_policy_two_refuses_to_run_without_a_baseline_timeline():
    with pytest.raises(RuntimeError, match="baseline timeline"):
        variants.CoreWithD2Policy2()


def test_policy_two_reads_the_installed_timeline_and_restores_it():
    intervals = [(STAMP, STAMP + pd.Timedelta(hours=2))]
    with variants.baseline_timeline(intervals):
        policy = variants.CoreWithD2Policy2()
        assert policy._baseline_busy(STAMP + pd.Timedelta(hours=1)) is True
        assert policy._baseline_busy(STAMP + pd.Timedelta(days=5)) is False
    with pytest.raises(RuntimeError):
        variants.CoreWithD2Policy2()


def _d2_signal():
    return Signal.pending_stop(Direction.SHORT, 100.0, 110.0, 2, D2_SETUP_ID)


def test_policy_two_suppresses_a_d2_signal_while_the_baseline_was_busy(monkeypatch):
    intervals = [(STAMP, STAMP + pd.Timedelta(hours=2))]
    monkeypatch.setattr(CoreWithFamily, "on_candle", lambda self, candle: _d2_signal())
    with variants.baseline_timeline(intervals):
        policy = variants.CoreWithD2Policy2()
        busy = Candle(STAMP + pd.Timedelta(hours=1), 1, 2, 0.5, 1.5, 1.0)
        idle = Candle(STAMP + pd.Timedelta(days=5), 1, 2, 0.5, 1.5, 1.0)
        assert policy.on_candle(busy) is None
        assert policy.suppressed_signals == 1
        assert isinstance(policy.on_candle(idle), Signal)
        assert policy.suppressed_signals == 1


def test_policy_two_never_suppresses_a_frozen_child_signal(monkeypatch):
    """Only D2 is gated; the frozen pair keeps its unconditional priority."""
    frozen_signal = Signal.pending_stop(Direction.SHORT, 100.0, 110.0, 2, T3_SETUP_ID)
    monkeypatch.setattr(CoreWithFamily, "on_candle", lambda self, candle: frozen_signal)
    with variants.baseline_timeline([(STAMP, STAMP + pd.Timedelta(hours=2))]):
        policy = variants.CoreWithD2Policy2()
        busy = Candle(STAMP + pd.Timedelta(hours=1), 1, 2, 0.5, 1.5, 1.0)
        assert policy.on_candle(busy) is frozen_signal
        assert policy.suppressed_signals == 0


def test_busy_intervals_cover_positions_and_live_pending_orders():
    class FakeEvent:
        def __init__(self, created, fill, expiry, setup):
            self.created_time, self.fill_time = created, fill
            self.expiry_time, self.setup_id = expiry, setup

    class FakeSegment:
        order_events = [FakeEvent(STAMP, None, STAMP + pd.Timedelta(minutes=30), "X"),
                        FakeEvent(STAMP + pd.Timedelta(days=1),
                                  STAMP + pd.Timedelta(days=1, minutes=15),
                                  STAMP + pd.Timedelta(days=1, minutes=30), "X")]

    class FakeResult:
        trade_log = [{"entry_time": (STAMP + pd.Timedelta(days=2)).isoformat(),
                      "exit_time": (STAMP + pd.Timedelta(days=2, hours=1)).isoformat()}]
        legacy_segment_results = [FakeSegment()]

    intervals = variants.busy_intervals(FakeResult())
    assert len(intervals) == 3
    #--- an unfilled order stays busy until expiry; a filled one until the fill
    assert intervals[0] == (STAMP, STAMP + pd.Timedelta(minutes=30))
    assert intervals[1][1] == STAMP + pd.Timedelta(days=1, minutes=15)


# --- the contention ledger ------------------------------------------------------------


def _trade(setup, entry, exit_, r):
    return {"setup_id": setup, "direction": "SHORT", "entry_time": entry,
            "exit_time": exit_, "realized_r": r, "pnl": r * 100,
            "entry_price": 1.0, "exit_price": 2.0}


class _Result:
    def __init__(self, trades, events=()):
        self.trade_log = list(trades)

        class Segment:
            order_events = list(events)

        self.legacy_segment_results = [Segment()]


def test_the_ledger_separates_a_same_bar_displacement_from_a_later_block():
    t0 = pd.Timestamp("2024-01-01T00:00:00Z")
    hour = pd.Timedelta(hours=1)
    #--- D2 opens first and is still holding when the T3 setup would have fired.
    baseline = _Result([_trade(T3_SETUP_ID, (t0 + 2 * hour).isoformat(),
                               (t0 + 3 * hour).isoformat(), 3.0)])
    combined = _Result([_trade(D2_SETUP_ID, t0.isoformat(),
                               (t0 + 4 * hour).isoformat(), 1.0)])
    standalone = _Result(combined.trade_log)
    ledger = phase_e.contention_ledger(baseline, combined, standalone)
    assert ledger["d2_blocks_later_t3"]["count"] == 1
    assert ledger["d2_blocks_later_t3"]["total_r"] == pytest.approx(3.0)
    assert ledger["d2_displaces_t3"]["count"] == 0
    assert ledger["d2_additive"]["count"] == 0


def test_the_ledger_counts_a_non_overlapping_d2_trade_as_additive():
    t0 = pd.Timestamp("2024-01-01T00:00:00Z")
    day = pd.Timedelta(days=1)
    baseline = _Result([_trade(T3_SETUP_ID, t0.isoformat(), (t0 + day).isoformat(), 3.0)])
    combined = _Result(baseline.trade_log + [
        _trade(D2_SETUP_ID, (t0 + 5 * day).isoformat(), (t0 + 6 * day).isoformat(), 2.0)])
    ledger = phase_e.contention_ledger(baseline, combined, _Result(combined.trade_log))
    assert ledger["d2_additive"]["count"] == 1
    assert ledger["d2_additive"]["total_r"] == pytest.approx(2.0)
    assert ledger["d2_blocks_later_t3"]["count"] == 0


def test_the_ledger_records_d2_trades_the_frozen_pair_prevented():
    t0 = pd.Timestamp("2024-01-01T00:00:00Z")
    day = pd.Timedelta(days=1)
    frozen = _trade(T3_SETUP_ID, t0.isoformat(), (t0 + day).isoformat(), 3.0)
    baseline = _Result([frozen])
    combined = _Result([frozen])
    standalone = _Result([_trade(D2_SETUP_ID, (t0 + pd.Timedelta(hours=2)).isoformat(),
                                 (t0 + pd.Timedelta(hours=6)).isoformat(), -1.0)])
    ledger = phase_e.contention_ledger(baseline, combined, standalone)
    assert ledger["baseline_blocks_d2_open_position"]["count"] == 1
    assert ledger["baseline_blocks_d2_open_position"]["total_r"] == pytest.approx(-1.0)


def test_every_ledger_class_reports_a_count_and_an_r_consequence():
    ledger = phase_e.contention_ledger(_Result([]), _Result([]), _Result([]))
    expected = {"d2_additive", "d2_displaces_t3", "d2_displaces_a4",
                "d2_blocks_later_t3", "d2_blocks_later_a4",
                "baseline_blocks_d2_open_position", "baseline_blocks_d2_pending_order",
                "baseline_trade_lost_other"}
    assert set(ledger) == expected
    for entry in ledger.values():
        assert entry["count"] == 0 and entry["total_r"] == 0


# --- the split -------------------------------------------------------------------------


@pytest.mark.parametrize("strategy_id", sorted(variants.PHASE_E_STRATEGY_IDS))
def test_every_phase_e_config_stops_before_the_holdout(strategy_id):
    config = phase_e.development_config(strategy_id)
    assert config.end_date == DEVELOPMENT_END < HOLDOUT_START
    assert config.risk_reward_ratio == 3.0


def test_running_past_the_split_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(phase_e, "HOLDOUT_START", DEVELOPMENT_END)
    with pytest.raises(ValueError, match="holdout"):
        phase_e.run_arm(variants.POLICY_IDS["POLICY1"], tmp_path / "x.sqlite3")


def test_no_rolling_window_reaches_the_holdout():
    for length in (3, 6):
        for window in phase_e.rolling(length, [], [], [], [])["windows"]:
            assert pd.Timestamp(window["end"]) <= DEVELOPMENT_END


# --- registration and protected sources --------------------------------------------------


def test_the_phase_e_arms_exist_only_in_the_private_registry():
    assert len(variants.PHASE_E_STRATEGY_IDS) == 20
    registry = variants.phase_e_registry()
    for strategy_id in variants.PHASE_E_STRATEGY_IDS:
        assert registry.get(strategy_id).metadata.status.value == "RESEARCH"
    assert not any(d.metadata.strategy_id.startswith("RESEARCH_")
                   for d in discover_builtin_strategies().all())


def test_the_production_catalog_does_not_expose_the_phase_e_arms():
    script = (
        "import strategies.btc_core_v2_phase_e_variants;"
        "from strategies.registry import discover_builtin_strategies;"
        "ids = [d.metadata.strategy_id for d in discover_builtin_strategies().all()];"
        "print(any(i.startswith('RESEARCH_') for i in ids))"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "False", proc.stdout


@pytest.mark.parametrize("module,digest", (
    ("btc_v3_a4_pullback_long.py", "55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9"),
    ("btc_v3_t3_breakout_short.py", "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910"),
    ("btc_v3_core_v1.py", "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"),
))
def test_protected_source_files_are_byte_for_byte_unchanged(module, digest):
    assert sha256((ROOT / "strategies" / module).read_bytes()).hexdigest() == digest

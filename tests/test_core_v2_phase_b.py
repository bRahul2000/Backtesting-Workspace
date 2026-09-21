"""BTC Core V2 Phase B — confirmation-timing and structure-lookback wrappers.

Experiment A rests on a correction, so the mechanism is pinned here rather than
assumed: A4 has no one-bar confirmation window. An armed pullback waits until
the frozen invalidation rules clear it, so a bounded window is *tighter* than
the frozen behaviour. These tests prove the window does exactly what it claims
— withdraw the confirmation opportunity after N bars, touching nothing else.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from research import core_v2_phase_b as phase_b
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies import btc_core_v2_phase_b_variants as variants
import strategies.btc_v3_a4_pullback_long as a4_module
from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen, frozen_parameters
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.registry import StrategyRegistry, discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
EQUIV_START = pd.Timestamp("2024-01-01", tz="UTC")
EQUIV_END = pd.Timestamp("2024-07-01", tz="UTC")

FROZEN_VS_BASELINE = (
    ("BTC_V3_A4_PULLBACK_LONG_FROZEN", "RESEARCH_A4_WINDOW_UNBOUNDED"),
    ("BTC_V3_T3_BREAKOUT_SHORT_FROZEN", "RESEARCH_T3_LOOKBACK_05"),
    ("BTC_V3_CORE_V1_FROZEN", "RESEARCH_CORE_A4_WINDOW_UNBOUNDED"),
    ("BTC_V3_CORE_V1_FROZEN", "RESEARCH_CORE_T3_LOOKBACK_05"),
)


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        return phase_b.dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


def _run(strategy_id: str, ledger: Path, registry=None):
    config = replace(phase_b.phase_b_config(strategy_id),
                     start_date=EQUIV_START, end_date=EQUIV_END)
    return run_universal_backtest(phase_b.dataset_path(), config, ledger_path=ledger,
                                  registry=registry or variants.phase_b_registry())


# --- the baseline arms are the frozen strategies ------------------------------


@pytest.mark.parametrize("frozen_id,baseline_id", FROZEN_VS_BASELINE)
def test_the_baseline_arm_is_identical_to_the_frozen_strategy(
        dataset_available, tmp_path, frozen_id, baseline_id):
    frozen = _run(frozen_id, tmp_path / "a.sqlite3")
    baseline = _run(baseline_id, tmp_path / "b.sqlite3")
    assert baseline.trade_log == frozen.trade_log
    assert baseline.profit_factor == frozen.profit_factor


def test_the_frozen_a4_wait_is_unbounded_not_one_bar():
    """The premise the arm corrects: there is no one-bar window to widen."""
    assert variants.A4_BASELINE_WINDOW is variants.UNBOUNDED is None
    assert variants.A4ConfirmationWindowVariant().window_bars is None


# --- the window mechanism ------------------------------------------------------


@pytest.mark.parametrize("window,bars,expected", (
    (1, 1, False),   # the pullback's own start bar; the test will see bars=2
    (1, 2, True),
    (2, 1, False), (2, 2, False), (2, 3, True),
    (3, 1, False), (3, 2, False), (3, 3, False), (3, 4, True),
    (None, 99, False),
))
def test_the_window_withdraws_confirmation_exactly_after_n_testable_bars(
        window, bars, expected, monkeypatch):
    """pullback_bars is incremented before the frozen confirmation test."""
    variant = variants.A4ConfirmationWindowVariant(window)
    variant.pullback_active = True
    variant.pullback_bars = bars
    seen = {}

    def fake_on_candle(self, candle):
        seen["declined"] = a4_module.confirmation_passes(candle, None, 0.0, 0.0, self.params) is False
        seen["patched"] = a4_module.confirmation_passes is not original
        return None

    original = a4_module.confirmation_passes
    monkeypatch.setattr(BtcV3A4PullbackLongFrozen, "on_candle", fake_on_candle)
    variant.on_candle(object())
    assert seen["patched"] is expected


def test_the_confirmation_predicate_is_restored_after_every_bar():
    """A leaked patch would silently disable confirmation for other strategies."""
    original = a4_module.confirmation_passes
    variant = variants.A4ConfirmationWindowVariant(1)
    variant.pullback_active, variant.pullback_bars = True, 99
    with variants._confirmation_withdrawn(True):
        assert a4_module.confirmation_passes is not original
    assert a4_module.confirmation_passes is original
    with pytest.raises(RuntimeError):
        with variants._confirmation_withdrawn(True):
            raise RuntimeError("boom")
    assert a4_module.confirmation_passes is original


@pytest.mark.parametrize("window", (1, 2, 3))
def test_no_signal_is_emitted_past_the_window_on_real_data(dataset_available, tmp_path, window):
    """Read the age of every confirmation the arm actually produced."""
    created = []

    def factory():
        strategy = variants.A4ConfirmationWindowVariant(window)
        created.append(strategy)
        return strategy

    base = variants.phase_b_registry().get(variants.A4_WINDOW_IDS[window])
    registry = StrategyRegistry()
    registry.register(replace(base, factory=factory))
    _run(variants.A4_WINDOW_IDS[window], tmp_path / "w.sqlite3", registry=registry)
    ages = [diag["pullback_bars"] for strategy in created
            for diag in strategy.signal_diagnostics.values()]
    assert ages, "the arm produced no signal to check"
    assert max(ages) <= window + 1
    assert min(ages) >= 2


def test_the_unbounded_baseline_confirms_well_past_any_window(dataset_available, tmp_path):
    """If every confirmation were early the experiment would be meaningless."""
    created = []

    def factory():
        strategy = BtcV3A4PullbackLongFrozen()
        created.append(strategy)
        return strategy

    base = discover_builtin_strategies().get("BTC_V3_A4_PULLBACK_LONG_FROZEN")
    registry = StrategyRegistry()
    registry.register(replace(base, factory=factory))
    _run("BTC_V3_A4_PULLBACK_LONG_FROZEN", tmp_path / "u.sqlite3", registry=registry)
    ages = [diag["pullback_bars"] for strategy in created
            for diag in strategy.signal_diagnostics.values()]
    assert max(ages) > 4, "frozen A4 should confirm late as well as early"


def test_a_window_only_ever_removes_a4_confirmations(dataset_available, tmp_path):
    counts = {}
    for window in (1, 2, 3, None):
        result = _run(variants.A4_WINDOW_IDS[window], tmp_path / f"c{window}.sqlite3")
        counts[window] = sum(1 for row in result.trade_log if row["direction"] == "LONG")
    assert counts[1] <= counts[2] <= counts[3] <= counts[None]


# --- exactly one thing moves ---------------------------------------------------


@pytest.mark.parametrize("window", variants.A4_CONFIRMATION_WINDOWS)
def test_the_a4_window_arm_changes_no_parameter_at_all(window):
    assert asdict(variants.A4ConfirmationWindowVariant(window).params) == asdict(frozen_parameters())


@pytest.mark.parametrize("lookback", variants.T3_STRUCTURE_LOOKBACKS)
def test_the_t3_arm_moves_only_the_structure_lookback(lookback):
    frozen, variant = V3T3FrozenParameters(), variants.T3StructureLookbackVariant(lookback).params
    assert variant.trend_structure_lookback == lookback
    for name in V3T3FrozenParameters.__dataclass_fields__:
        if name == "trend_structure_lookback":
            continue
        assert getattr(variant, name) == getattr(frozen, name), name


def test_phase_a_conclusions_are_carried_into_every_phase_b_arm():
    """Body thresholds stay at 0.70 and the reward multiple stays at 3R."""
    for window in variants.A4_CONFIRMATION_WINDOWS:
        params = variants.A4ConfirmationWindowVariant(window).params
        assert params.confirmation_min_body_percent == 0.70
        assert params.reward_multiple == 3.0
    for lookback in variants.T3_STRUCTURE_LOOKBACKS:
        params = variants.T3StructureLookbackVariant(lookback).params
        assert params.trend_minimum_body_percent == 0.70
        assert params.reward_multiple == 3.0


def test_the_t3_lookback_changes_which_low_must_break():
    """Break semantics are untouched; only how far back the low is taken."""
    from engine.models import Candle

    lows = [100.0, 90.0, 95.0, 96.0, 97.0]
    candles = [Candle(pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i),
                      100.0, 101.0, low, 100.0, 1.0) for i, low in enumerate(lows)]
    for lookback, expected in ((5, 90.0), (3, 95.0)):
        variant = variants.T3StructureLookbackVariant(lookback)
        prior = candles[-lookback:]
        assert min(bar.low for bar in prior) == expected
        assert variant.params.trend_structure_lookback == lookback


def test_the_core_arm_keeps_the_other_child_frozen():
    core = variants.CoreV2PhaseBVariant(a4_window=2)
    assert core.a4.window_bars == 2
    assert core.t3.params.trend_structure_lookback == 5
    core = variants.CoreV2PhaseBVariant(t3_lookback=3)
    assert core.a4.window_bars is None
    assert core.t3.params.trend_structure_lookback == 3


def test_the_variants_subclass_the_frozen_strategies():
    assert issubclass(variants.A4ConfirmationWindowVariant, BtcV3A4PullbackLongFrozen)
    assert issubclass(variants.T3StructureLookbackVariant, BtcV3T3BreakoutShortFrozen)
    assert issubclass(variants.CoreV2PhaseBVariant, BtcV3CoreV1Frozen)


@pytest.mark.parametrize("bad", (0, -1, 1.5, True))
def test_an_invalid_window_is_refused(bad):
    with pytest.raises(ValueError):
        variants.A4ConfirmationWindowVariant(bad)


@pytest.mark.parametrize("bad", (0, -3))
def test_an_invalid_lookback_is_refused_by_the_frozen_validator(bad):
    with pytest.raises(ValueError):
        variants.T3StructureLookbackVariant(bad)


# --- the split ------------------------------------------------------------------


@pytest.mark.parametrize("strategy_id", sorted(variants.PHASE_B_STRATEGY_IDS))
def test_every_phase_b_config_stops_before_the_holdout(strategy_id):
    config = phase_b.phase_b_config(strategy_id)
    assert config.end_date == DEVELOPMENT_END < HOLDOUT_START
    assert config.dataset_role.value == "DEVELOPMENT"
    assert config.risk_reward_ratio == 3.0


def test_running_past_the_split_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(phase_b, "HOLDOUT_START", DEVELOPMENT_END)
    with pytest.raises(ValueError, match="holdout"):
        phase_b.run_arm("RESEARCH_A4_WINDOW_UNBOUNDED", tmp_path / "x.sqlite3")


# --- analysis --------------------------------------------------------------------


def _row(entry, r, pnl, mfe_r=None, mae_r=None):
    return {"setup_id": "A", "direction": "SHORT", "entry_time": entry, "realized_r": r,
            "pnl": pnl, "entry_price": 1.0, "exit_price": 2.0, "mfe_r": mfe_r,
            "mae_r": mae_r, "mfe_amount": 10.0, "mae_amount": 5.0,
            "capture_efficiency": 0.5, "excursion_model": "BAR_BASED_APPROXIMATION"}


def test_excursions_summarise_how_far_trades_travelled():
    rows = [_row("2024-01-01T00:00:00Z", 3.0, 300.0, mfe_r=3.2, mae_r=0.4),
            _row("2024-02-01T00:00:00Z", -1.0, -100.0, mfe_r=0.8, mae_r=1.0)]
    stats = phase_b.excursions(rows)
    assert stats["mfe_r"] == pytest.approx(2.0)
    assert stats["mae_r"] == pytest.approx(0.7)
    assert stats["reached_1r"] == 1
    assert stats["reached_2r"] == 1
    assert stats["model"] == "BAR_BASED_APPROXIMATION"


def test_excursions_handle_missing_values_without_inventing_any():
    stats = phase_b.excursions([_row("2024-01-01T00:00:00Z", 1.0, 1.0)])
    assert stats["mfe_r"] is None and stats["reached_1r"] == 0
    assert phase_b.excursions([])["trades"] == 0


def test_yearly_breakdown_groups_by_entry_year_in_either_encoding():
    stamp = pd.Timestamp("2024-05-05T00:00:00Z")
    rows = [_row(stamp.isoformat(), 3.0, 300.0), _row(stamp.value, -1.0, -100.0),
            _row("2025-02-02T00:00:00Z", 1.0, 100.0)]
    yearly = phase_b.yearly_breakdown(rows)
    assert yearly["2024"]["trades"] == 2
    assert yearly["2024"]["total_r"] == pytest.approx(2.0)
    assert yearly["2025"]["trades"] == 1


def test_describe_with_excursions_keeps_the_phase_a_fields():
    stream = phase_b.describe_with_excursions([_row("2024-01-01T00:00:00Z", 3.0, 300.0, 3.1, 0.2)])
    assert stream["trades"] == 1 and stream["total_r"] == pytest.approx(3.0)
    assert stream["excursions"]["reached_2r"] == 1


# --- registration ----------------------------------------------------------------


def test_all_sixteen_phase_b_arms_exist_in_the_private_registry():
    assert len(variants.PHASE_B_STRATEGY_IDS) == 16
    registry = variants.phase_b_registry()
    for strategy_id in variants.PHASE_B_STRATEGY_IDS:
        assert registry.get(strategy_id).metadata.status.value == "RESEARCH"


def test_building_the_private_registry_never_mutates_the_global_one():
    before = [d.metadata.strategy_id for d in discover_builtin_strategies().all()]
    variants.phase_b_registry()
    after = [d.metadata.strategy_id for d in discover_builtin_strategies().all()]
    assert after == before
    assert not any(sid.startswith("RESEARCH_") for sid in after)


def test_the_production_catalog_does_not_expose_the_phase_b_arms():
    script = (
        "import strategies.btc_core_v2_phase_b_variants;"
        "from strategies.registry import discover_builtin_strategies;"
        "ids = [d.metadata.strategy_id for d in discover_builtin_strategies().all()];"
        "print(any(i.startswith('RESEARCH_') for i in ids))"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "False", proc.stdout


# --- the frozen strategies are untouched ------------------------------------------


@pytest.mark.parametrize("module,digest", (
    ("btc_v3_a4_pullback_long.py", "55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9"),
    ("btc_v3_t3_breakout_short.py", "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910"),
    ("btc_v3_core_v1.py", "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"),
))
def test_protected_source_files_are_byte_for_byte_unchanged(module, digest):
    assert sha256((ROOT / "strategies" / module).read_bytes()).hexdigest() == digest

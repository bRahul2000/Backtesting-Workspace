"""BTC Core V2 Phase A — body-threshold ablation wrappers and analysis.

The ablation is only worth anything if each wrapper moves exactly one number and
nothing else. These tests pin that: at the frozen default every wrapper must be
indistinguishable from the frozen strategy on real data, every other parameter
must still equal the frozen value, and Phase A must never read the holdout.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from research import core_v2_phase_a as phase_a
from strategies import btc_core_v2_variants as variants
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen, CONFIRMATION_MAX_BODY_PERCENT, frozen_parameters,
)
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]

#--- A window inside DEVELOPMENT, long enough to produce trades on both sides.
EQUIV_START = pd.Timestamp("2024-01-01", tz="UTC")
EQUIV_END = pd.Timestamp("2024-07-01", tz="UTC")

FROZEN_VS_VARIANT = (
    ("BTC_V3_A4_PULLBACK_LONG_FROZEN", "RESEARCH_A4_BODY_070"),
    ("BTC_V3_T3_BREAKOUT_SHORT_FROZEN", "RESEARCH_T3_BODY_070"),
    ("BTC_V3_CORE_V1_FROZEN", "RESEARCH_CORE_A4_BODY_070"),
    ("BTC_V3_CORE_V1_FROZEN", "RESEARCH_CORE_T3_BODY_070"),
)


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        return phase_a.dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


def _run(strategy_id: str, ledger: Path):
    config = replace(phase_a.development_config(strategy_id),
                     start_date=EQUIV_START, end_date=EQUIV_END)
    return run_universal_backtest(phase_a.dataset_path(), config, ledger_path=ledger,
                                  registry=variants.phase_a_registry())


# --- the wrappers are the frozen strategies at the frozen default -------------


@pytest.mark.parametrize("frozen_id,variant_id", FROZEN_VS_VARIANT)
def test_the_baseline_arm_is_identical_to_the_frozen_strategy(
        dataset_available, tmp_path, frozen_id, variant_id):
    frozen = _run(frozen_id, tmp_path / "a.sqlite3")
    variant = _run(variant_id, tmp_path / "b.sqlite3")
    assert variant.trade_log == frozen.trade_log
    assert variant.total_trades == frozen.total_trades
    assert variant.profit_factor == frozen.profit_factor
    assert variant.average_r == frozen.average_r
    assert variant.max_drawdown_percent == frozen.max_drawdown_percent


# --- exactly one parameter moves ---------------------------------------------


@pytest.mark.parametrize("value", variants.BODY_THRESHOLDS)
def test_a4_variant_moves_only_the_confirmation_body_minimum(value):
    frozen, variant = asdict(frozen_parameters()), asdict(
        variants.A4ConfirmationBodyVariant(value).params)
    assert variant.pop("confirmation_min_body_percent") == value
    frozen.pop("confirmation_min_body_percent")
    assert variant == frozen


@pytest.mark.parametrize("value", variants.BODY_THRESHOLDS)
def test_t3_variant_moves_only_the_trend_body_minimum(value):
    fields = [f for f in V3T3FrozenParameters.__dataclass_fields__]
    frozen, variant = V3T3FrozenParameters(), variants.T3BreakoutBodyVariant(value).params
    assert getattr(variant, "trend_minimum_body_percent") == value
    for name in fields:
        if name == "trend_minimum_body_percent":
            continue
        assert getattr(variant, name) == getattr(frozen, name), name


def test_the_a4_upper_body_cap_is_not_part_of_this_ablation():
    assert variants.UPPER_BODY_CAP == CONFIRMATION_MAX_BODY_PERCENT == 0.90
    for value in variants.BODY_THRESHOLDS:
        variant = variants.A4ConfirmationBodyVariant(value)
        assert variant.params.confirmation_min_body_percent <= 0.90


@pytest.mark.parametrize("value", variants.BODY_THRESHOLDS)
def test_the_reward_multiple_stays_at_three_r(value):
    assert variants.A4ConfirmationBodyVariant(value).params.reward_multiple == 3.0
    assert variants.T3BreakoutBodyVariant(value).params.reward_multiple == 3.0


def test_the_core_variant_keeps_the_other_child_frozen():
    core = variants.CoreV2BodyVariant(a4_body=0.40)
    assert core.a4.params.confirmation_min_body_percent == 0.40
    assert core.t3.params.trend_minimum_body_percent == 0.70
    frozen = V3T3FrozenParameters()
    for name in V3T3FrozenParameters.__dataclass_fields__:
        assert getattr(core.t3.params, name) == getattr(frozen, name), name
    core = variants.CoreV2BodyVariant(t3_body=0.40)
    assert core.t3.params.trend_minimum_body_percent == 0.40
    assert asdict(core.a4.params) == asdict(frozen_parameters())


def test_the_variants_subclass_the_frozen_strategies():
    """Inheritance is what guarantees every unlisted rule is the frozen one."""
    assert issubclass(variants.A4ConfirmationBodyVariant, BtcV3A4PullbackLongFrozen)
    assert issubclass(variants.T3BreakoutBodyVariant, BtcV3T3BreakoutShortFrozen)
    assert issubclass(variants.CoreV2BodyVariant, BtcV3CoreV1Frozen)


def test_an_out_of_range_threshold_is_refused_by_the_frozen_validator():
    with pytest.raises(ValueError):
        variants.A4ConfirmationBodyVariant(0.0)
    with pytest.raises(ValueError):
        variants.T3BreakoutBodyVariant(1.5)


# --- the locked split ---------------------------------------------------------


def test_the_development_and_holdout_splits_are_locked_and_disjoint():
    assert phase_a.DEVELOPMENT_START == pd.Timestamp("2023-11-10 23:15", tz="UTC")
    assert phase_a.DEVELOPMENT_END == pd.Timestamp("2025-06-30 23:45", tz="UTC")
    assert phase_a.HOLDOUT_START == pd.Timestamp("2025-07-01 00:00", tz="UTC")
    assert phase_a.HOLDOUT_END == pd.Timestamp("2026-09-20 07:15", tz="UTC")
    assert phase_a.DEVELOPMENT_END < phase_a.HOLDOUT_START


@pytest.mark.parametrize("strategy_id", sorted(variants.PHASE_A_STRATEGY_IDS))
def test_every_phase_a_config_stops_before_the_holdout(strategy_id):
    config = phase_a.development_config(strategy_id)
    assert config.end_date < phase_a.HOLDOUT_START
    assert config.dataset_role.value == "DEVELOPMENT"
    assert config.risk_reward_ratio == 3.0


def test_running_past_the_split_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(phase_a, "DEVELOPMENT_END", phase_a.HOLDOUT_START)
    with pytest.raises(ValueError, match="holdout"):
        phase_a.run_arm("RESEARCH_A4_BODY_070", tmp_path / "x.sqlite3")


def test_the_dataset_fingerprint_is_verified(monkeypatch):
    monkeypatch.setattr(phase_a, "DATASET_FINGERPRINT", "0" * 64)
    with pytest.raises(ValueError, match="fingerprint"):
        phase_a.dataset_path()


# --- analysis -----------------------------------------------------------------


def _trade(entry: str, r: float, pnl: float, setup: str = "A", side: str = "LONG",
           entry_price: float = 1.0, exit_price: float = 2.0) -> dict:
    return {"setup_id": setup, "direction": side, "entry_time": entry, "realized_r": r,
            "pnl": pnl, "entry_price": entry_price, "exit_price": exit_price}


def test_trade_delta_separates_added_displaced_and_common():
    baseline = [_trade("2024-01-05T10:00:00Z", 3.0, 300.0),
                _trade("2024-02-05T10:00:00Z", -1.0, -100.0)]
    variant = [_trade("2024-01-05T10:00:00Z", 3.0, 300.0),
               _trade("2024-01-20T10:00:00Z", -1.0, -100.0)]
    delta = phase_a.trade_delta(baseline, variant)
    assert [row["entry_time"] for row in delta.added] == ["2024-01-20T10:00:00Z"]
    assert [row["entry_time"] for row in delta.displaced] == ["2024-02-05T10:00:00Z"]
    assert len(delta.common) == 1
    assert delta.changed == []


def test_trade_delta_flags_a_common_trade_that_executed_differently():
    baseline = [_trade("2024-01-05T10:00:00Z", 3.0, 300.0, exit_price=2.0)]
    variant = [_trade("2024-01-05T10:00:00Z", 3.0, 300.0, exit_price=2.5)]
    assert len(phase_a.trade_delta(baseline, variant).changed) == 1


def test_trade_delta_matches_integer_and_iso_timestamps_alike():
    """trade_log timestamps arrive as epoch nanoseconds, not ISO strings."""
    stamp = pd.Timestamp("2024-01-05T10:00:00Z")
    baseline = [_trade(stamp.value, 3.0, 300.0)]
    variant = [_trade(stamp.isoformat(), 3.0, 300.0)]
    delta = phase_a.trade_delta(baseline, variant)
    assert delta.added == [] and delta.displaced == []
    assert len(delta.common) == 1


def test_describe_stream_reports_expectancy_and_months():
    rows = [_trade("2024-01-05T10:00:00Z", 3.0, 300.0),
            _trade("2024-01-20T10:00:00Z", -1.0, -100.0),
            _trade("2024-03-02T10:00:00Z", -1.0, -100.0)]
    stream = phase_a.describe_stream(rows)
    assert stream["trades"] == 3
    assert stream["total_r"] == pytest.approx(1.0)
    assert stream["average_r"] == pytest.approx(1 / 3)
    assert stream["profit_factor"] == pytest.approx(1.5)
    assert stream["win_rate"] == pytest.approx(100 / 3)
    assert sorted(stream["months"]) == ["2024-01", "2024-03"]
    assert stream["months"]["2024-01"]["trades"] == 2
    assert stream["max_losing_streak"] == 2


def test_describe_stream_handles_an_empty_stream():
    stream = phase_a.describe_stream([])
    assert stream["trades"] == 0 and stream["total_r"] == 0.0
    assert stream["profit_factor"] is None


def test_max_drawdown_of_a_stream_is_peak_to_trough_in_time_order():
    rows = [_trade("2024-01-01T00:00:00Z", 3.0, 300.0),
            _trade("2024-01-02T00:00:00Z", -1.0, -100.0),
            _trade("2024-01-03T00:00:00Z", -1.0, -100.0)]
    assert phase_a._max_drawdown_r(rows) == pytest.approx(-2.0)
    assert phase_a._max_drawdown_r(list(reversed(rows))) == pytest.approx(-2.0)


def test_concentration_does_not_report_a_share_of_a_negative_total():
    """A best month as a share of a losing total reads as if the best month hurt."""
    losing = phase_a.describe_stream([_trade("2024-01-01T00:00:00Z", 1.0, 100.0),
                                      _trade("2024-02-01T00:00:00Z", -3.0, -300.0)])
    assert phase_a.concentration(losing)["share_of_total_r"] is None
    winning = phase_a.describe_stream([_trade("2024-01-01T00:00:00Z", 3.0, 300.0),
                                       _trade("2024-02-01T00:00:00Z", 1.0, 100.0)])
    result = phase_a.concentration(winning)
    assert result["share_of_total_r"] == pytest.approx(75.0)
    assert result["best_month"] == "2024-01"
    assert result["worst_month"] == "2024-02"


# --- registration -------------------------------------------------------------


def test_all_sixteen_arms_exist_in_the_private_registry():
    assert len(variants.PHASE_A_STRATEGY_IDS) == 16
    registry = variants.phase_a_registry()
    for strategy_id in variants.PHASE_A_STRATEGY_IDS:
        descriptor = registry.get(strategy_id)
        assert descriptor.metadata.status.value == "RESEARCH"
        assert descriptor.warmup_resolver is not None


def test_the_private_registry_also_carries_the_frozen_strategies():
    registry = variants.phase_a_registry()
    for strategy_id in ("BTC_V3_A4_PULLBACK_LONG_FROZEN",
                        "BTC_V3_T3_BREAKOUT_SHORT_FROZEN", "BTC_V3_CORE_V1_FROZEN"):
        assert registry.get(strategy_id).metadata.status.value == "FROZEN"


def test_building_the_private_registry_never_mutates_the_global_one():
    """The global registry is what the workspace dropdown lists."""
    before = [d.metadata.strategy_id for d in discover_builtin_strategies().all()]
    variants.phase_a_registry()
    variants.phase_a_registry()
    after = [d.metadata.strategy_id for d in discover_builtin_strategies().all()]
    assert after == before
    assert not any(sid.startswith("RESEARCH_") for sid in after)


def test_the_production_catalog_does_not_expose_the_research_arms():
    """Even importing the ablation module must not reach the workspace list."""
    script = (
        "import strategies.btc_core_v2_variants;"
        "from strategies.registry import discover_builtin_strategies;"
        "ids = [d.metadata.strategy_id for d in discover_builtin_strategies().all()];"
        "print(any(i.startswith('RESEARCH_') for i in ids))"
    )
    proc = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          capture_output=True, text=True, check=True)
    assert proc.stdout.strip() == "False", proc.stdout


def test_arms_fingerprint_distinctly_so_runs_cannot_be_confused():
    from strategies.base_strategy import effective_parameter_payload, parameter_fingerprint

    registry = variants.phase_a_registry()
    seen = set()
    for family in (variants.A4_VARIANT_IDS, variants.T3_VARIANT_IDS,
                   variants.CORE_A4_VARIANT_IDS, variants.CORE_T3_VARIANT_IDS):
        prints = {parameter_fingerprint(effective_parameter_payload(registry.get(sid)))
                  for sid in family.values()}
        assert len(prints) == len(family)
        seen |= prints
    assert len(seen) >= 8


# --- the frozen strategies are untouched --------------------------------------


@pytest.mark.parametrize("module,digest", (
    ("btc_v3_a4_pullback_long.py", "55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9"),
    ("btc_v3_t3_breakout_short.py", "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910"),
    ("btc_v3_core_v1.py", "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"),
))
def test_protected_source_files_are_byte_for_byte_unchanged(module, digest):
    assert sha256((ROOT / "strategies" / module).read_bytes()).hexdigest() == digest


def test_no_variant_module_mutates_a_frozen_parameter_object():
    """A shared frozen defaults object would leak one arm's threshold into another."""
    first = variants.A4ConfirmationBodyVariant(0.40)
    second = variants.A4ConfirmationBodyVariant(0.70)
    assert first.params.confirmation_min_body_percent == 0.40
    assert second.params.confirmation_min_body_percent == 0.70
    assert frozen_parameters().confirmation_min_body_percent == 0.70
    t3_first = variants.T3BreakoutBodyVariant(0.40)
    t3_second = variants.T3BreakoutBodyVariant(0.70)
    assert t3_first.params.trend_minimum_body_percent == 0.40
    assert t3_second.params.trend_minimum_body_percent == 0.70
    assert V3T3FrozenParameters().trend_minimum_body_percent == 0.70

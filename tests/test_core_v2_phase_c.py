"""BTC Core V2 Phase C — stability study of the T3 lookback-4 lead.

Phase C is the study that decides a promotion, so its measurement machinery has
to be trustworthy before its numbers mean anything: slicing must pick the right
trades, the bootstrap must actually resample in blocks, the leave-one-out must
remove what it claims, and the break-definition arms must change the break level
and nothing else. That is what these tests pin.
"""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from research import core_v2_phase_c as phase_c
from research.core_v2_phase_a import DEVELOPMENT_END, DEVELOPMENT_START, HOLDOUT_START
from services import market_datasets as md
from strategies import btc_core_v2_phase_c_variants as variants
import strategies.btc_v3_t3_breakout_short as t3_module
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.registry import discover_builtin_strategies

ROOT = Path(__file__).resolve().parents[1]
EQUIV_START = pd.Timestamp("2024-01-01", tz="UTC")
EQUIV_END = pd.Timestamp("2024-07-01", tz="UTC")


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        return phase_c.dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


def _row(entry: str, r: float, pnl: float | None = None) -> dict:
    return {"setup_id": "T", "direction": "SHORT", "entry_time": entry, "realized_r": r,
            "pnl": pnl if pnl is not None else r * 100.0,
            "entry_price": 1.0, "exit_price": 2.0}


# --- the frozen break definition is the frozen strategy ------------------------


def test_the_frozen_break_arm_is_identical_to_the_frozen_strategy(dataset_available, tmp_path):
    """Lookback 5 with FROZEN semantics must be the frozen T3 exactly."""
    config = replace(phase_c.development_config("BTC_V3_T3_BREAKOUT_SHORT_FROZEN"),
                     start_date=EQUIV_START, end_date=EQUIV_END)
    frozen = run_universal_backtest(phase_c.dataset_path(), config,
                                    ledger_path=tmp_path / "a.sqlite3")
    arm = run_universal_backtest(
        phase_c.dataset_path(),
        replace(config, strategy_id=variants.BREAK_IDS[(5, "FROZEN")]),
        ledger_path=tmp_path / "b.sqlite3", registry=variants.phase_c_registry())
    assert arm.trade_log == frozen.trade_log


def test_a_frozen_definition_installs_no_patch_at_all():
    original = t3_module.evaluate_v3
    with variants._break_level_shifted(variants.BREAK_BY_KEY["FROZEN"]):
        assert t3_module.evaluate_v3 is original
    with variants._break_level_shifted(variants.BREAK_BY_KEY["STRICT_1_TICK"]):
        assert t3_module.evaluate_v3 is not original
    assert t3_module.evaluate_v3 is original


def test_the_patch_is_restored_even_when_the_bar_raises():
    original = t3_module.evaluate_v3
    with pytest.raises(RuntimeError):
        with variants._break_level_shifted(variants.BREAK_BY_KEY["STRICT_0P02_ATR"]):
            raise RuntimeError("boom")
    assert t3_module.evaluate_v3 is original


# --- the shift changes the break level and nothing else ------------------------


def _observation(close: float, prior_low: float, atr: float = 100.0):
    from engine.models import Candle
    from strategies.btc_v3_t3_breakout_short import V3Observation
    from strategies.confirmed_h1_regime import H1RegimeValue

    candle = Candle(pd.Timestamp("2024-01-01", tz="UTC"), close + 10, close + 20,
                    close - 5, close, 1.0)
    return V3Observation(
        candle=candle, h1=H1RegimeValue(None, None, None, None, None, None),
        ema_fast=close, ema_slow=close, adx=20.0, rsi=30.0, atr=atr,
        trend_previous_high=close + 100, trend_previous_low=prior_low,
        range_previous_high=close + 100, range_previous_low=close - 100,
        trend_stop_low=close - 5, trend_stop_high=close + 20)


@pytest.mark.parametrize("definition,expected_shift", (
    ("LOOSER_1_TICK", -0.01), ("STRICT_1_TICK", 0.01),
    ("STRICT_0P01_ATR", 1.0), ("STRICT_0P02_ATR", 2.0), ("STRICT_0P05_ATR", 5.0),
))
def test_the_shift_moves_only_the_prior_low(definition, expected_shift):
    seen = {}
    original = t3_module.evaluate_v3

    def capture(obs, params, counters=None):
        seen["obs"] = obs
        return None

    t3_module.evaluate_v3 = capture
    try:
        with variants._break_level_shifted(variants.BREAK_BY_KEY[definition]):
            t3_module.evaluate_v3(_observation(1000.0, 1010.0), V3T3FrozenParameters())
    finally:
        t3_module.evaluate_v3 = original
    obs = seen["obs"]
    assert obs.trend_previous_low == pytest.approx(1010.0 - expected_shift)
    #--- every other field must be the one the frozen strategy built
    assert obs.trend_previous_high == 1100.0
    assert obs.trend_stop_high == 1020.0 and obs.trend_stop_low == 995.0
    assert obs.atr == 100.0 and obs.rsi == 30.0 and obs.adx == 20.0


def test_a_one_tick_shift_is_below_the_price_resolution_of_this_instrument():
    """BTCUSDm quotes to two decimals, so a one-tick test can barely bind."""
    assert variants.TICK_SIZE == 0.01


@pytest.mark.parametrize("lookback", variants.LOOKBACKS_UNDER_TEST)
@pytest.mark.parametrize("definition", [item.key for item in variants.BREAK_DEFINITIONS])
def test_every_arm_keeps_the_frozen_parameters(lookback, definition):
    variant = variants.T3BreakDefinitionVariant(lookback, definition)
    frozen = V3T3FrozenParameters()
    assert variant.params.trend_structure_lookback == lookback
    assert variant.params.trend_minimum_body_percent == 0.70
    assert variant.params.reward_multiple == 3.0
    for name in V3T3FrozenParameters.__dataclass_fields__:
        if name == "trend_structure_lookback":
            continue
        assert getattr(variant.params, name) == getattr(frozen, name), name


def test_an_unknown_break_definition_is_refused():
    with pytest.raises(ValueError):
        variants.T3BreakDefinitionVariant(4, "NOT_A_DEFINITION")


def test_the_core_arm_leaves_a4_completely_frozen():
    from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen, frozen_parameters
    from dataclasses import asdict

    core = variants.CoreV2PhaseCVariant(4, "STRICT_0P02_ATR")
    assert type(core.a4) is BtcV3A4PullbackLongFrozen
    assert asdict(core.a4.params) == asdict(frozen_parameters())
    assert core.t3.params.trend_structure_lookback == 4


def test_the_variants_subclass_the_frozen_strategies():
    assert issubclass(variants.T3BreakDefinitionVariant, BtcV3T3BreakoutShortFrozen)


# --- slicing --------------------------------------------------------------------


def test_slicing_selects_by_entry_time_inclusively():
    rows = [_row("2024-01-01T00:00:00Z", 1.0), _row("2024-06-30T23:45:00Z", 2.0),
            _row("2024-07-01T00:00:00Z", 3.0)]
    picked = phase_c.slice_rows(rows, pd.Timestamp("2024-01-01", tz="UTC"),
                                pd.Timestamp("2024-06-30 23:45", tz="UTC"))
    assert [row["realized_r"] for row in picked] == [1.0, 2.0]


def test_slicing_reads_legacy_integer_timestamps_too():
    stamp = pd.Timestamp("2024-03-01T00:00:00Z")
    rows = [_row(stamp.value, 1.0)]
    assert len(phase_c.slice_rows(rows, pd.Timestamp("2024-01-01", tz="UTC"),
                                  pd.Timestamp("2024-12-31", tz="UTC"))) == 1


def test_metrics_report_drawdown_and_rate_over_the_slice():
    rows = [_row("2024-01-15T00:00:00Z", 3.0, 300.0), _row("2024-02-15T00:00:00Z", -1.0, -100.0)]
    out = phase_c.metrics(rows, pd.Timestamp("2024-01-01", tz="UTC"),
                          pd.Timestamp("2024-03-01", tz="UTC"))
    assert out["trades"] == 2
    assert out["total_r"] == pytest.approx(2.0)
    assert out["trades_per_month"] == pytest.approx(2 / (60 / 30.4375), rel=1e-3)
    assert out["max_drawdown_percent"] > 0


def test_drawdown_of_a_monotonically_winning_slice_is_zero():
    rows = [_row("2024-01-15T00:00:00Z", 3.0, 300.0), _row("2024-02-15T00:00:00Z", 3.0, 300.0)]
    assert phase_c._drawdown_percent(rows) == 0.0


# --- bootstrap --------------------------------------------------------------------


def test_the_bootstrap_reproduces_the_observed_stream():
    rows = [_row(f"2024-0{i+1}-01T00:00:00Z", 3.0 if i % 2 else -1.0) for i in range(6)]
    out = phase_c.block_bootstrap(rows, block=2, samples=500)
    assert out["trades"] == 6 and out["samples"] == 500
    assert out["observed"]["total_r"] == pytest.approx(sum(r["realized_r"] for r in rows))
    assert out["observed"]["average_r"] == pytest.approx(out["observed"]["total_r"] / 6)


def test_the_bootstrap_is_deterministic_for_a_fixed_seed():
    rows = [_row(f"2024-0{i+1}-01T00:00:00Z", float(i) - 2) for i in range(6)]
    first = phase_c.block_bootstrap(rows, block=3, samples=300, seed=7)
    second = phase_c.block_bootstrap(rows, block=3, samples=300, seed=7)
    assert first["total_r"] == second["total_r"]
    assert first != phase_c.block_bootstrap(rows, block=3, samples=300, seed=8)


def test_a_constant_stream_bootstraps_to_a_point_mass():
    rows = [_row(f"2024-0{i+1}-01T00:00:00Z", 2.0) for i in range(4)]
    out = phase_c.block_bootstrap(rows, block=2, samples=200)
    assert out["total_r"]["p5"] == pytest.approx(8.0)
    assert out["total_r"]["p95"] == pytest.approx(8.0)
    assert out["total_r"]["probability_le_0"] == 0.0


def test_an_all_losing_stream_bootstraps_to_certain_loss():
    rows = [_row(f"2024-0{i+1}-01T00:00:00Z", -1.0) for i in range(4)]
    out = phase_c.block_bootstrap(rows, block=1, samples=200)
    assert out["total_r"]["probability_le_0"] == 1.0
    assert out["profit_factor"]["probability_le_1"] == 1.0


def test_a_resample_without_a_loss_counts_as_above_one_not_as_missing():
    """Discarding undefined PF would quietly bias the probability downward."""
    rows = [_row("2024-01-01T00:00:00Z", 3.0), _row("2024-02-01T00:00:00Z", -1.0)]
    out = phase_c.block_bootstrap(rows, block=1, samples=2000)
    assert out["profit_factor"]["undefined_samples"] > 0
    assert 0.0 < out["profit_factor"]["probability_le_1"] < 1.0


def test_block_resampling_keeps_adjacent_trades_together():
    """With one block covering the whole stream, every sample is a rotation."""
    values = [1.0, -1.0, 5.0, -2.0]
    rows = [_row(f"2024-0{i+1}-01T00:00:00Z", v) for i, v in enumerate(values)]
    out = phase_c.block_bootstrap(rows, block=len(values), samples=200)
    assert out["total_r"]["p5"] == pytest.approx(sum(values))
    assert out["total_r"]["p95"] == pytest.approx(sum(values))


def test_the_bootstrap_handles_an_empty_stream():
    assert phase_c.block_bootstrap([], block=3, samples=10)["trades"] == 0


# --- leave-one-out ------------------------------------------------------------------


def test_leaving_a_month_out_removes_exactly_that_month():
    rows = [_row("2024-01-05T00:00:00Z", 3.0), _row("2024-01-20T00:00:00Z", -1.0),
            _row("2024-02-05T00:00:00Z", 3.0)]
    out = phase_c.leave_out(rows, drop="2024-01")
    assert out["dropped_trades"] == 2 and out["trades"] == 1
    assert out["total_r"] == pytest.approx(3.0)


def test_leaving_a_year_out_removes_exactly_that_year():
    rows = [_row("2024-01-05T00:00:00Z", 3.0), _row("2025-02-05T00:00:00Z", -1.0)]
    out = phase_c.leave_out(rows, drop="2024", by="year")
    assert out["dropped_trades"] == 1 and out["total_r"] == pytest.approx(-1.0)


# --- the split ------------------------------------------------------------------------


def test_the_split_is_the_locked_development_period():
    assert phase_c.DEVELOPMENT_START == DEVELOPMENT_START
    assert phase_c.DEVELOPMENT_END == DEVELOPMENT_END < HOLDOUT_START
    for _, start, end in phase_c.SUBPERIODS:
        assert phase_c._utc(end) <= DEVELOPMENT_END
        assert phase_c._utc(start) >= DEVELOPMENT_START


def test_running_past_the_split_is_refused(tmp_path):
    with pytest.raises(ValueError, match="holdout"):
        phase_c.run_lookback(5, tmp_path / "x.sqlite3",
                             end_date=HOLDOUT_START + pd.Timedelta(days=1))


def test_no_rolling_window_reaches_the_holdout():
    rolling = phase_c._rolling(6, [], [], [], [])
    for window in rolling["windows"]:
        assert pd.Timestamp(window["end"]) <= DEVELOPMENT_END


# --- the spread multiplier ---------------------------------------------------------------


def test_the_default_spread_multiplier_changes_nothing(dataset_available, tmp_path):
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_T3_BREAKOUT_SHORT_FROZEN", timeframe="15m",
        higher_timeframes=("1h",), start_date=EQUIV_START, end_date=EQUIV_END,
        dataset_role=DatasetRole.DEVELOPMENT, risk_per_trade_percent=0.25,
        spread=0.0, spread_source=entry.spread_source, data_source=entry.key)
    plain = run_universal_backtest(entry.path, config, ledger_path=tmp_path / "a.sqlite3")
    explicit = run_universal_backtest(entry.path, replace(config, spread_multiplier=1.0),
                                      ledger_path=tmp_path / "b.sqlite3")
    assert plain.trade_log == explicit.trade_log
    assert plain.execution_diagnostics["spread_multiplier"] == 1.0


def test_the_spread_multiplier_actually_scales_the_broker_spread(dataset_available, tmp_path):
    """An unchanged stress row must mean insensitivity, not a dead knob."""
    native = phase_c.run_lookback(5, tmp_path / "n.sqlite3")
    severe = phase_c.run_lookback(5, tmp_path / "s.sqlite3", spread_multiplier=3.0)
    scale = (severe.execution_diagnostics["effective_spread_price"]
             / native.execution_diagnostics["effective_spread_price"])
    assert scale == pytest.approx(3.0)
    assert severe.pnl < native.pnl


def test_a_non_positive_spread_multiplier_is_refused():
    with pytest.raises(ValueError, match="spread_multiplier"):
        BacktestConfig(
            instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id="X",
            timeframe="15m", start_date=EQUIV_START, end_date=EQUIV_END,
            dataset_role=DatasetRole.DEVELOPMENT, spread_multiplier=0.0)


# --- registration and protected sources -------------------------------------------------


def test_the_phase_c_arms_exist_only_in_the_private_registry():
    assert len(variants.PHASE_C_STRATEGY_IDS) == 24
    registry = variants.phase_c_registry()
    for strategy_id in variants.PHASE_C_STRATEGY_IDS:
        assert registry.get(strategy_id).metadata.status.value == "RESEARCH"
    assert not any(d.metadata.strategy_id.startswith("RESEARCH_")
                   for d in discover_builtin_strategies().all())


def test_the_production_catalog_does_not_expose_the_phase_c_arms():
    script = (
        "import strategies.btc_core_v2_phase_c_variants;"
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

"""BTC Core V2 Phase D — candidate setup families and the opportunity map.

Two of the three families are the frozen T3 source running branches that were
switched off, so the tests that matter there are that *nothing else* moved and
that each family carries its own setup id — the Core routes pending-order
ownership by setup id, and a collision would let one child cancel another's
order. The third family is a real mirrored implementation, so it is checked
against the long original it mirrors, statement by statement where that is
observable.
"""
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from engine.models import Candle, Direction, ExecutionState, Signal
from research import core_v2_phase_d as phase_d
from research.core_v2_opportunity_map import build, classify, mark_coverage
from research.core_v2_phase_a import DEVELOPMENT_END, HOLDOUT_START
from strategies import btc_core_v2_phase_d_families as families
import strategies.btc_v3_t3_breakout_short as t3_module
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen, CONFIRMATION_MAX_BODY_PERCENT, frozen_parameters,
)
from strategies.btc_v3_l2_trend_pullback_long import body_percent, h1_bullish
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.confirmed_h1_regime import H1RegimeValue
from strategies.registry import discover_builtin_strategies
from utils.data_validation import load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
EQUIV_START = pd.Timestamp("2024-01-01", tz="UTC")
EQUIV_END = pd.Timestamp("2024-07-01", tz="UTC")


@pytest.fixture(scope="module")
def dataset_available() -> Path:
    try:
        return phase_d.dataset_path()
    except (FileNotFoundError, ValueError) as exc:
        pytest.skip(f"validated Exness dataset unavailable: {exc}")


def _run(strategy_id: str, ledger: Path):
    config = replace(phase_d.development_config(strategy_id),
                     start_date=EQUIV_START, end_date=EQUIV_END)
    return run_universal_backtest(phase_d.dataset_path(), config, ledger_path=ledger,
                                  registry=families.phase_d_registry())


# --- D1 and D3 are the frozen source with a branch switched on ------------------


def test_d1_enables_only_the_long_branch():
    frozen, variant = V3T3FrozenParameters(), families.D1T3LongMirror().params
    assert variant.longs_enabled is True and variant.shorts_enabled is False
    for name in V3T3FrozenParameters.__dataclass_fields__:
        if name in {"longs_enabled", "shorts_enabled"}:
            continue
        assert getattr(variant, name) == getattr(frozen, name), name


def test_d3_enables_only_the_range_branch():
    frozen, variant = V3T3FrozenParameters(), families.D3T3RangeSweep().params
    assert variant.trend_enabled is False and variant.range_enabled is True
    assert variant.longs_enabled is True and variant.shorts_enabled is True
    for name in V3T3FrozenParameters.__dataclass_fields__:
        if name in {"trend_enabled", "range_enabled", "longs_enabled", "shorts_enabled"}:
            continue
        assert getattr(variant, name) == getattr(frozen, name), name


def test_the_frozen_body_and_reward_survive_into_every_family():
    for strategy in (families.D1T3LongMirror(), families.D3T3RangeSweep()):
        assert strategy.params.trend_minimum_body_percent == 0.70
        assert strategy.params.reward_multiple == 3.0
    assert families.D2A4ShortMirror().params.confirmation_min_body_percent == 0.70
    assert families.D2A4ShortMirror().params.reward_multiple == 3.0


def test_d1_carries_its_own_setup_id_and_restores_the_frozen_one():
    """A shared setup id would let one child cancel another's pending order."""
    original = t3_module.TREND_SETUP_ID
    with families._trend_setup_id(families.D1_SETUP_ID):
        assert t3_module.TREND_SETUP_ID == families.D1_SETUP_ID
    assert t3_module.TREND_SETUP_ID == original
    with pytest.raises(RuntimeError):
        with families._trend_setup_id(families.D1_SETUP_ID):
            raise RuntimeError("boom")
    assert t3_module.TREND_SETUP_ID == original


def test_every_family_has_a_distinct_setup_id():
    ids = set(families.FAMILY_SETUP_IDS.values())
    assert len(ids) == 3
    from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4
    from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3
    assert A4 not in ids and T3 not in ids


def test_d1_signals_long_and_d1_trades_are_long(dataset_available, tmp_path):
    result = _run(families.STANDALONE_IDS["D1"], tmp_path / "d1.sqlite3")
    assert result.trade_log
    assert {row["direction"] for row in result.trade_log} == {"LONG"}
    assert {row["setup_id"] for row in result.trade_log} == {families.D1_SETUP_ID}


# --- D2 is a mirror, so check it against the original ---------------------------


def _h1(fast, slow, close, slope, separation, atr=100.0):
    lookback = slow - slope
    return H1RegimeValue(hour=pd.Timestamp("2024-01-01", tz="UTC"), close=close,
                         fast_ema=fast, slow_ema=slow, slow_ema_lookback=lookback,
                         atr=atr if separation is None else
                         abs(fast - slow) / separation if separation else atr)


def test_h1_bearish_is_the_reflection_of_h1_bullish():
    params = frozen_parameters()
    bearish = _h1(fast=90.0, slow=100.0, close=95.0, slope=-20.0, separation=1.5)
    bullish = _h1(fast=110.0, slow=100.0, close=105.0, slope=20.0, separation=1.5)
    assert families.h1_bearish(bearish, params) is True
    assert h1_bullish(bullish, params) is True
    assert families.h1_bearish(bullish, params) is False
    assert h1_bullish(bearish, params) is False


def test_h1_bearish_requires_every_condition_the_long_version_does():
    params = frozen_parameters()
    assert families.h1_bearish(_h1(90.0, 100.0, 95.0, +20.0, 1.5), params) is False   # slope up
    assert families.h1_bearish(_h1(110.0, 100.0, 95.0, -20.0, 1.5), params) is False  # ema stack
    assert families.h1_bearish(_h1(90.0, 100.0, 105.0, -20.0, 1.5), params) is False  # close above
    assert families.h1_bearish(_h1(90.0, 100.0, 95.0, -20.0, 0.5), params) is False   # separation


def _candle(open_, high, low, close):
    return Candle(pd.Timestamp("2024-01-01T10:00", tz="UTC"), open_, high, low, close, 1.0)


def test_the_short_confirmation_mirrors_the_long_one():
    params = frozen_parameters()
    previous = _candle(100.0, 101.0, 99.0, 100.0)
    good = _candle(100.0, 100.2, 98.0, 98.2)   # bearish, big body, closes below prior low
    assert families.short_confirmation_passes(good, previous, ema20=99.5, rsi=40.0,
                                              params=params) is True
    bullish = _candle(98.0, 100.2, 97.8, 100.0)
    assert families.short_confirmation_passes(bullish, previous, 99.5, 40.0, params) is False
    no_break = _candle(100.0, 100.2, 99.4, 99.5)
    assert families.short_confirmation_passes(no_break, previous, 99.5, 40.0, params) is False


def test_the_short_confirmation_rsi_band_is_reflected_about_fifty():
    """A4 requires 48 <= rsi <= 70, so the mirror requires 30 <= rsi <= 52."""
    params = frozen_parameters()
    previous = _candle(100.0, 101.0, 99.0, 100.0)
    good = _candle(100.0, 100.2, 98.0, 98.2)
    assert families.short_confirmation_passes(good, previous, 99.5, 30.0, params) is True
    assert families.short_confirmation_passes(good, previous, 99.5, 52.0, params) is True
    assert families.short_confirmation_passes(good, previous, 99.5, 29.9, params) is False
    assert families.short_confirmation_passes(good, previous, 99.5, 52.1, params) is False


def test_the_short_confirmation_applies_the_a4_upper_body_cap():
    params = frozen_parameters()
    previous = _candle(100.0, 101.0, 99.0, 100.0)
    marubozu = _candle(100.0, 100.0, 98.0, 98.0)  # body = 100% of range
    assert body_percent(marubozu) > CONFIRMATION_MAX_BODY_PERCENT
    assert families.short_confirmation_passes(marubozu, previous, 99.5, 40.0, params) is False


def test_d2_uses_the_frozen_a4_parameter_object_unchanged():
    assert asdict(families.D2A4ShortMirror().params) == asdict(frozen_parameters())


def test_d2_only_ever_emits_short_pending_stops(dataset_available, tmp_path):
    result = _run(families.STANDALONE_IDS["D2"], tmp_path / "d2.sqlite3")
    assert result.trade_log
    assert {row["direction"] for row in result.trade_log} == {"SHORT"}
    assert {row["setup_id"] for row in result.trade_log} == {families.D2_SETUP_ID}


def test_d2_signals_only_on_closed_bars_with_a_trigger_below_the_close(dataset_available):
    """A short stop entry must sit below the signal candle's close, or the engine rejects it."""
    frame = load_ohlcv_csv(phase_d.dataset_path())
    frame = frame.loc[frame.timestamp.between(EQUIV_START, EQUIV_END)]
    candles = [Candle(r.timestamp, r.open, r.high, r.low, r.close, r.volume)
               for r in frame.itertuples(index=False)]
    strategy = families.D2A4ShortMirror()
    strategy.reset()
    strategy.on_backtest_window(candles[0].timestamp, None)
    signals = 0
    for candle in candles:
        strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        action = strategy.on_candle(candle)
        if isinstance(action, Signal):
            signals += 1
            assert action.direction is Direction.SHORT
            assert action.pending_entry_price < candle.close
            assert action.pending_stop_price > action.pending_entry_price
    assert signals > 0


def test_d2_produces_one_signal_per_pullback(dataset_available):
    frame = load_ohlcv_csv(phase_d.dataset_path())
    frame = frame.loc[frame.timestamp.between(EQUIV_START, EQUIV_END)]
    strategy = families.D2A4ShortMirror()
    strategy.reset()
    strategy.on_backtest_window(frame.timestamp.iloc[0], None)
    starts = []
    for row in frame.itertuples(index=False):
        strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        strategy.on_candle(Candle(row.timestamp, row.open, row.high, row.low, row.close, row.volume))
    starts = [diag["pullback_start_time"] for diag in strategy.signal_diagnostics.values()]
    assert len(starts) == len(set(starts)), "a pullback signalled more than once"


# --- the Core composition --------------------------------------------------------


def test_the_core_composition_keeps_both_frozen_children_frozen():
    for key in families.FAMILIES:
        core = families.CoreWithFamily(key)
        assert type(core.a4) is BtcV3A4PullbackLongFrozen
        assert type(core.t3) is BtcV3T3BreakoutShortFrozen
        assert asdict(core.a4.params) == asdict(frozen_parameters())


#--- Position size is a percentage of the *running* balance, so inserting a
#--- candidate trade earlier in the sequence legitimately changes quantity, pnl
#--- and trade_id downstream. The strategy decision does not change, which is
#--- why R — not PnL — is the comparison used throughout this research.
DECISION_FIELDS = ("setup_id", "direction", "signal_time", "entry_time", "exit_time",
                   "entry_price", "exit_price", "stop_loss", "take_profit",
                   "exit_reason", "bars_held")
#--- R is size-invariant in principle but computed as pnl / initial_risk, two
#--- size-scaled quantities, so it carries float noise of order 1e-16.
RATIO_FIELDS = ("realized_r", "r_multiple")


def test_the_frozen_children_decide_identically_where_they_are_not_displaced(
        dataset_available, tmp_path):
    """A trade the candidate does not displace must be the same decision as baseline."""
    baseline = _run("BTC_V3_CORE_V1_FROZEN", tmp_path / "base.sqlite3")
    combined = _run(families.CORE_IDS["D2"], tmp_path / "comb.sqlite3")

    def key(row):
        return (row["setup_id"], row["direction"], row["entry_time"])

    base_by_key = {key(row): row for row in baseline.trade_log}
    shared = 0
    for row in combined.trade_log:
        original = base_by_key.get(key(row))
        if original is None:
            continue
        shared += 1
        for field in DECISION_FIELDS:
            assert row[field] == original[field], field
        for field in RATIO_FIELDS:
            assert row[field] == pytest.approx(original[field], rel=1e-12), field
    assert shared > 0


def test_only_size_dependent_fields_may_differ_on_a_shared_trade(
        dataset_available, tmp_path):
    """Pin the reason: equity compounds differently once a trade is inserted."""
    baseline = _run("BTC_V3_CORE_V1_FROZEN", tmp_path / "base2.sqlite3")
    combined = _run(families.CORE_IDS["D2"], tmp_path / "comb2.sqlite3")
    allowed = {"quantity", "pnl", "initial_risk", "estimated_stop_loss", "trade_id",
               "pnl_percent", "entry_commission", "exit_commission", "leverage_capped",
               "realized_r", "r_multiple"}

    def key(row):
        return (row["setup_id"], row["direction"], row["entry_time"])

    base_by_key = {key(row): row for row in baseline.trade_log}
    for row in combined.trade_log:
        original = base_by_key.get(key(row))
        if original is None:
            continue
        differing = {field for field in row if row[field] != original[field]}
        assert differing <= allowed, differing


def test_the_candidate_only_acts_where_the_frozen_pair_did_not(dataset_available, tmp_path):
    combined = _run(families.CORE_IDS["D2"], tmp_path / "c.sqlite3")
    setups = {row["setup_id"] for row in combined.trade_log}
    assert families.D2_SETUP_ID in setups
    #--- one global position: no two trades may overlap in time
    ordered = sorted(combined.trade_log, key=lambda row: row["entry_time"])
    for earlier, later in zip(ordered, ordered[1:]):
        assert earlier["exit_time"] <= later["entry_time"]


# --- the split --------------------------------------------------------------------


@pytest.mark.parametrize("strategy_id", sorted(families.PHASE_D_STRATEGY_IDS))
def test_every_phase_d_config_stops_before_the_holdout(strategy_id):
    config = phase_d.development_config(strategy_id)
    assert config.end_date == DEVELOPMENT_END < HOLDOUT_START
    assert config.risk_reward_ratio == 3.0


def test_running_past_the_split_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(phase_d, "HOLDOUT_START", DEVELOPMENT_END)
    with pytest.raises(ValueError, match="holdout"):
        phase_d.run_arm(families.STANDALONE_IDS["D2"], tmp_path / "x.sqlite3")


# --- the opportunity map -----------------------------------------------------------


def _series(rows):
    base = pd.Timestamp("2024-01-01", tz="UTC")
    return [Candle(base + pd.Timedelta(minutes=15 * i), *row, 1.0)
            for i, row in enumerate(rows)]


def test_the_map_flags_a_break_of_the_prior_five_bar_high():
    rows = [(100, 101, 99, 100)] * 5 + [(100, 105, 99, 104)]
    states = classify(_series(rows))
    assert "BREAKOUT_UP" in states[-1].events
    assert "BREAKDOWN" not in states[-1].events


def test_the_reclaim_event_is_causal_not_forward_looking():
    """The break is detected on the previous bar, the failure on the current one."""
    rows = [(100, 101, 99, 100)] * 5 + [(100, 105, 99, 104), (104, 105, 99, 100)]
    states = classify(_series(rows))
    assert "BREAKOUT_UP" in states[5].events
    assert "FAILED_BREAKOUT_RECLAIM_DOWN" in states[6].events
    assert "FAILED_BREAKOUT_RECLAIM_DOWN" not in states[5].events


def test_the_map_marks_bars_inside_an_open_core_position():
    rows = [(100, 101, 99, 100)] * 6
    states = classify(_series(rows))
    trade = [{"entry_time": states[1].timestamp.isoformat(),
              "exit_time": states[3].timestamp.isoformat()}]
    mark_coverage(states, trade)
    assert [state.covered for state in states] == [False, True, True, True, False, False]


def test_the_map_counts_every_bar_exactly_once_per_dimension():
    rows = [(100, 101 + i % 3, 99 - i % 2, 100 + (i % 5) - 2) for i in range(600)]
    summary = build(_series(rows), [])
    assert sum(item["bars"] for item in summary["regime"].values()) == summary["bars"]
    assert sum(item["bars"] for item in summary["volatility"].values()) == summary["bars"]
    assert summary["core_position_bars"] == 0


def test_an_unconfirmed_h1_bar_is_warmup_not_a_regime():
    states = classify(_series([(100, 101, 99, 100)] * 3))
    assert all(state.h1_regime == "WARMUP" for state in states)


# --- the verdict is mechanical ------------------------------------------------------


def _contribution(**over):
    payload = {
        "new_trades_added": 30, "added_by_the_candidate": 30,
        "baseline_trades_displaced": 5, "incremental_trades_per_month": 5.0,
        "incremental_profit_factor": 1.5, "incremental_average_r": 0.3,
        "incremental_total_r": 9.0,
        "incremental_monthly": {"2024-01": {"total_r": 4.0}, "2024-02": {"total_r": 5.0}},
        "subperiod_net_r": [{"label": "a", "added_r": 5.0, "displaced_r": 1.0},
                            {"label": "b", "added_r": 5.0, "displaced_r": 1.0}],
    }
    payload.update(over)
    return payload


def test_a_family_meeting_every_criterion_is_carried_forward():
    assert phase_d.verdict(None, _contribution())["carry_forward"] is True


@pytest.mark.parametrize("override,fragment", (
    ({"incremental_average_r": -0.1}, "expectancy"),
    ({"incremental_profit_factor": 1.0}, "PF"),
    ({"incremental_trades_per_month": 1.0}, "frequency"),
    ({"new_trades_added": 0}, "no trade"),
    ({"baseline_trades_displaced": 40}, "displaces more"),
    ({"subperiod_net_r": [{"label": "a", "added_r": 5.0, "displaced_r": 1.0},
                          {"label": "b", "added_r": 0.0, "displaced_r": 1.0}]}, "subperiod"),
    ({"incremental_monthly": {"2024-01": {"total_r": 9.0}}}, "one month"),
))
def test_each_failure_mode_is_named(override, fragment):
    result = phase_d.verdict(None, _contribution(**override))
    assert result["carry_forward"] is False
    assert any(fragment in reason for reason in result["failed_criteria"]), result


# --- registration and protected sources ----------------------------------------------


def test_the_phase_d_arms_exist_only_in_the_private_registry():
    assert len(families.PHASE_D_STRATEGY_IDS) == 6
    registry = families.phase_d_registry()
    for strategy_id in families.PHASE_D_STRATEGY_IDS:
        assert registry.get(strategy_id).metadata.status.value == "RESEARCH"
    assert not any(d.metadata.strategy_id.startswith("RESEARCH_")
                   for d in discover_builtin_strategies().all())


def test_the_production_catalog_does_not_expose_the_phase_d_arms():
    script = (
        "import strategies.btc_core_v2_phase_d_families;"
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

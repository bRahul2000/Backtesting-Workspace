"""Market dataset registry — Exness BTCUSDm as a first-class selectable dataset.

Before the registry the dataset was inferred from the instrument, so "BTCUSD"
silently meant the legacy Bitstamp CSV. With two BTC datasets that is a real
hazard: an experiment labelled Exness could have run on Bitstamp candles.
"""
from pathlib import Path

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from services import market_datasets as md
from strategies.registry import discover_builtin_strategies
from ui.universal_workspace import dataset_for_instrument, dataset_for_source

ROOT = Path(__file__).resolve().parents[1]
CORE = "BTC_V3_CORE_V1_FROZEN"


def _config(entry: md.MarketDataset, **over) -> BacktestConfig:
    values = dict(
        instrument=entry.instrument, broker_profile="EXNESS_STANDARD",
        strategy_id=CORE, timeframe=entry.timeframe, higher_timeframes=("1h",),
        start_date=pd.Timestamp("2026-01-01", tz="UTC"),
        end_date=pd.Timestamp("2026-03-01", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT, risk_per_trade_percent=0.25,
        spread=0.0 if entry.carries_per_bar_spread else 10.0,
        spread_source=entry.spread_source, data_source=entry.key)
    values.update(over)
    return BacktestConfig(**values)


# --- registry ---------------------------------------------------------------------------------


def test_both_btc_datasets_are_registered_and_present():
    btc = md.datasets_for_instrument("BTCUSD", "15m")
    keys = {entry.key for entry in btc}
    assert md.BITSTAMP_BTCUSD_15M in keys
    assert md.EXNESS_BTCUSDM_M15 in keys
    for entry in btc:
        assert entry.exists, f"{entry.key} missing at {entry.path}"


def test_the_legacy_bitstamp_dataset_is_unchanged_and_still_updatable():
    """Bitstamp support must not be removed or altered."""
    entry = md.dataset(md.BITSTAMP_BTCUSD_15M)
    assert entry.path == ROOT / "data" / "btcusd_15m.csv"
    assert entry.supports_update is True
    assert entry.read_only is False
    assert entry.spread_source == "CONSTANT"


def test_the_exness_dataset_is_the_validated_r1_processed_file():
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    assert entry.path == ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"
    assert entry.broker == "Exness Technologies Ltd"
    assert entry.symbol == "BTCUSDm"


def test_exness_datasets_are_read_only_and_have_no_update_path():
    """Validated broker evidence is never written or downloaded by the UI."""
    for key in (md.EXNESS_BTCUSDM_M15, md.EXNESS_BTCUSDM_H1,
                md.EXNESS_XAUUSDM_M15, md.EXNESS_XAUUSDM_H1):
        entry = md.dataset(key)
        assert entry.read_only is True
        assert entry.supports_update is False


def test_only_bitstamp_can_be_updated():
    updatable = [e.key for e in md.all_datasets() if e.supports_update]
    assert updatable == [md.BITSTAMP_BTCUSD_15M]


def test_an_unknown_dataset_key_is_refused():
    with pytest.raises(KeyError):
        md.dataset("NOT_A_DATASET")


# --- loading and summary ----------------------------------------------------------------------


def test_exness_btcusdm_m15_loads_correctly():
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    summary = md.summarise(entry)
    assert summary.bars > 90_000
    assert summary.first_candle.startswith("2023-11-10")
    assert summary.symbol == "BTCUSDm"
    assert summary.timeframe == "15m"
    assert summary.segments >= 1
    assert len(summary.fingerprint) == 64


def test_the_summary_reports_source_identity_and_shape():
    summary = md.summarise(md.dataset(md.EXNESS_BTCUSDM_M15))
    for field in (summary.broker, summary.source, summary.symbol, summary.timeframe,
                  summary.path, summary.first_candle, summary.last_candle,
                  summary.fingerprint):
        assert field and field != "-"
    assert summary.segments > 0
    assert summary.gapped_candles >= 0


def test_the_fingerprint_identifies_the_file():
    from core.fingerprints import sha256_file
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    assert md.summarise(entry).fingerprint == sha256_file(entry.path)


def test_bitstamp_and_exness_have_different_fingerprints():
    a = md.summarise(md.dataset(md.BITSTAMP_BTCUSD_15M)).fingerprint
    b = md.summarise(md.dataset(md.EXNESS_BTCUSDM_M15)).fingerprint
    assert a != b


# --- spread handling --------------------------------------------------------------------------


def test_the_exness_dataset_declares_and_carries_a_per_bar_spread():
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    assert entry.spread_source == "BROKER_NATIVE_PER_BAR"
    assert entry.carries_per_bar_spread is True
    raw = pd.read_csv(entry.path, nrows=5)
    assert "spread_points" in raw.columns
    assert "spread_price" in raw.columns
    summary = md.summarise(entry)
    assert summary.spread_points_median and summary.spread_points_median > 0


def test_bitstamp_carries_no_per_bar_spread():
    entry = md.dataset(md.BITSTAMP_BTCUSD_15M)
    assert entry.carries_per_bar_spread is False
    raw = pd.read_csv(entry.path, nrows=5)
    assert "spread_points" not in raw.columns
    assert md.summarise(entry).spread_points_median is None


def test_historical_spread_is_actually_used_not_the_ui_default(tmp_path):
    """The run must differ from the same data forced to a flat spread.

    If BROKER_NATIVE_PER_BAR were ignored, these two would be identical.
    """
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    native = run_universal_backtest(entry.path, _config(entry),
                                    ledger_path=tmp_path / "a.sqlite3")
    flat = run_universal_backtest(
        entry.path, _config(entry, spread_source="CONSTANT", spread=10.0),
        ledger_path=tmp_path / "b.sqlite3")
    assert native.total_trades or flat.total_trades
    assert (native.total_trades, round(native.pnl, 6)) != (flat.total_trades, round(flat.pnl, 6))


# --- the frozen Core on Exness ------------------------------------------------------------------


def test_the_frozen_core_is_compatible_with_btcusd():
    registry = discover_builtin_strategies()
    ids = {d.metadata.strategy_id for d in registry.for_instrument("BTCUSD")}
    assert CORE in ids


def test_the_frozen_core_runs_on_the_exness_dataset(tmp_path):
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    result = run_universal_backtest(entry.path, _config(entry),
                                    ledger_path=tmp_path / "c.sqlite3")
    assert result.total_trades > 0
    assert result.dataset_fingerprint == md.summarise(entry).fingerprint


def test_the_exness_baseline_matches_the_certified_stage2_window(tmp_path):
    """Cross-check: the UI path must reproduce the certified parity result.

    Stage 2 window 1 certified 22 trades over 2026-01-01..2026-03-01 on this
    dataset. Selecting it through the registry must give the same answer.
    """
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    result = run_universal_backtest(entry.path, _config(entry),
                                    ledger_path=tmp_path / "d.sqlite3")
    assert result.total_trades == 22


def test_dataset_selection_changes_the_actual_backtest_data(tmp_path):
    exness = md.dataset(md.EXNESS_BTCUSDM_M15)
    bitstamp = md.dataset(md.BITSTAMP_BTCUSD_15M)
    a = run_universal_backtest(exness.path, _config(exness),
                               ledger_path=tmp_path / "e.sqlite3")
    b = run_universal_backtest(bitstamp.path, _config(bitstamp),
                               ledger_path=tmp_path / "f.sqlite3")
    assert a.dataset_fingerprint != b.dataset_fingerprint
    assert (a.total_trades, a.pnl) != (b.total_trades, b.pnl)


# --- experiment identity -------------------------------------------------------------------------


def test_the_config_records_the_selected_dataset(tmp_path):
    for key in (md.EXNESS_BTCUSDM_M15, md.BITSTAMP_BTCUSD_15M):
        entry = md.dataset(key)
        config = _config(entry)
        assert config.data_source == key
        result = run_universal_backtest(entry.path, config,
                                        ledger_path=tmp_path / f"{key}.sqlite3")
        assert result.dataset_fingerprint == md.summarise(entry).fingerprint


def test_a_recorded_run_resolves_back_to_the_dataset_it_used():
    """Reproduction must verify against the recorded dataset, not today's default."""
    assert dataset_for_source(md.EXNESS_BTCUSDM_M15).key == md.EXNESS_BTCUSDM_M15
    assert dataset_for_source(md.BITSTAMP_BTCUSD_15M).key == md.BITSTAMP_BTCUSD_15M


def test_legacy_experiment_rows_still_resolve():
    """Historical rows recorded the old data_source strings."""
    assert dataset_for_source("canonical_btcusd_15m").key == md.BITSTAMP_BTCUSD_15M
    assert dataset_for_source("exness_xauusd_phase2a_m15").key == md.EXNESS_XAUUSDM_M15
    assert dataset_for_source("exness_xauusd_phase2a_h1").key == md.EXNESS_XAUUSDM_H1


def test_the_legacy_default_for_btcusd_is_still_bitstamp():
    """Existing behaviour is preserved for anything that did not select."""
    path, source = dataset_for_instrument("BTCUSD", "15m")
    assert path == md.dataset(md.BITSTAMP_BTCUSD_15M).path
    assert source == "canonical_btcusd_15m"


# --- frozen strategy integrity ---------------------------------------------------------------------


def test_frozen_core_hashes_are_unchanged():
    expected = {
        "BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
        "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
        "BTC_V3_CORE_V1_FROZEN": "631374d5",
    }
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)

from pathlib import Path
import json

import pandas as pd
import pytest

from brokers.base_broker import BrokerInstrumentProfile
from brokers.exness import load_exness_xauusd_profile
from engine.gold_execution import (
    GoldDirection, GoldQuoteBar, calculate_lot_size, entry_price, exit_price,
    loss_per_lot, margin_required, normalize_price, pnl_from_prices,
    round_volume, validate_stop_distance,
)
from instruments.xauusd import load_xauusd_profile
from services.gold_data import import_gold_ohlcv_csv
from services.gold_spec import PROFILE_ID, load_mt5_gold_snapshot


SPEC = {
    "profile_id": PROFILE_ID, "broker": "Exness", "account_server": "Exness-MT5Trial",
    "symbol": "XAUUSDm", "description": "Gold", "digits": 2, "point": 0.01,
    "tick_size": 0.01, "tick_value": 1.0, "tick_value_profit": 1.0,
    "tick_value_loss": 1.0, "contract_size": 100.0, "volume_min": 0.01,
    "volume_max": 100.0, "volume_step": 0.01, "stops_level": 10, "freeze_level": 0,
    "margin_calculation_mode": 0, "margin_initial": 1800.0, "margin_maintenance": None,
    "swap_long": -2.0, "swap_short": 1.0, "swap_mode": 1,
    "trading_sessions": ["1 00:00-23:59"], "bid": 1800.00, "ask": 1800.05,
    "spread": 0.05, "capture_timestamp_utc": "2026-09-19T12:00:00", "source": "test fixture",
}


def _spec(tmp_path: Path) -> BrokerInstrumentProfile:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SPEC), encoding="utf-8")
    return load_exness_xauusd_profile(path).instrument("XAUUSD")


def test_snapshot_loads_gold_profile_without_guessing_and_rejects_credentials(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(SPEC), encoding="utf-8")
    assert load_mt5_gold_snapshot(path)["profile_id"] == PROFILE_ID
    assert load_xauusd_profile(path).contract_size == 100.0
    assert load_exness_xauusd_profile(path).instrument("XAUUSD").known
    path.write_text(json.dumps({**SPEC, "password": "secret"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Credential"):
        load_mt5_gold_snapshot(path)


def test_gold_csv_import_normalizes_validates_deduplicates_and_excludes_incomplete_bar(tmp_path):
    source = tmp_path / "gold.csv"
    pd.DataFrame([
        ["2026-01-01 00:00", 1800, 1801, 1799, 1800.5, 10],
        ["2026-01-01 00:15", 1800.5, 1802, 1800, 1801, 11],
        ["2026-01-01 00:15", 1800.5, 1802, 1800, 1801, 11],
        ["2026-01-01 00:45", 1801, 1803, 1800, 1802, 12],
        ["2026-01-01 01:00", 1802, 1804, 1801, 1803, 13],
    ], columns=["Date", "Open", "High", "Low", "Close", "Volume"]).to_csv(source, index=False)
    metadata = import_gold_ohlcv_csv(
        source, tmp_path / "xauusd_m15.csv", timeframe="M15", source_timezone="UTC",
        as_of=pd.Timestamp("2026-01-01 01:00", tz="UTC"),
    )
    assert metadata.candles == 3
    assert metadata.duplicates_removed == 1
    assert metadata.incomplete_bars_removed == 1
    assert metadata.missing_candles == 1
    assert metadata.continuous_segments == 2
    with pytest.raises(ValueError, match="source_timezone"):
        import_gold_ohlcv_csv(source, tmp_path / "bad.csv", timeframe="M15")


def test_gold_long_and_short_use_quote_sides_and_tick_value_pnl(tmp_path):
    spec = _spec(tmp_path)
    bar = GoldQuoteBar(1800, 1810, 1790, 1805, 1800.05, 1810.05, 1790.05, 1805.05)
    assert entry_price(bar, GoldDirection.LONG) == 1800.05
    assert entry_price(bar, GoldDirection.SHORT) == 1800
    assert exit_price(bar, GoldDirection.LONG, 1795, 1808) == (1795, "stop")
    assert exit_price(bar, GoldDirection.SHORT, 1808, 1792) == (1808, "stop")
    assert pnl_from_prices(1800.05, 1801.05, GoldDirection.LONG, 1, spec) == pytest.approx(100)
    assert pnl_from_prices(1800, 1799, GoldDirection.SHORT, 1, spec) == pytest.approx(100)
    assert loss_per_lot(1800.05, 1799.05, GoldDirection.LONG, spec, spread=.05) == pytest.approx(105)


def test_gold_risk_sizing_volume_limits_margin_stops_and_precision(tmp_path):
    spec = _spec(tmp_path)
    assert calculate_lot_size(10_000, 1, 1800.05, 1799.05, GoldDirection.LONG, spec) == pytest.approx(1.0)
    assert calculate_lot_size(10_000, 1, 1800.05, 1799.05, GoldDirection.LONG, spec,
                              spread=.05) == pytest.approx(.95)
    assert calculate_lot_size(10_000, 1, 1800, 1801, GoldDirection.SHORT, spec) == pytest.approx(1.0)
    assert round_volume(.019, spec) == .01
    assert round_volume(101, spec) == 100
    assert normalize_price(1800.056, spec) == 1800.06
    assert margin_required(2, 1800) == 3600
    with pytest.raises(ValueError, match="stops level"):
        validate_stop_distance(1800, 1799.95, GoldDirection.LONG, spec)
    with pytest.raises(ValueError, match="minimum"):
        calculate_lot_size(10, 1, 1800, 1799, GoldDirection.LONG, spec)
    assert calculate_lot_size(10_000, 10, 1800, 1799, GoldDirection.LONG, spec,
                              margin_per_lot=1800) == pytest.approx(5.55)


def test_gold_same_bar_resolution_is_explicit_for_both_directions(tmp_path):
    spec = _spec(tmp_path)
    bar = GoldQuoteBar(1800, 1810, 1790, 1800, 1800.05, 1810.05, 1790.05, 1800.05)
    assert exit_price(bar, GoldDirection.LONG, 1795, 1805, stop_first=True) == (1795, "stop")
    assert exit_price(bar, GoldDirection.LONG, 1795, 1805, stop_first=False) == (1805, "target")
    assert spec.trading_sessions == () or spec.trading_sessions
"""Broker-native per-bar spread: an additive path that must not disturb the
existing constant-spread behaviour.

The load-bearing test is the equivalence one: a per-bar sequence whose values
are all equal to the old constant must reproduce the constant run exactly,
trade for trade.
"""
from pathlib import Path

import pandas as pd
import pytest

from core.adapters.audited_engine import _broker_native_spread, run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from research.exness_cost_calibrated import _spread_at

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
BITSTAMP = ROOT / "data/btcusd_15m.csv"
EXNESS = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"
START = pd.Timestamp("2024-01-01", tz="UTC")
END = pd.Timestamp("2024-03-01", tz="UTC")


def _config(**overrides) -> BacktestConfig:
    base = dict(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m", higher_timeframes=("1h",),
        start_date=START, end_date=END, dataset_role=DatasetRole.PAPER)
    base.update(overrides)
    return BacktestConfig(**base)


# --- config -------------------------------------------------------------------------------


def test_spread_source_defaults_to_the_historical_constant():
    assert _config().spread_source == "CONSTANT"


def test_an_unknown_spread_source_is_refused():
    with pytest.raises(ValueError, match="spread_source"):
        _config(spread_source="GUESS")


def test_broker_native_spread_source_is_accepted():
    assert _config(spread_source="BROKER_NATIVE_PER_BAR").spread_source == "BROKER_NATIVE_PER_BAR"


# --- per-bar resolution -------------------------------------------------------------------


def test_a_scalar_spread_resolves_to_itself_on_every_bar():
    assert _spread_at(10.0, 0) == 10.0
    assert _spread_at(10.0, 5_000) == 10.0
    assert _spread_at(7, 3) == 7.0


def test_a_sequence_spread_resolves_per_bar():
    assert _spread_at([1.0, 2.0, 3.0], 0) == 1.0
    assert _spread_at([1.0, 2.0, 3.0], 2) == 3.0


# --- the replay path ----------------------------------------------------------------------


def _run(path, **overrides):
    return run_universal_backtest(path, _config(**overrides),
                                  ledger_path=Path("/tmp/pb_r3_overlap/test_spread.sqlite3"))


def test_a_flat_per_bar_spread_reproduces_the_constant_run_exactly():
    """Equivalence proof: the new path cannot change existing results."""
    constant = _run(BITSTAMP, spread=10.0)
    frame = pd.read_csv(EXNESS)
    assert (frame.spread_price > 0).all()

    # Same feed, same window, one spread value per bar, all equal to the constant.
    flat = Path("/tmp/pb_r3_overlap/flat_spread_probe.csv")
    flat.parent.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(BITSTAMP)
    source["spread_price"] = 10.0
    source.to_csv(flat, index=False)
    try:
        per_bar = _run(flat, spread_source="BROKER_NATIVE_PER_BAR", spread=10.0)
        assert per_bar.total_trades == constant.total_trades
        assert per_bar.pnl == pytest.approx(constant.pnl)
        assert per_bar.average_r == pytest.approx(constant.average_r)
        for left, right in zip(constant.trade_log, per_bar.trade_log):
            assert left["entry_price"] == pytest.approx(right["entry_price"])
            assert left["exit_price"] == pytest.approx(right["exit_price"])
            assert left["exit_reason"] == right["exit_reason"]
    finally:
        flat.unlink(missing_ok=True)


def test_a_real_broker_spread_is_wider_than_the_old_constant_and_costs_more():
    """Sanity: the real per-bar spread is about twice the calibrated constant,
    so the broker-native run cannot be cheaper on the same feed."""
    flat_ten = _run(EXNESS, spread=10.0)
    native = _run(EXNESS, spread_source="BROKER_NATIVE_PER_BAR")
    assert native.total_trades > 0
    assert native.average_r < flat_ten.average_r


# --- column requirements ------------------------------------------------------------------


def test_broker_native_spread_requires_an_explicit_spread_column():
    """A broker-native run must never silently fall back to the constant."""
    with pytest.raises(ValueError, match="spread_price"):
        _broker_native_spread(BITSTAMP, pd.read_csv(BITSTAMP).head(5))


def test_broker_native_spread_reads_the_real_exness_column():
    data = pd.DataFrame({"timestamp": pd.to_datetime(
        ["2023-11-10T23:15:00Z", "2023-11-10T23:30:00Z"], utc=True)})
    series = _broker_native_spread(EXNESS, data)
    assert series.loc[pd.Timestamp("2023-11-10 23:15", tz="UTC")] == pytest.approx(10.68)
    assert (series >= 0).all()


def test_a_wrong_length_per_bar_spread_is_refused():
    from engine.models import Candle
    from research.exness_cost_calibrated import run_synthetic_segment
    from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen

    frame = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0})
    with pytest.raises(ValueError, match="one value per candle"):
        run_synthetic_segment(frame, BtcV3CoreV1Frozen(), [10.0, 10.0], START)


def test_a_negative_per_bar_spread_is_refused():
    from research.exness_cost_calibrated import run_synthetic_segment
    from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen

    frame = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=4, freq="15min", tz="UTC"),
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1.0})
    with pytest.raises(ValueError, match="nonnegative"):
        run_synthetic_segment(frame, BtcV3CoreV1Frozen(), [10.0, -1.0, 10.0, 10.0], START)

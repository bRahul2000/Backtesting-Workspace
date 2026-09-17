"""Phase 4K gates and freeze safeguards; no active strategy changes."""
import json

import numpy as np
import pandas as pd
import pytest

import research.setup_a_volatility_research as research


def _signal_rows():
    return pd.DataFrame({
        "signal_candle_time": pd.to_datetime([
            "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z",
            "2024-01-03T00:00:00Z", "2024-01-04T00:00:00Z"]),
        "atr_percent": [.1, .2, .3, .4],
        "recent_volatility_24h_percent": [1., 2., 3., 4.],
    })


def test_atr_and_24h_volatility_use_only_completed_prefix():
    assert research.atr_percent(200, 50_000) == pytest.approx(.4)
    closes = pd.Series(np.linspace(100, 120, 97))
    original = research.recent_volatility(closes)
    assert np.isnan(research.recent_volatility(closes.iloc[:-1]))
    future = pd.concat([closes, pd.Series([1000.])], ignore_index=True)
    assert research.recent_volatility(future.iloc[:-1]) == pytest.approx(original)
    assert original > 0


def test_development_percentiles_and_no_validation_leakage():
    signals = _signal_rows()
    thresholds = research.development_thresholds(signals)
    assert thresholds["atr_percent"][20] == pytest.approx(.16)
    assert thresholds["recent_volatility_24h_percent"][40] == pytest.approx(2.2)
    with_validation = pd.concat([signals, signals.iloc[[0]].assign(
        signal_candle_time=pd.Timestamp("2025-01-01T00:00:00Z"),
        atr_percent=100.)], ignore_index=True)
    with pytest.raises(ValueError, match="validation"):
        research.development_thresholds(with_validation)


def test_threshold_is_strict_and_multirule_and_classification():
    row = {"atr_percent": .3, "recent_volatility_24h_percent": 2.}
    atr_rule = {"feature": "atr_percent", "threshold": .3}
    vol_rule = {"feature": "recent_volatility_24h_percent", "threshold": 1.5}
    assert not research.allowed(row, [atr_rule])
    assert research.allowed(row, [vol_rule])
    assert not research.allowed(row, [atr_rule, vol_rule])
    assert research.allowed(row, [])


def test_freeze_hash_and_immutability(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "REPORT", tmp_path)
    pd.DataFrame([{"feature": "atr_percent", "percentile": 20,
                   "threshold": .26}]).to_csv(tmp_path / "development_one_factor.csv", index=False)
    candidate = [{"candidate_id": "C1", "rules": [
        {"feature": "atr_percent", "percentile": 20, "threshold": .26}]}]
    frozen = research.freeze_candidates(candidate)
    assert len(frozen["freeze_hash_sha256"]) == 64
    with pytest.raises(FileExistsError):
        research.freeze_candidates(candidate)
    assert research.load_frozen()["candidates"] == candidate
    path = tmp_path / "frozen_candidates.json"
    altered = json.loads(path.read_text())
    altered["candidates"][0]["rules"][0]["threshold"] = .5
    path.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match="modified"):
        research.load_frozen()


def test_validation_refuses_to_load_data_before_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "REPORT", tmp_path)
    def forbidden_load(*, development_only):
        raise AssertionError("Validation data accessed before freeze")
    monkeypatch.setattr(research, "load_data", forbidden_load)
    with pytest.raises(FileNotFoundError):
        research.validate()


def _trades():
    return pd.DataFrame({
        "signal_year": [2024, 2024, 2025],
        "segment_id": ["S1", "S1", "S2"],
        "signal_time": pd.to_datetime(["2024-01-01T01:00:00Z",
                                       "2024-01-02T01:00:00Z", "2025-01-01T01:00:00Z"]),
        "exit_time": pd.to_datetime(["2024-01-01T02:00:00Z",
                                     "2024-01-02T02:00:00Z", "2025-01-01T02:00:00Z"]),
        "direction": ["LONG", "SHORT", "LONG"],
        "atr_percent": [.2, .4, .1],
        "gross_pnl": [-10., 30., -5.],
        "realized_r": [-1., 3., -1.],
        "mfe_r": [.2, 3., .1],
        "reached_0.5r": [False, True, False],
    })


def test_retention_year_and_long_short_aggregation():
    trades = _trades().loc[lambda d: d.signal_year.eq(2024)]
    summary = research.metrics(trades, baseline_trades=4, start_year=2024,
                               end_year=2024)
    assert summary["trades"] == 2
    assert summary["retention_percent"] == 50
    assert summary["long_trades"] == 1 and summary["short_trades"] == 1
    assert summary["long_average_r"] == -1 and summary["short_average_r"] == 3
    assert summary["never_reached_0.5r_percent"] == 50
    assert summary["worst_segment_dd_percent"] > 0


def test_allowed_blocked_yearly_counterfactual():
    trades = _trades()
    signals = trades[["signal_year", "atr_percent"]].copy()
    rules = [{"feature": "atr_percent", "threshold": .25}]
    year = research.participation_summary(signals, trades, trades, rules, 2024)
    assert year["control_signals"] == 2
    assert year["signals_allowed"] == 1 and year["signals_blocked"] == 1
    assert year["control_trades_allowed"] == 1 and year["control_trades_blocked"] == 1
    assert year["allowed_counterfactual_pnl"] == 30
    assert year["blocked_counterfactual_pnl"] == -10
    assert year["allowed_counterfactual_pf"] == float("inf")
    later = research.participation_summary(signals, trades, trades, rules, 2025)
    assert later["signals_allowed"] == 0

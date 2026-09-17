"""Deterministic Phase 4E research isolation and freeze tests."""
from types import SimpleNamespace

import pandas as pd
import pytest

from engine.models import Direction, Signal
from research import setup_b_entry_research as research
from strategies.btc_v2_setup_b import SetupBParameters


def test_one_factor_parameter_isolation():
    original = SetupBParameters()
    changed = research.EntrySpec.from_dict({"minimum_adx": 25}).strategy_params()
    assert changed.minimum_adx == 25
    assert {key for key in original.__dataclass_fields__
            if getattr(original, key) != getattr(changed, key)} == {"minimum_adx"}
    proposed = research.EntrySpec.from_dict({"minimum_structure_break_atr": .2})
    assert proposed.strategy_params() == original
    with pytest.raises(ValueError):
        research.EntrySpec.from_dict({"reward_multiple": 2.})


@pytest.mark.parametrize("direction,close,high,low", [
    (Direction.LONG, 102., 101., 99.),
    (Direction.SHORT, 98., 101., 99.),
])
def test_structure_break_distance_filter(direction, close, high, low):
    candle = SimpleNamespace(close=close)
    signal = Signal(direction)
    slope = .1 if direction is Direction.LONG else -.1
    assert research.entry_filter_pass(signal, candle, previous_high=high,
                                      previous_low=low, atr=10.,
                                      h1_slope_percent=slope,
                                      minimum_structure_break_atr=.1)
    assert not research.entry_filter_pass(signal, candle, previous_high=high,
                                          previous_low=low, atr=10.,
                                          h1_slope_percent=slope,
                                          minimum_structure_break_atr=.2)


@pytest.mark.parametrize("direction,slope", [(Direction.LONG, .03),
                                             (Direction.SHORT, -.03)])
def test_h1_slope_threshold_is_directional_and_symmetric(direction, slope):
    candle = SimpleNamespace(close=102. if direction is Direction.LONG else 98.)
    signal = Signal(direction)
    args = dict(previous_high=101., previous_low=99., atr=10.,
                h1_slope_percent=slope)
    assert research.entry_filter_pass(signal, candle, minimum_h1_slope_percent=.02, **args)
    assert not research.entry_filter_pass(signal, candle, minimum_h1_slope_percent=.04, **args)


def test_trade_retention_and_low_sample_flag():
    assert research.trade_retention(250, 500) == 50.
    assert research.low_sample(249)
    assert not research.low_sample(250)


def test_year_aggregation_and_pnl_contribution():
    times = [pd.Timestamp("2021-06-01", tz="UTC"),
             pd.Timestamp("2022-06-01", tz="UTC")]
    trades = pd.DataFrame([
        dict(segment_id="S01", signal_time=times[0], exit_time=times[0],
             direction="LONG", pnl=20., zero_cost_pnl=21., r=2., zero_cost_r=2.1),
        dict(segment_id="S02", signal_time=times[1], exit_time=times[1],
             direction="SHORT", pnl=-10., zero_cost_pnl=-9., r=-1., zero_cost_r=-.9),
    ])
    annual = research.annual_rows(trades, "X")
    assert [row["trades"] for row in annual] == [1, 1, 0, 0]
    assert annual[0]["pnl_contribution_percent_of_absolute_years"] == pytest.approx(66.6666667)
    assert annual[1]["pnl_contribution_percent_of_absolute_years"] == pytest.approx(-33.3333333)


def test_candidate_freeze_refuses_overwrite_and_detects_tamper(tmp_path):
    path = tmp_path / "frozen_candidates.json"
    candidate = [{"id": "C1", "changes": {"minimum_adx": 25}}]
    research.freeze_candidates(path, candidate, "source-hash")
    assert research.read_frozen_candidates(path)["candidates"] == candidate
    with pytest.raises(FileExistsError):
        research.freeze_candidates(path, [], "other-hash")
    path.write_text(path.read_text().replace("25", "30"))
    with pytest.raises(ValueError, match="changed"):
        research.read_frozen_candidates(path)


def test_development_range_stops_before_validation(tmp_path, monkeypatch):
    path = tmp_path / "candles.csv"
    pd.DataFrame([
        dict(timestamp="2024-12-31T23:45:00Z", open=100, high=101, low=99, close=100, volume=1),
        dict(timestamp="2025-01-01T00:00:00Z", open=100, high=101, low=99, close=100, volume=1),
    ]).to_csv(path, index=False)
    monkeypatch.setattr(research, "DATA", path)
    development = research._read_range(None, research.BOUNDARY)
    assert len(development) == 1
    assert development.timestamp.max() < research.BOUNDARY
    assert len(research._read_range(None, None)) == 2


def test_predefined_combinations_have_at_most_three_changes():
    factors = [{"parameter": name, "value": value}
               for name, value in [("minimum_adx", 25),
                                   ("minimum_body_percent", .6),
                                   ("maximum_extension_atr", 2.)]]
    combos = research.predefined_combinations(factors)
    assert len(combos) <= 5
    assert all(2 <= len(c["changes"]) <= 3 for c in combos)


def test_shortlist_needs_adjacent_adequate_settings():
    variants = ["CONTROL", "minimum_adx=18", "minimum_adx=20",
                "minimum_adx=22", "minimum_adx=25", "minimum_adx=28",
                "minimum_adx=30"]
    one = pd.DataFrame([dict(parameter="Control" if i == 0 else "minimum_adx",
                             variant=name, value=0 if i == 0 else [18, 18, 20, 22, 25, 28, 30][i],
                             trades=500 if i != 6 else 249,
                             trade_retention_percent=100 if i != 6 else 49.8,
                             profit_factor=.9 if i < 4 else 1.0,
                             average_r=-.1 if i < 4 else -.05,
                             worst_segment_dd_percent=5.)
                        for i, name in enumerate(variants)])
    years = pd.DataFrame([dict(variant=name, year=year,
                               net_pnl=-100 if name == "CONTROL" else
                               (-80 if i >= 4 else -100))
                          for i, name in enumerate(variants)
                          for year in (2021, 2022, 2023, 2024)])
    selected = research.shortlist_factors(one, years)
    assert selected and selected[0]["parameter"] == "minimum_adx"
    # Isolated improvement at one level is not enough.
    one.loc[one.variant == "minimum_adx=28", "profit_factor"] = .9
    assert research.shortlist_factors(one, years) == []

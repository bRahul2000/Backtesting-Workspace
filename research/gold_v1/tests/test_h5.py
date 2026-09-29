"""H5 regression tests: New York opening range across DST, causality, two-close rule and duplicate suppression.

    venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h5"))
import h1_study as h1                                    # noqa: E402
import h5_study as h5                                    # noqa: E402
from test_pipeline import frame                          # noqa: E402

# broker sessions either side of the US DST change (2026-03-08): EST closes 22:00 UTC, EDT closes 21:00 UTC
AROUND_DST = [("2026-03-04 23:00", "2026-03-05 21:45"), ("2026-03-05 23:00", "2026-03-06 21:45"),
              ("2026-03-08 22:00", "2026-03-09 20:45"), ("2026-03-09 22:00", "2026-03-10 20:45")]


def test_opening_range_maps_to_correct_utc_bars_across_dst():
    f = h1.features(frame(AROUND_DST))
    ors = h5.opening_ranges(f)
    got = [(str(f["time"].iloc[r.or_first]), str(f["time"].iloc[r.or_last])) for r in ors.itertuples()]
    assert got == [
        ("2026-03-05 14:30:00+00:00", "2026-03-05 14:45:00+00:00"),       # EST: 09:30 New York = 14:30 UTC
        ("2026-03-06 14:30:00+00:00", "2026-03-06 14:45:00+00:00"),
        ("2026-03-09 13:30:00+00:00", "2026-03-09 13:45:00+00:00"),       # EDT: 09:30 New York = 13:30 UTC
        ("2026-03-10 13:30:00+00:00", "2026-03-10 13:45:00+00:00"),
    ]
    for r in ors.itertuples():
        bars = f.iloc[[r.or_first, r.or_last]]
        assert r.or_high == bars["high"].max() and r.or_low == bars["low"].min()


@pytest.mark.parametrize("utc, ny_minutes", [
    ("2026-03-06 14:30", 570), ("2026-03-06 13:30", 510),      # EST
    ("2026-03-09 13:30", 570), ("2026-03-09 14:30", 630),      # EDT
    ("2026-01-15 17:45", 765), ("2026-05-15 16:45", 765),      # last confirming bar (12:45 New York)
])
def test_ny_minutes(utc, ny_minutes):
    f = pd.DataFrame({"time": [pd.Timestamp(utc, tz="UTC")]})
    assert h5.ny_minutes(f)[0] == ny_minutes


def _day_with_closes(closes_after_or: list[float]) -> pd.DataFrame:
    """One EST session with a flat OR (high 4001, low 3999) and chosen closes from 10:00 New York (15:00 UTC)."""
    f0 = frame([("2026-01-13 23:00", "2026-01-14 21:45")])
    f0[["open", "high", "low", "close"]] = 4000.0
    f0["high"], f0["low"] = 4001.0, 3999.0
    start = f0.index[f0["time"] == pd.Timestamp("2026-01-14 15:00", tz="UTC")][0]
    prev = 4000.0
    for k, px in enumerate(closes_after_or + [closes_after_or[-1]]):     # extra bar: the entry bar opens at prev
        j = start + k
        f0.loc[j, ["open", "close"]] = [prev, px]
        f0.loc[j, "high"] = max(4001.0, prev, px) + 0.5
        f0.loc[j, "low"] = min(3999.0, prev, px) - 0.5
        prev = px
    return f0


def _events(f0):
    f = h1.features(f0)
    ors = h5.opening_ranges(f)
    return h5.detect(f, ors)


def test_two_consecutive_strict_closes_needed_and_equality_is_not_outside():
    # 10:00 close == OR high (not outside), 10:15 above, 10:30 inside (reset), 10:45 above, 11:00 above -> confirm 11:00
    ev, counts, _, _ = _events(_day_with_closes([4001.0, 4002.0, 4000.0, 4002.0, 4003.0]))
    assert list(ev["direction"]) == ["long"] and ev["signal_time_ny"].iloc[0] == "11:00"
    assert counts["raw_outside_closes"]["long"] == 4          # 10:15, 10:45, 11:00 and the 11:15 entry bar


def test_one_event_per_direction_and_both_directions_kept():
    closes = [4002.0, 4003.0, 4004.0, 4000.0, 3998.0, 3997.0]      # long confirms 10:15, again 10:30; short 11:15
    ev, counts, days, _ = _events(_day_with_closes(closes))
    assert list(ev["direction"]) == ["long", "short"]
    assert counts["suppressed_duplicates"]["long"] == 1
    assert ev["both_directions_day"].all() and list(ev["opposite_confirmed_earlier"]) == [False, True]
    assert (ev["stop"] == 4000.0).all()                              # OR midpoint


def test_no_confirmation_after_1245_new_york():
    closes = [4000.0] * 11 + [4002.0, 4003.0]                       # outside closes at 12:45 and 13:00 New York
    ev, _, _, _ = _events(_day_with_closes(closes))
    assert ev.empty


def test_future_perturbation_does_not_change_past_events():
    dev = h1.load_dev()
    f = h1.features(dev)
    ev, _, _, _ = h5.detect(f, h5.opening_ranges(f))
    cut = int(len(dev) * 0.5)
    noisy = dev.copy()
    shift = np.random.default_rng(2).normal(0, 5, len(dev) - cut)
    for col in ("open", "high", "low", "close"):
        noisy.loc[cut:, col] = noisy.loc[cut:, col].to_numpy() + shift
    noisy.loc[cut:, "high"] = noisy.loc[cut:, ["open", "high", "low", "close"]].max(axis=1)
    noisy.loc[cut:, "low"] = noisy.loc[cut:, ["open", "high", "low", "close"]].min(axis=1)
    fn = h1.features(noisy)
    ev2, _, _, _ = h5.detect(fn, h5.opening_ranges(fn))
    key = ["direction", "signal_index", "or_high", "or_low", "entry", "stop", "first_break", "opposite_swept_before"]
    assert set(map(tuple, ev[ev["entry_index"] < cut][key].to_numpy())) == \
        set(map(tuple, ev2[ev2["entry_index"] < cut][key].to_numpy()))

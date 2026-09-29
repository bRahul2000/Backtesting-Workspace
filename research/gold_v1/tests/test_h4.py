"""H4 regression tests: live causal TVWAP race, band rules, stop causality and duplicate suppression.

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
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h4"))
import h1_study as h1                                    # noqa: E402
import h4_study as h4                                    # noqa: E402


def bars(rows, tvwap):
    """Crafted one-session frame: rows = (open, high, low, close); TVWAP per bar."""
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    f["tvwap"] = tvwap
    f["session_last"] = len(f) - 1
    return f


def test_race_uses_previous_bar_tvwap_not_the_current_one():
    # long from 100, risk 2 (stop 98). Bar 1 high 101: previous TVWAP 102 -> not hit, even though bar 1's own TVWAP
    # (101) would be touched. Bar 2 high 102.5 reaches bar 1's TVWAP 101.
    f = bars([(100, 100, 100, 100), (100, 101, 99.5, 100.5), (100.5, 102.5, 100, 102)], [102, 101, 101.5])
    r = h4.tvwap_race(f, 1, 1, 100.0, 2.0)
    assert r["tv_outcome"] == "hit" and r["tv_bars"] == 2 and r["tv_realized_r"] == pytest.approx(0.5)


def test_race_same_bar_target_and_stop_is_ambiguous_never_favourable():
    f = bars([(100, 100, 100, 100), (100, 103, 97, 100)], [102, 102])
    r = h4.tvwap_race(f, 1, 1, 100.0, 2.0)
    assert r["tv_outcome"] == "ambiguous" and r["tv_outcome_r"] == -1.0


def test_race_gap_through_target_realizes_at_open_and_session_end_marks_to_market():
    f = bars([(100, 100, 100, 100), (103, 104, 102.5, 103)], [102, 102])
    r = h4.tvwap_race(f, 1, 1, 100.0, 2.0)
    assert r["tv_outcome"] == "hit" and r["tv_realized_r"] == pytest.approx(1.5)
    f = bars([(100, 100, 100, 100), (100, 100.5, 99, 100.4)], [105, 105])
    r = h4.tvwap_race(f, 1, 1, 100.0, 2.0)
    assert r["tv_outcome"] == "session_end" and r["tv_outcome_r"] == pytest.approx(0.2)


def test_short_race_mirrors_long():
    f = bars([(100, 100, 100, 100), (100, 100.5, 98.9, 99.2)], [99, 99])
    r = h4.tvwap_race(f, 1, -1, 100.0, 2.0)
    assert r["tv_outcome"] == "hit" and r["tv_realized_r"] == pytest.approx(0.5)


@pytest.fixture(scope="module")
def run():
    dev = h1.load_dev()
    f = h4.h4_features(h1.features(dev))
    ev, counts, reentry = h4.detect(f)
    return dev, f, ev, counts, reentry


def test_events_follow_every_band_rule(run):
    _, f, ev, _, _ = run
    assert len(ev) > 0 and ev["entry_time"].max() < h1.DEV_END
    for e in ev.itertuples():
        d = 1 if e.direction == "long" else -1
        X, R, s0 = e.exhaustion_index, e.reentry_index, e.streak_start_index
        for k in range(s0, X + 1):                                        # the whole streak closed beyond 2σ
            ck, u2, l2 = f["close"].iloc[k], f["u2"].iloc[k], f["l2"].iloc[k]
            assert (ck > u2) if d == -1 else (ck < l2)
        assert f["l1"].iloc[R] < f["close"].iloc[R] < f["u1"].iloc[R] and 1 <= R - X <= 2
        for k in range(X + 1, R):                                         # nothing re-exhausted in between
            ck = f["close"].iloc[k]
            assert f["l2"].iloc[k] <= ck <= f["u2"].iloc[k]
        assert f["bar_no"].iloc[X] >= 4 and f["er_h1"].iloc[R] <= 0.15 and not f["ny_open_hour"].iloc[R]
        span = f.iloc[s0:R + 1]
        assert e.stop == (span["high"].max() if d == -1 else span["low"].min())
        assert e.entry == f["open"].iloc[R + 1] and e.risk > 0 and e.target_r > 0
        assert f["tday"].iloc[s0] == f["tday"].iloc[R + 1]


def test_one_event_per_streak(run):
    _, _, ev, _, _ = run
    assert not ev.duplicated(["direction", "streak_start_index"]).any()


def test_ny_open_hour_is_dst_aware():
    t = pd.Series(pd.to_datetime(["2026-01-15 14:30", "2026-01-15 15:15", "2026-01-15 15:30",
                                  "2026-05-15 13:30", "2026-05-15 14:15", "2026-05-15 14:30"], utc=True))
    local = t.dt.tz_convert(h1.NEW_YORK)
    m = local.dt.hour * 60 + local.dt.minute
    flag = ((m >= h4.NY_OPEN[0]) & (m <= h4.NY_OPEN[1])).tolist()
    assert flag == [True, True, False, True, True, False]


def test_future_perturbation_does_not_change_past_events(run):
    dev, _, ev, _, _ = run
    cut = int(len(dev) * 0.5)
    noisy = dev.copy()
    shift = np.random.default_rng(3).normal(0, 5, len(dev) - cut)
    for col in ("open", "high", "low", "close"):
        noisy.loc[cut:, col] = noisy.loc[cut:, col].to_numpy() + shift
    noisy.loc[cut:, "high"] = noisy.loc[cut:, ["open", "high", "low", "close"]].max(axis=1)
    noisy.loc[cut:, "low"] = noisy.loc[cut:, ["open", "high", "low", "close"]].min(axis=1)
    ev2, _, _ = h4.detect(h4.h4_features(h1.features(noisy)))
    key = ["direction", "exhaustion_index", "reentry_index", "stop", "entry", "target_r"]
    assert set(map(tuple, ev[ev["entry_index"] < cut][key].to_numpy())) == \
        set(map(tuple, ev2[ev2["entry_index"] < cut][key].to_numpy()))

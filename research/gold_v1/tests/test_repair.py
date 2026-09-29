"""Causality regression tests for the deep-history repair (DEEP_HISTORY_REPAIR_PREREGISTRATION.md, criterion A9).

    venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests/test_repair.py

The repair rule decides a removal from bar TIMESTAMPS only (a one-bar session: previous and next bar starts both
>= 60 min away). The next-bar dependency is a timestamp known at most 60 minutes after the bar, never a price.
These tests pin that:
  * prices never influence a removal;
  * adding / changing bars after time T cannot change the repair of any bar at or before T - 60 min;
  * on repaired data, ATR and frozen-H3 detection before T - 60 min cannot change when bars after T change.
Only raw_full rows inside the repair window are read (the 2021-09 holdout and later are never loaded).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
EXP = HERE.parent / "history_expansion"
sys.path.insert(0, str(EXP))
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h3"))
import h1_study as h1                                    # noqa: E402
import h3_study as h3                                    # noqa: E402
import repair_history as rh                              # noqa: E402


@pytest.fixture(scope="module")
def window():
    header, lines = rh.read_window("M15")
    return header, lines


def as_time(ts):
    return pd.to_datetime(pd.Series(ts), format=rh.FMT, utc=True)


def test_rule_is_timestamp_only_and_matches_preregistered_count(window):
    _, lines = window
    ts = [ln[:19] for ln in lines]
    mask = rh.one_bar_session_mask(ts)
    assert int(mask.sum()) == 164                                         # preregistered expectation
    # scrambling every price leaves the decision unchanged (the rule never sees prices)
    rng = np.random.default_rng(0)
    scrambled = [ln[:20] + ",".join(f"{v:.3f}" for v in rng.uniform(1, 9, 4)) + ln[ln.index(",", 20 + 1):]
                 for ln in lines[:2000]]
    assert np.array_equal(rh.one_bar_session_mask([ln[:19] for ln in scrambled]), rh.one_bar_session_mask(ts[:2000]))
    t = as_time(ts)
    for i in np.flatnonzero(mask):                                        # every removal is an isolated one-bar session
        assert (i == 0 or (t[i] - t[i - 1]).total_seconds() >= 3600) and \
               (i == len(t) - 1 or (t[i + 1] - t[i]).total_seconds() >= 3600)


@pytest.mark.parametrize("frac", [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95])
def test_future_bars_cannot_change_past_repair(window, frac):
    _, lines = window
    ts = [ln[:19] for ln in lines]
    cut = int(len(ts) * frac)
    full = rh.one_bar_session_mask(ts)
    t = as_time(ts)
    horizon = t[cut - 1] - pd.Timedelta(minutes=60)
    settled = (t[:cut] <= horizon).to_numpy()
    # (a) prefix only
    pre = rh.one_bar_session_mask(ts[:cut])
    assert np.array_equal(pre[settled], full[:cut][settled])
    # (b) prefix + arbitrary extra future bars (a bar 15 min after the cut and an isolated one later)
    last = t[cut - 1]
    extra = [(last + pd.Timedelta(minutes=15)).strftime(rh.FMT), (last + pd.Timedelta(hours=30)).strftime(rh.FMT)]
    alt = rh.one_bar_session_mask(ts[:cut] + extra)
    assert np.array_equal(alt[:cut][settled], full[:cut][settled])


def _frame(lines):
    rows = [ln.rstrip("\n").split(",") for ln in lines]
    f = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
    f["time"] = pd.to_datetime(f["timestamp"], format=rh.FMT, utc=True)
    for c in ("open", "high", "low", "close"):
        f[c] = f[c].astype(float)
    for c in ("tick_volume", "spread", "real_volume"):
        f[c] = f[c].astype(int)
    return f.drop(columns=["timestamp"]).reset_index(drop=True)


def _repaired(lines):
    mask = rh.one_bar_session_mask([ln[:19] for ln in lines])
    return [ln for ln, m in zip(lines, mask) if not m]


@pytest.mark.parametrize("cut_day", ["2018-08-15 12:00", "2018-09-10 03:00"])
def test_future_changes_cannot_alter_past_atr_or_h3_detection(window, cut_day):
    _, lines = window
    sub = [ln for ln in lines if "2018.06.01" <= ln[:10] < "2018.10.01"]      # includes July+ Sunday artifacts
    cut_t = pd.Timestamp(cut_day, tz="UTC")
    cut_s = cut_t.strftime(rh.FMT)
    prefix = [ln for ln in sub if ln[:19] < cut_s]
    # future: shift all later prices by +25 and append a spurious isolated bar
    future = []
    for ln in sub:
        if ln[:19] >= cut_s:
            p = ln.rstrip("\n").split(",")
            p[1:5] = [f"{float(v) + 25:.3f}" for v in p[1:5]]
            future.append(",".join(p) + "\n")
    spurious = (pd.to_datetime(future[-1][:19], format=rh.FMT) + pd.Timedelta(hours=30)).strftime(rh.FMT) + \
        ",1300.000,1400.000,1200.000,1350.000,99999,0,0\n"
    a = h3.h3_features(h1.features(_frame(_repaired(sub))))
    b = h3.h3_features(h1.features(_frame(_repaired(prefix + future + [spurious]))))
    c = h3.h3_features(h1.features(_frame(_repaired(prefix))))
    horizon = cut_t - pd.Timedelta(minutes=60)
    for other in (b, c):
        n = int((a["time"] <= horizon).sum())
        assert a["time"].iloc[:n].equals(other["time"].iloc[:n])
        assert np.allclose(a["atr"].iloc[:n], other["atr"].iloc[:n], equal_nan=True)
        assert np.allclose(a["rng8_pct"].iloc[:n], other["rng8_pct"].iloc[:n], equal_nan=True)
        assert np.array_equal(a["compressed"].iloc[:n], other["compressed"].iloc[:n])
    key = ["direction", "displacement_index", "signal_index", "stop", "box_high", "box_low"]
    ea, _, _ = h3.detect(a)
    for other in (b, c):
        eo, _, _ = h3.detect(other)
        before = lambda e: set(map(tuple, e[e["entry_time"] <= horizon][key].to_numpy()))   # noqa: E731
        assert before(ea) == before(eo)

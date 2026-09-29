"""Regression tests for the corrected Gold V1 research pipeline (research/gold_v1/h1/h1_study.py) and the H2 layer.

    venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests

Synthetic frames pin each causality and precision property. The real-data tests read development rows only.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True                          # keep the frozen H1 folder byte-identical
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h2"))
import h1_study as h1                                    # noqa: E402
import h2_study as h2                                    # noqa: E402


def frame(days: list[tuple[str, str]], price=4000.0, seed=0) -> pd.DataFrame:
    """M15 bars for each (first bar, last bar) session, with a random walk around `price`."""
    rng = np.random.default_rng(seed)
    times = pd.DatetimeIndex([])
    for a, b in days:
        times = times.append(pd.date_range(a, b, freq="15min", tz="UTC"))
    n = len(times)
    close = price + np.cumsum(rng.normal(0, 1, n))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.1, 1, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1, n)
    return pd.DataFrame({"time": times, "open": open_, "high": high, "low": low, "close": close,
                         "tick_volume": rng.integers(50, 500, n), "spread": 280, "real_volume": 0})


TWO_DAYS = [("2026-01-05 23:00", "2026-01-06 21:45"), ("2026-01-06 23:00", "2026-01-07 21:45")]


# 1. Asia-range causality ---------------------------------------------------------------------------------------------

def test_asia_range_invisible_before_it_exists():
    f0 = frame(TWO_DAYS)
    spike = f0.index[f0["time"] == pd.Timestamp("2026-01-07 03:00", tz="UTC")][0]
    f0.loc[spike, "high"] += 100                        # day 2's Asia high is set at 03:00
    f = h1.features(f0)
    day2 = f[f["tday"] == f["tday"].max()]
    pre_asia = day2[day2["time"] < pd.Timestamp("2026-01-07 00:00", tz="UTC")]         # 23:00-23:45 evening bars
    in_asia = day2[day2["hour"] < 7]
    after = day2[day2["time"] >= pd.Timestamp("2026-01-07 07:00", tz="UTC")]
    assert len(pre_asia) == 4 and pre_asia["asia_high"].isna().all()
    assert in_asia["asia_high"].isna().all()
    assert (after["asia_high"] == f0.loc[spike, "high"]).all()


def test_asia_range_prefix_invariant():
    f0 = frame(TWO_DAYS)
    full = h1.features(f0)
    for cut in (5, 40, 95, 100, len(f0) - 1):
        part = h1.features(f0.iloc[:cut].reset_index(drop=True))
        assert np.allclose(part["asia_high"], full["asia_high"].iloc[:cut], equal_nan=True)
        assert np.allclose(part["asia_low"], full["asia_low"].iloc[:cut], equal_nan=True)


# 2. weighted variance precision ----------------------------------------------------------------------------------------

def test_tvwap_sigma_full_precision_near_4000():
    f0 = frame(TWO_DAYS[:1], price=4000.0, seed=3)
    f0[["open", "high", "low", "close"]] = 4000.0 + (f0[["open", "high", "low", "close"]] - 4000.0) * 1e-3   # tiny σ
    f = h1.features(f0)
    tp = ((f0["high"] + f0["low"] + f0["close"]) / 3).to_numpy()
    w = f0["tick_volume"].to_numpy(float)
    worst = naive_worst = 0.0
    for k in range(len(f0)):
        m = np.average(tp[:k + 1], weights=w[:k + 1])
        sd = np.sqrt(np.average((tp[:k + 1] - m) ** 2, weights=w[:k + 1]))
        worst = max(worst, abs(sd - f["tvwap_sd"].iloc[k]), abs(m - f["tvwap"].iloc[k]))
        naive = np.sqrt(max((w[:k + 1] * tp[:k + 1] ** 2).sum() / w[:k + 1].sum() - m * m, 0.0))
        naive_worst = max(naive_worst, abs(naive - sd))
    assert worst < 1e-9
    assert naive_worst > 1e-6            # the uncentred E[x²] − m² formula would fail this test


# 3. UTC / DST ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("utc, session", [
    ("2026-03-06 12:00", "London"),       # 07:00 New York (EST): New York not open yet
    ("2026-03-09 12:00", "Overlap"),      # 08:00 New York (EDT from 03-08), 12:00 London (GMT)
    ("2026-03-27 06:45", "Asia"),         # Asia 00:00-07:00 UTC
    ("2026-03-27 07:00", "Other"),        # 07:00 London (GMT): London not open, Asia over
    ("2026-03-27 07:45", "Other"),
    ("2026-03-30 07:00", "London"),       # 08:00 London (BST from 03-29)
    ("2026-03-30 15:30", "New York"),     # 16:30 BST London closed, 11:30 New York
    ("2026-01-15 21:45", "New York"),     # 16:45 New York (EST)
    ("2026-05-15 21:00", "Other"),        # 17:00 New York (EDT) — closed
])
def test_sessions_follow_dst(utc, session):
    assert h1.session_of(pd.Timestamp(utc, tz="UTC")) == session


def test_timestamps_parse_as_utc_and_boundary_holds():
    dev = h1.load_dev()
    assert str(dev["time"].dt.tz) == "UTC"
    assert dev["time"].min() >= h1.DEV_START and dev["time"].max() < h1.DEV_END
    # the broker day ends at 17:00 New York in both EST and EDT
    last = dev.groupby(h1.trading_days(dev))["time"].max() + pd.Timedelta(minutes=15)
    ny = last.dt.tz_convert(h1.NEW_YORK)
    assert (ny.dt.hour == 17).mean() > 0.9


# 4. previous day ----------------------------------------------------------------------------------------------------

def test_previous_day_uses_completed_days_only():
    days = TWO_DAYS + [("2026-01-07 23:00", "2026-01-08 21:45")]
    f = h1.features(frame(days))
    ids = sorted(f["tday"].unique())
    assert f.loc[f["tday"] == ids[0], "pdh"].isna().all()
    for prev, cur in zip(ids, ids[1:]):
        p = f[f["tday"] == prev]
        c = f[f["tday"] == cur]
        assert (c["pdh"] == p["high"].max()).all() and (c["pdl"] == p["low"].min()).all()


# 5. TVWAP session reset ---------------------------------------------------------------------------------------------

def test_tvwap_resets_causally():
    f0 = frame(TWO_DAYS)
    f = h1.features(f0)
    tp = (f["high"] + f["low"] + f["close"]) / 3
    firsts = f.groupby("tday").head(1)
    assert np.allclose(firsts["tvwap"], tp[firsts.index]) and (firsts["tvwap_sd"] == 0).all()
    part = h1.features(f0.iloc[:100].reset_index(drop=True))
    assert np.allclose(part["tvwap"], f["tvwap"].iloc[:100]) and np.allclose(part["tvwap_sd"], f["tvwap_sd"].iloc[:100])


# H2 layer ------------------------------------------------------------------------------------------------------------

def test_h1_direction_and_expansion_use_completed_hours():
    f0 = frame([("2026-01-05 23:00", "2026-01-09 21:45")], seed=7)
    full = h2.h2_features(h1.features(f0))
    for cut in (130, 211, 300):
        part = h2.h2_features(h1.features(f0.iloc[:cut].reset_index(drop=True)))
        for c in ("dir_h1", "h1_expansion"):
            assert np.array_equal(part[c].to_numpy(), full[c].iloc[:cut].to_numpy())
    # a bar's direction never depends on its own (incomplete) hour
    hour = full["time"].dt.floor("1h")
    assert (full.groupby(hour)["dir_h1"].nunique(dropna=False) == 1).all()


def test_h2_events_prefix_invariant_and_stop_causal():
    dev = h1.load_dev()
    f = h2.h2_features(h1.features(dev))
    ev, _ = h2.detect(f)
    cut = int(len(dev) * 0.6)
    fp = h2.h2_features(h1.features(dev.iloc[:cut].reset_index(drop=True)))
    evp, _ = h2.detect(fp)
    inner = ev[ev["entry_index"] < cut]
    key = ["direction", "signal_index", "zone", "stop"]
    assert set(map(tuple, inner[key].to_numpy())) == set(map(tuple, evp[evp["entry_index"] < cut][key].to_numpy()))
    for e in ev.itertuples():
        window = f.iloc[e.extreme_index + 1: e.signal_index + 1]
        expect = window["low"].min() if e.direction == "long" else window["high"].max()
        assert e.stop == expect and e.entry_index == e.signal_index + 1

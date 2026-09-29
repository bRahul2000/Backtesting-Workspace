"""H3 regression tests: causality of the compression box, displacement/acceptance rules and duplicate suppression.

    venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v1/tests

Uses development rows only and the event detector only (no forward outcomes).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h3"))
import h1_study as h1                                    # noqa: E402
import h3_study as h3                                    # noqa: E402


@pytest.fixture(scope="module")
def dev():
    return h1.load_dev()


@pytest.fixture(scope="module")
def run(dev):
    f = h3.h3_features(h1.features(dev))
    ev, counts, acc = h3.detect(f)
    return f, ev, counts, acc


def test_events_exist_and_are_development_only(run):
    f, ev, _, _ = run
    assert len(ev) > 0
    assert ev["entry_time"].max() < h1.DEV_END


def test_box_excludes_displacement_bar_and_lies_in_one_day(run):
    f, ev, _, _ = run
    tday = f["tday"].to_numpy()
    for e in ev.itertuples():
        k, D = e.compression_index, e.displacement_index
        assert 1 <= D - k <= h3.LIFETIME
        assert tday[k - 7] == tday[k] == tday[D] == tday[e.signal_index] == tday[e.entry_index]
        assert e.box_high == f["high"].iloc[k - 7:k + 1].max() and e.box_low == f["low"].iloc[k - 7:k + 1].min()
        assert f["compressed"].iloc[k]
        closes = f["close"].iloc[k + 1:D]
        assert ((closes <= e.box_high) & (closes >= e.box_low)).all()          # rule 6: box intact until D


def test_displacement_acceptance_and_stop_rules(run):
    f, ev, _, _ = run
    for e in ev.itertuples():
        d = 1 if e.direction == "long" else -1
        D, A = f.iloc[e.displacement_index], f.iloc[e.signal_index]
        rng = D["high"] - D["low"]
        assert rng >= 1.5 * f["atr"].iloc[e.displacement_index - 1] - 1e-9
        assert abs(D["close"] - D["open"]) / rng >= 0.6 - 1e-12
        assert d * (D["close"] - D["open"]) > 0
        boundary = e.box_high if d == 1 else e.box_low
        assert d * (D["close"] - boundary) > 0 and d * (A["close"] - boundary) > 0
        assert e.stop == (D["low"] if d == 1 else D["high"])
        assert e.entry == f["open"].iloc[e.entry_index] and e.risk > 0


def test_one_event_per_structure_and_direction(run):
    _, ev, counts, _ = run
    assert not ev.duplicated(["structure_id", "direction"]).any()
    accepted = sum(counts["accepted_breakouts"].values())
    assert accepted == len(ev) + counts["suppressed_duplicates"] + counts["no_entry_bar"] + counts["rejected_risk_le_0"]


def test_future_perturbation_does_not_change_past_events(dev, run):
    _, ev, _, _ = run
    cut = int(len(dev) * 0.55)
    noisy = dev.copy()
    rng = np.random.default_rng(1)
    shift = rng.normal(0, 5, len(dev) - cut)
    for col in ("open", "high", "low", "close"):
        noisy.loc[cut:, col] = noisy.loc[cut:, col].to_numpy() + shift
    noisy.loc[cut:, "high"] = noisy.loc[cut:, ["open", "high", "low", "close"]].max(axis=1)
    noisy.loc[cut:, "low"] = noisy.loc[cut:, ["open", "high", "low", "close"]].min(axis=1)
    ev2, _, _ = h3.detect(h3.h3_features(h1.features(noisy)))
    key = ["direction", "displacement_index", "signal_index", "stop", "box_high", "box_low", "entry"]
    before = set(map(tuple, ev[ev["entry_index"] < cut][key].to_numpy()))
    after = set(map(tuple, ev2[ev2["entry_index"] < cut][key].to_numpy()))
    assert before == after

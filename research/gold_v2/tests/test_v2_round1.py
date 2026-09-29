"""Regression tests for Gold V2 round-1 code (C1 race rules, C4 circular-shift null, causality).

    venv/bin/python -m pytest -q -p no:cacheprovider research/gold_v2/tests
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "c1_round_number"))
sys.path.insert(0, str(HERE.parent / "c4_session_momentum"))
import c1_study as c1                                    # noqa: E402
import c4_study as c4                                    # noqa: E402


def frame(rows):
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    f["tday"] = 1
    return f


def one_event(level, side, d, i=1):
    return pd.DataFrame([{"group": "round", "i": i, "time": pd.Timestamp("2024-01-02", tz="UTC"), "tday": 1,
                          "level": level, "offset": 0.0, "side": side, "d": d}])


def test_touch_bar_continuation_only_is_continuation_and_reversal_hit_is_ambiguous():
    # from below at L=2000, d=2: touch bar reaching 2002 only -> continuation
    f = frame([(1999, 1999.5, 1998.5, 1999), (1999, 2002.5, 1998.5, 2002)])
    assert c1.race(f, one_event(2000, 1, 2.0))["result"].iloc[0] == "continuation"
    # touch bar also reaching 1998 (reversal target): order unknown -> ambiguous
    f = frame([(1999, 1999.5, 1998.9, 1999), (1999, 2000.5, 1997.5, 1999)])
    assert c1.race(f, one_event(2000, 1, 2.0))["result"].iloc[0] == "ambiguous"


def test_later_bar_race_and_same_bar_double_hit():
    f = frame([(1999, 1999.5, 1998.9, 1999), (1999, 2000.2, 1999.0, 1999.5), (1999.5, 1999.6, 1997.9, 1998)])
    assert c1.race(f, one_event(2000, 1, 2.0))["result"].iloc[0] == "reversal"
    f = frame([(1999, 1999.5, 1998.9, 1999), (1999, 2000.2, 1999.0, 1999.5), (1999.5, 2002.5, 1997.5, 1998)])
    assert c1.race(f, one_event(2000, 1, 2.0))["result"].iloc[0] == "ambiguous"


def test_first_touch_is_causal_and_placebo_never_round():
    f, t0, t1 = c1.load("dev")
    ev = c1.events(f, (0.0,), t0, t1, "round")
    pc = f["close"].shift().to_numpy()
    for e in ev.head(300).itertuples():
        assert (pc[e.i] < e.level <= f["high"].iat[e.i]) if e.side == 1 else (pc[e.i] > e.level >= f["low"].iat[e.i])
    pl = c1.events(f, c1.PLACEBO_PRIMARY, t0, t1, "placebo")
    assert not ((pl["level"] % 50) == 0).any()
    # causality: events up to a cut are identical when later bars are removed
    cut = len(f) // 2
    fp = f.iloc[:cut].copy()
    evp = c1.events(fp, (0.0,), t0, t1, "round")
    assert set(map(tuple, ev[ev.i < cut - 1][["i", "level", "side"]].to_numpy())) == \
        set(map(tuple, evp[evp.i < cut - 1][["i", "level", "side"]].to_numpy()))


def test_circular_shift_null_is_deterministic_and_detects_planted_signal():
    rng = np.random.default_rng(0)
    n = 400
    s = np.where(rng.random(n) > 0.5, 1.0, -1.0)
    y_null = rng.normal(0, 1, n)
    y_sig = 0.6 * s + rng.normal(0, 1, n)
    t = pd.Series(pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"))
    base = pd.DataFrame({"r_us": s, "us_start": t})
    r1 = c4.stats(base.assign(y_atr=y_null), 0.1)
    r2 = c4.stats(base.assign(y_atr=y_null), 0.1)
    assert r1["p_one_sided_circular_shift"] == r2["p_one_sided_circular_shift"]
    assert c4.stats(base.assign(y_atr=y_sig), 0.1)["p_one_sided_circular_shift"] < 0.01
    assert abs(c4.effect(s, y_sig) - np.cov(s, y_sig, bias=True)[0, 1]) < 1e-12

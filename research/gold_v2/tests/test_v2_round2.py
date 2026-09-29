"""Round-2 regression tests: M1 repair causality (R7), A race rules, C residual causality."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
V2 = HERE.parent
for d in ("a_round_continuation", "c_usd_residual", "data"):
    sys.path.insert(0, str(V2 / d))
import a_study as A                                      # noqa: E402
import c_study as C                                      # noqa: E402
import repair_m1 as RM                                   # noqa: E402


def test_m1_repair_rule_is_timestamp_only_and_causal():
    _, lines = RM.window_lines()
    ts = [ln[:19] for ln in lines]
    full = RM.one_bar_session_mask(ts)
    assert int(full.sum()) == 167
    t = pd.to_datetime(pd.Series(ts), format="%Y.%m.%d %H:%M:%S", utc=True)
    for frac in (0.1, 0.37, 0.64, 0.9):
        cut = int(len(ts) * frac)
        settled = (t[:cut] <= t[cut - 1] - pd.Timedelta(minutes=60)).to_numpy()
        extra = [(t[cut - 1] + pd.Timedelta(minutes=1)).strftime("%Y.%m.%d %H:%M:%S")]
        for alt in (RM.one_bar_session_mask(ts[:cut]), RM.one_bar_session_mask(ts[:cut] + extra)[:cut]):
            assert np.array_equal(alt[settled], full[:cut][settled])


def _f(rows):
    f = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    f["tday"] = 1
    return f


def _ev(level, side, d):
    return pd.DataFrame([{"group": "round", "i": 1, "time": pd.Timestamp("2019-01-02", tz="UTC"), "tday": 1,
                          "level": level, "offset": 0.0, "side": side, "d": d}])


def test_a_race_from_above_continuation_and_ambiguity():
    # from above at L=1300, d=2: continuation target 1298 (down), reversal 1302 (up)
    f = _f([(1301, 1301.5, 1300.5, 1301), (1301, 1301.2, 1297.5, 1298)])      # touch bar reaches 1298 only
    assert A.race(f, _ev(1300, -1, 2.0))["result"].iloc[0] == "continuation"
    f = _f([(1301, 1301.5, 1300.5, 1301), (1301, 1302.5, 1299.5, 1300)])      # touch bar reaches reversal target
    assert A.race(f, _ev(1300, -1, 2.0))["result"].iloc[0] == "ambiguous"
    f = _f([(1301, 1301.5, 1300.5, 1301), (1301, 1301.2, 1299.8, 1300.5), (1300.5, 1302.4, 1300.1, 1302)])
    assert A.race(f, _ev(1300, -1, 2.0))["result"].iloc[0] == "reversal"


def test_c_residual_state_is_causal():
    C.PERIODS["t_full"] = ("2023.01.02 00:00:00", "2023-02-01", "2023-03-01", "2023.03.01 00:00:00")
    C.PERIODS["t_cut"] = ("2023.01.02 00:00:00", "2023-02-01", "2023-02-15", "2023.02.15 00:00:00")
    a = C.build("t_full", "DXYm")
    b = C.build("t_cut", "DXYm")
    common = b.index[b.index < pd.Timestamp("2023-02-14 20:00", tz="UTC")]
    for col in ("beta", "z", "sd_g", "e"):
        assert np.allclose(a.loc[common, col].astype(float), b.loc[common, col].astype(float), equal_nan=True), col
    assert (a.loc[common, "vol_regime"].fillna("NA") == b.loc[common, "vol_regime"].fillna("NA")).all()

"""Tests for the Gold V2 sealed-aware data layer."""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "data"))
import v2_data as vd                                     # noqa: E402


def test_sealed_windows():
    assert vd.is_sealed("2021.09.01 00:00:00") and vd.is_sealed("2022.11.26 23:45:00")
    assert not vd.is_sealed("2022.11.27 00:00:00") and not vd.is_sealed("2021.08.31 23:59:00")
    assert vd.is_sealed("2026.06.03 00:00:00") and vd.is_sealed("2026.09.18 12:00:00")
    assert not vd.is_sealed("2026.06.02 23:59:00")
    assert vd.overlaps_sealed("2021.08.01 00:00:00", "2021.10.01 00:00:00")
    assert not vd.overlaps_sealed("2023.01.01 00:00:00", "2025.12.23 00:00:00")


def test_loader_skips_sealed_lines_before_parsing(tmp_path):
    p = tmp_path / "x.csv"
    lines = ["timestamp,open,high,low,close,tick_volume,spread,real_volume",
             "2021.08.31 20:00:00,1,2,0.5,1.5,10,5,0",
             "2021.09.01 01:00:00,NOT,A,NUMBER,!,x,y,z",          # sealed: must never be parsed
             "2022.11.28 01:00:00,3,4,2.5,3.5,11,6,0",
             "2026.07.01 01:00:00,NOT,A,NUMBER,!,x,y,z"]         # sealed
    p.write_text("\n".join(lines) + "\n")
    f = vd.load_bars([p], "2021.01.01 00:00:00", "2027.01.01 00:00:00")
    assert len(f) == 2 and f.attrs["sealed_lines_skipped"] == 2


def test_aggregation_matches_mt5_grid():
    t = pd.date_range("2024-01-02 10:00", periods=30, freq="1min", tz="UTC")
    m1 = pd.DataFrame({"time": t, "open": range(30), "high": [x + 1 for x in range(30)],
                       "low": [x - 1 for x in range(30)], "close": [x + 0.5 for x in range(30)], "tick_volume": 1})
    a = vd.aggregate(m1, 15)
    assert list(a.index) == [pd.Timestamp("2024-01-02 10:00", tz="UTC"), pd.Timestamp("2024-01-02 10:15", tz="UTC")]
    r = a.iloc[0]
    assert (r.open, r.high, r.low, r.close, r.tick_volume) == (0, 15, -1, 14.5, 15)

"""Gold V2 round 2 — non-outcome screening on the new data (alignment, M1 artifact scan, C1 ambiguity at M1, power).

    venv/bin/python research/gold_v2/data/round2_screen.py

No directional outcome, reversal/continuation rate, return or race result is computed or printed.
The C1 ambiguity measurement uses ONLY the 2023–2025 development events (where C1 outcomes were already computed)
and reports ONLY the share of events whose touch ordering is unresolvable at M15 vs at M1 — never which side won.
The 2017–2021 era is measured for data cleanliness only (no touch events there). Sealed lines are never parsed.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v2_data as vd                                                                     # noqa: E402

ROOT = HERE.parents[2]
R = HERE / "raw"
NY = ZoneInfo("America/New_York")
C1_EVENTS = ROOT / "research/gold_v2/c1_round_number/dev/events.csv"
DEV_M15 = ROOT / "research/gold_v1/history_expansion/h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv"


def m1(sym: str, a: str, b: str) -> pd.DataFrame:
    return vd.load_bars(sorted(glob.glob(str(R / f"v2_m1_{sym}_*.csv"))), a, b)


def alignment(x: pd.DataFrame, o: pd.DataFrame, name: str) -> dict:
    """Minute-level co-occurrence inside XAU's own trading minutes, and M15 co-occurrence; session-hour profile."""
    xs, os_ = set(x["time"]), set(o["time"])
    common = xs & os_
    xa, oa = vd.aggregate(x, 15), vd.aggregate(o, 15)
    c15 = xa.index.intersection(oa.index)
    xh = x["time"].dt.tz_convert(NY).dt.hour
    miss = x[~x["time"].isin(os_)]
    return {"pair": f"XAUUSDm vs {name}", "xau_m1": len(xs), "other_m1": len(os_),
            "xau_minutes_with_other_bar": round(len(common) / len(xs), 4),
            "xau_m15_with_other_m15": round(len(c15) / len(xa), 4),
            "other_m15_without_xau": int(len(oa.index.difference(xa.index))),
            "missing_other_minutes_by_ny_hour_top": miss["time"].dt.tz_convert(NY).dt.hour.value_counts().head(5).to_dict(),
            "xau_ny_hour_coverage_min": round(float(x.assign(h=xh, has=x["time"].isin(os_)).groupby("h")["has"].mean().min()), 4)}


def isolated_m1(x: pd.DataFrame) -> pd.DataFrame:
    t = x["time"]
    gp = t.diff().dt.total_seconds().div(60).fillna(1e9)
    gn = (-t.diff(-1)).dt.total_seconds().div(60).fillna(1e9)
    return x[(gp >= 60) & (gn >= 60)]


def c1_ambiguity_at_m1() -> dict:
    """For each C1 dev event (round and placebo; 2023–2025), locate the FIRST M1 bar inside the touch M15 bar that
    touches the level from the approach side, and ask only: does that M1 bar ALSO reach the reversal target
    (ordering unresolvable at M1)? Returns shares of unresolvable events; no reversal/continuation counts."""
    ev = pd.read_csv(C1_EVENTS, parse_dates=["time"])
    ev = ev[["group", "time", "level", "side", "d"]]
    x = m1("XAUUSDm", "2022.12.31 00:00:00", "2025.12.23 00:00:00").set_index("time")
    prev_close = x["close"].shift()
    out = {}
    for g, df in ev.groupby("group"):
        amb_m15 = amb_m1 = located = 0
        for e in df.itertuples():
            win = x.loc[e.time: e.time + pd.Timedelta(minutes=14)]
            pc = prev_close.loc[e.time: e.time + pd.Timedelta(minutes=14)]
            if win.empty:
                continue
            rev = e.level - e.side * e.d
            # M15-level ambiguity (as preregistered): touch bar reaches the reversal target
            if (win["low"].min() <= rev) if e.side == 1 else (win["high"].max() >= rev):
                amb_m15 += 1
            touch = (pc < e.level) & (win["high"] >= e.level) if e.side == 1 else (pc > e.level) & (win["low"] <= e.level)
            if not touch.any():
                continue
            located += 1
            tb = win[touch].iloc[0]
            if (tb["low"] <= rev) if e.side == 1 else (tb["high"] >= rev):
                amb_m1 += 1
        n = len(df)
        out[g] = {"events": n, "touch_located_in_m1": located,
                  "unresolvable_at_m15_share": round(amb_m15 / n, 4),
                  "unresolvable_at_m1_share_of_located": round(amb_m1 / max(1, located), 4)}
    return out


def power(n_events: int, p0: float = 0.5, k: float = 2.0) -> float:
    return round(2.8 * math.sqrt(p0 * (1 - p0) * (1 / n_events + 1 / (k * n_events))) * 100, 1)


def main() -> None:
    res = {}
    span = ("2022.11.27 23:00:00", "2026.06.03 00:00:00")          # post-holdout, pre-validation
    x = m1("XAUUSDm", *span)
    for s in ("XAGUSDm", "EURUSDm", "DXYm", "USDJPYm"):
        res[f"alignment_{s}_2022_11_to_2026_06"] = alignment(x, m1(s, *span), s)
    xj = m1("XAUUSDm", "2017.04.27 00:00:00", "2021.08.31 22:00:00")
    res["alignment_USDJPYm_2017_2021"] = alignment(xj, m1("USDJPYm", "2017.04.27 00:00:00", "2021.08.31 22:00:00"), "USDJPYm")
    iso = isolated_m1(xj)
    res["xau_m1_2017_2021"] = {
        "bars": len(xj), "isolated_one_bar_sessions": len(iso),
        "isolated_by_weekday_time": iso["time"].dt.strftime("%a %H:%M").value_counts().to_dict(),
        "isolated_first": str(iso["time"].min()), "isolated_last": str(iso["time"].max()),
        "intraday_holes_by_year": {int(y): int(v) for y, v in xj.assign(g=xj["time"].diff().dt.total_seconds().div(60))
                                   .query("g > 1 and g < 60").groupby(xj["time"].dt.year).size().items()},
        "dec_2019_bars": int(((xj["time"] >= pd.Timestamp("2019-12-01", tz="UTC")) &
                              (xj["time"] < pd.Timestamp("2019-12-23", tz="UTC"))).sum()),
        "spread_zero_share": round(float((xj["spread"] == 0).mean()), 4)}
    res["c1_touch_ordering_resolution_dev_2023_2025"] = c1_ambiguity_at_m1()
    (HERE / "audit" / "round2_screen.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(json.dumps(res, indent=1, default=str))


if __name__ == "__main__":
    main()

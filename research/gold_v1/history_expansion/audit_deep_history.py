"""Gold V1 — deep XAUUSDm history audit (server earliest → 2019-12), history quality only, no strategy outcomes.

    venv/bin/python research/gold_v1/history_expansion/audit_deep_history.py

Reads raw_full/ (new snapshot) and raw/ (2019-12-23 → 2026-09-29 evidence snapshot). Row groups by timestamp TEXT,
split before any parsing:
  OLD       < 2019-12-23                      full quality audit (never-seen era)
  ARTIFACT  2019-12-23 … 2021-08-31           known contaminated era: parsed only to locate the artifact boundary
  HOLDOUT   2021-09-01 … 2022-11-27 22:59      SEALED — line-text equality counts vs raw/ only
  REPLIC    2022-11-27 23:00 … 2025-12-22 22:59 already-used replication slice: line-text equality only
  DEV+      2025-12-22 23:00 onward            development, sealed validation/OOS, later: line-text equality only
Writes deep_audit_results.json and deep_gaps_M15.csv. Reuses the functions of audit_history.py unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audit_history as ah                                                              # noqa: E402

FULL = HERE / "raw_full"
PREV = HERE / "raw"
GROUPS = [("OLD", "0000", "2019.12.23"), ("ARTIFACT", "2019.12.23", "2021.09.01"),
          ("HOLDOUT", "2021.09.01", "2022.11.27 23:00:00"), ("REPLIC", "2022.11.27 23:00:00", "2025.12.22 23:00:00"),
          ("DEV+", "2025.12.22 23:00:00", "9999")]


def split(path: Path) -> tuple[str, dict[str, list[str]]]:
    out = {g: [] for g, _, _ in GROUPS}
    with open(path) as fh:
        header = fh.readline()
        for line in fh:
            ts = line[:19]
            for g, lo, hi in GROUPS:
                if lo <= ts < hi:
                    out[g].append(line)
                    break
    return header, out


def text_overlap(new: list[str], old: list[str]) -> dict:
    """Line-text comparison only (used for sealed / already-used groups): no value is parsed."""
    ts_new, ts_old = {ln[:19] for ln in new}, {ln[:19] for ln in old}
    common = ts_new & ts_old
    return {"rows_new": len(new), "rows_prev": len(old), "timestamps_common": len(common),
            "identical_lines": len(set(new) & set(old)), "timestamps_only_new": len(ts_new - ts_old),
            "timestamps_only_prev": len(ts_old - ts_new),
            "only_new_first": min(ts_new - ts_old) if ts_new - ts_old else None,
            "only_new_last": max(ts_new - ts_old) if ts_new - ts_old else None}


def lone_bars(f: pd.DataFrame, bar_minutes: int) -> pd.DataFrame:
    """Bars isolated by > 60 min on both sides, and whether they equal the aggregate of the NEXT session up to the
    following 00:00 UTC (the 'future bar' artifact signature)."""
    t = f["time"]
    gp = t.diff().dt.total_seconds().div(60)
    gn = (-t.diff(-1)).dt.total_seconds().div(60)
    idx = np.flatnonzero(((gp > 60) & (gn > 60)).to_numpy())
    rows = []
    for i in idx:
        r = f.iloc[i]
        nxt_start = i + 1
        if nxt_start >= len(f):
            continue
        day_end = f["time"].iloc[nxt_start].normalize() + pd.Timedelta(days=1)
        s = f[(f["time"] >= f["time"].iloc[nxt_start]) & (f["time"] < day_end)]
        rows.append({"bar": str(r.time), "weekday": r.time.day_name(), "hhmm": r.time.strftime("%H:%M"),
                     "tick_volume": int(r.tick_volume), "next_session_first": str(s["time"].iloc[0]),
                     "hours_before_next_session": (s["time"].iloc[0] - r.time).total_seconds() / 3600,
                     "high_eq_next": bool(r.high == s["high"].max()), "low_eq_next": bool(r.low == s["low"].min()),
                     "close_eq_next": bool(r.close == s["close"].iloc[-1]),
                     "tv_ratio_next": round(r.tick_volume / max(1, s["tick_volume"].sum()), 3)})
    return pd.DataFrame(rows)


def main() -> None:
    res = {}
    for tf, minutes in (("M15", 15), ("H1", 60)):
        hdr, new = split(FULL / f"xauusd_XAUUSDm_{tf}.csv")
        hdr_prev, prev = split(PREV / f"xauusd_XAUUSDm_{tf}.csv")
        r = {"header_equal_prev": hdr == hdr_prev,
             "rows_by_group_new": {g: len(v) for g, v in new.items()},
             "rows_by_group_prev": {g: len(v) for g, v in prev.items()},
             "text_overlap": {g: text_overlap(new[g], prev[g]) for g in ("ARTIFACT", "HOLDOUT", "REPLIC", "DEV+")}}
        frame = ah.parse(new["OLD"] + new["ARTIFACT"])                     # OLD audited; ARTIFACT for the boundary
        q, gaps = ah.quality(frame, minutes, tf)
        r["quality_old_plus_artifact"] = {k: v for k, v in q.items() if k != "holiday_gaps"}
        r["holiday_gaps_count_by_year"] = pd.Series([int(g["prev_bar"][:4]) for g in q["holiday_gaps"]]).value_counts().sort_index().to_dict() if q["holiday_gaps"] else {}
        lb = lone_bars(frame, minutes)
        r["lone_bars"] = {"count": len(lb),
                          "by_year_weekday_time": {" ".join(k): int(v) for k, v in lb.assign(y=lb["bar"].str[:4]).groupby(["y", "weekday", "hhmm"]).size().items()} if len(lb) else {},
                          "first": lb["bar"].min() if len(lb) else None, "last": lb["bar"].max() if len(lb) else None,
                          "share_high_low_close_eq_next_session": float((lb.high_eq_next & lb.low_eq_next & lb.close_eq_next).mean()) if len(lb) else None}
        lb.to_csv(HERE / f"deep_lone_bars_{tf}.csv", index=False)
        gaps.to_csv(HERE / f"deep_gaps_{tf}.csv", index=False)
        if tf == "M15":
            r["by_year"] = ah.by_year(frame)
            r["largest_open_jumps"] = ah.jumps_list(frame, top=20)
            m15 = frame
        else:
            r["m15_h1_alignment"] = ah.m15_h1_alignment(m15, frame)
            r["h1_by_year"] = {int(y): len(g) for y, g in frame.groupby(frame["time"].dt.year)}
        res[tf] = r
    (HERE / "deep_audit_results.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print("written deep_audit_results.json")


if __name__ == "__main__":
    main()

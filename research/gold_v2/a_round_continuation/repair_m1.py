"""Gold V2 A — preregistered structural repair of XAUUSDm M1, 2017-05-01 → 2021-08-31 21:59 (data only).

    venv/bin/python research/gold_v2/a_round_continuation/repair_m1.py repair
    venv/bin/python research/gold_v2/a_round_continuation/repair_m1.py audit

Implements A_M1_REPAIR_PREREGISTRATION.md. Rule (timestamps only): remove an M1 bar iff it forms a one-bar session
under the frozen session rule (previous and next bar starts both >= 60 min away). Raw files are verified against
SHA256SUMS first and never modified. The repaired CSV goes to data/derived/ (git-ignored payload); its hash, the
removal manifest and the audit are committed.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V2 = HERE.parent
ROOT = V2.parents[1]
sys.path.insert(0, str(V2 / "data"))
sys.path.insert(0, str(ROOT / "research/gold_v1/history_expansion"))
import v2_data as vd                                                                     # noqa: E402

RAW_FILES = [V2 / f"data/raw/v2_m1_XAUUSDm_{y}.csv" for y in (2017, 2018, 2019, 2020, 2021)]
OUT = V2 / "data/derived"
OUT_FILE = OUT / "xauusd_m1_2017_2021_repaired.csv"
WIN_START, WIN_END = "2017.05.01 00:00:00", "2021.08.31 22:00:00"
ERA_START = pd.Timestamp("2017-06-01", tz="UTC")
NY = ZoneInfo("America/New_York")
M15_REF = ROOT / "research/gold_v1/history_expansion/repaired/xauusd_XAUUSDm_M15_repaired.csv"
KNOWN_HOLE = (pd.Timestamp("2019-11-29", tz="UTC"), pd.Timestamp("2019-12-23", tz="UTC"))   # V1 M15 export hole
KNOWN_OUTAGES = [pd.Timestamp(x, tz="UTC") for x in ("2018-01-31 14:00", "2018-08-16 08:45", "2018-08-27 02:15",
                                                        "2018-08-27 09:30")]
CLOSURE_DATES_NY = {"2018-03-29": "GOOD_FRIDAY_EVE_AFTER_CLOSE", "2018-12-25": "CHRISTMAS_DAY",
                    "2019-12-25": "CHRISTMAS_DAY", "2020-01-01": "NEW_YEARS_DAY"}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_raw() -> None:
    sums = dict(line.split("  ")[::-1] for line in (V2 / "data/raw/SHA256SUMS").read_text().split("\n") if line)
    for p in RAW_FILES:
        assert sha(p) == sums[p.name], f"raw hash mismatch {p.name}"


def window_lines() -> tuple[str, list[str]]:
    lines, header = [], None
    for p in RAW_FILES:
        with open(p) as fh:
            h = fh.readline()
            header = header or h
            for line in fh:
                if WIN_START <= line[:19] < WIN_END:
                    lines.append(line)
    return header, lines


def one_bar_session_mask(ts: list[str]) -> np.ndarray:
    t = pd.to_datetime(pd.Series(ts), format=vd.FMT, utc=True)
    dp = t.diff().dt.total_seconds().div(60).fillna(np.inf)
    dn = (-t.diff(-1)).dt.total_seconds().div(60).fillna(np.inf)
    return ((dp >= 60) & (dn >= 60)).to_numpy()


def reason(t: pd.Timestamp) -> str:
    ny = t.tz_convert(NY)
    if ny.weekday() == 5:
        return "WEEKEND_SATURDAY_NY"
    return CLOSURE_DATES_NY.get(ny.strftime("%Y-%m-%d"), "UNCLASSIFIED")


def repair() -> None:
    verify_raw()
    OUT.mkdir(exist_ok=True)
    header, lines = window_lines()
    ts = [ln[:19] for ln in lines]
    mask = one_bar_session_mask(ts)
    kept = [ln for ln, m in zip(lines, mask) if not m]
    OUT_FILE.write_text(header + "".join(kept))
    tt = pd.to_datetime(pd.Series(ts), format=vd.FMT, utc=True)
    man = pd.DataFrame([{"timestamp": ts[i], "reason_code": reason(tt.iat[i]),
                         "ny_time": tt.iat[i].tz_convert(NY).strftime("%a %Y-%m-%d %H:%M"), "raw_line": lines[i].rstrip("\n")}
                        for i in np.flatnonzero(mask)])
    man.to_csv(HERE / "m1_repair_removal_manifest.csv", index=False)
    summary = {"rows_before": len(lines), "rows_removed": int(mask.sum()), "rows_after": len(kept),
               "repaired_sha256": sha(OUT_FILE), "raw_files": {p.name: sha(p) for p in RAW_FILES}}
    (HERE / "m1_repair_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "raw_files"}))


def audit() -> None:
    import audit_history as ah                                                           # V1 helpers, read-only
    verify_raw()
    summ = json.loads((HERE / "m1_repair_summary.json").read_text())
    assert sha(OUT_FILE) == summ["repaired_sha256"]
    man = pd.read_csv(HERE / "m1_repair_removal_manifest.csv")
    checks, res = {}, {}
    checks["R1_removals_all_in_known_closures"] = bool((man["reason_code"] != "UNCLASSIFIED").all())
    res["removal_categories"] = man["reason_code"].value_counts().to_dict()
    _, raw_lines = window_lines()
    rep_lines = OUT_FILE.read_text().splitlines(keepends=True)[1:]
    raw_set = set(raw_lines)
    checks["R2_untouched_rows_identical"] = bool(all(ln in raw_set for ln in rep_lines)
                                                 and len(rep_lines) == len(raw_lines) - len(man))
    f = vd.load_bars([OUT_FILE], WIN_START, WIN_END)
    tday = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    checks["R3_no_one_bar_sessions"] = bool((f.groupby(tday).size() > 1).all())
    checks["R3_no_saturday_ny_bars"] = bool((f["time"].dt.tz_convert(NY).dt.weekday != 5).all())
    bad = (f["high"] < f[["open", "close"]].max(axis=1)) | (f["low"] > f[["open", "close"]].min(axis=1)) | (f["high"] < f["low"])
    checks["R4_integrity"] = bool(f["time"].is_monotonic_increasing and not f["time"].duplicated().any()
                                  and not bad.any() and (f["time"].dt.second == 0).all())
    # R5 M1 -> M15 parity with the audited repaired M15 reference
    agg = vd.aggregate(f, 15)
    ref = vd.load_bars([M15_REF], "2017.06.01 00:00:00", WIN_END).set_index("time")
    both = ref.join(agg, how="left", lsuffix="_ref", rsuffix="_m1")
    mism = {c: int(((both[f"{c}_ref"] - both[f"{c}_m1"]).abs() > 5e-4).sum() + both[f"{c}_m1"].isna().sum())
            for c in ("open", "high", "low", "close")}
    extra = agg.index[(agg.index >= ref.index.min())].difference(ref.index)
    extra_outside_hole = [str(t) for t in extra if not (KNOWN_HOLE[0] <= t < KNOWN_HOLE[1])]
    checks["R5_m15_parity"] = bool(all(v == 0 for v in mism.values()) and not extra_outside_hole)
    res["m15_parity"] = {"ref_bars": len(ref), "mismatches": mism, "extra_m15_bars": len(extra),
                         "extra_outside_known_2019_hole": extra_outside_hole[:20]}
    # R6 gaps >= 60 min in the era explained (holiday class only for gaps <= 4 days) or known outages
    q, gaps = ah.quality(f, 1, "M1")
    gaps["t"] = pd.to_datetime(gaps["prev_bar"])
    era = gaps[(gaps["t"] >= ERA_START) & (gaps["gap_min"] >= 60)]
    long_holiday = era[era["kind"].isin(["holiday/early_close", "weekend+holiday"]) & (era["gap_min"] > 4 * 1440)]
    # amendment 1: known outages matched by the M15 bar containing the M1 last bar; M1-granularity break variants
    last_ny = (era["t"]).dt.tz_convert(NY)
    first_ny = pd.to_datetime(era["next_bar"]).dt.tz_convert(NY)
    lm = last_ny.dt.hour * 60 + last_ny.dt.minute
    fm = first_ny.dt.hour * 60 + first_ny.dt.minute
    m1_variant = (lm >= 16 * 60 + 30) & (lm <= 17 * 60 + 15) & (fm >= 17 * 60 + 45) & (fm <= 19 * 60 + 15) & (era["gap_min"] <= 150)
    known = era["t"].dt.floor("15min").isin(KNOWN_OUTAGES)
    unexpl = era[(era["kind"] == "UNEXPLAINED") & ~known & ~m1_variant]
    res["amendment_1_reclassified"] = era[(era["kind"] == "UNEXPLAINED") & (known | m1_variant)][
        ["prev_bar", "next_bar", "gap_min"]].to_dict("records")
    checks["R6_all_long_gaps_explained"] = bool(len(unexpl) == 0 and len(long_holiday) == 0)
    res["era_gap_kinds_ge60"] = era["kind"].value_counts().to_dict()
    res["unexplained"] = unexpl[["prev_bar", "next_bar", "gap_min", "close_ny", "reopen_ny"]].to_dict("records")
    res["holiday_gaps_over_4_days"] = long_holiday[["prev_bar", "next_bar", "gap_min"]].to_dict("records")
    res["intraday_holes_lt60_by_year"] = {int(y): int(n) for y, n in gaps[(gaps["gap_min"] < 60)].groupby(gaps["t"].dt.year).size().items()}
    res["rows"] = {"before": summ["rows_before"], "removed": summ["rows_removed"], "after": summ["rows_after"]}
    res["checks"] = checks
    res["result"] = "PASS" if all(checks.values()) else "FAIL"
    (HERE / "m1_repair_audit.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(res["result"], json.dumps(checks), json.dumps(res["m15_parity"]), res["unexplained"], res["holiday_gaps_over_4_days"])


if __name__ == "__main__":
    {"repair": repair, "audit": audit}[sys.argv[1]]()

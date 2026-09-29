"""Gold V1 — preregistered mechanical repair of the 2017-05 → 2021-08 XAUUSDm M15/H1 history (data only).

    venv/bin/python research/gold_v1/history_expansion/repair_history.py repair   # write repaired/ + manifests
    venv/bin/python research/gold_v1/history_expansion/repair_history.py audit    # post-repair audit (A1–A10)
    venv/bin/python research/gold_v1/history_expansion/repair_history.py count    # H3 DETECTION-ONLY counts (audit PASS only)

Implements DEEP_HISTORY_REPAIR_PREREGISTRATION.md. Rows are selected from raw_full/ by timestamp TEXT in
[WINDOW_START, WINDOW_END_EXCL) — the reserved 2021-09 holdout and everything later are never read.
REMOVAL RULE (timestamps only): an M15 bar is removed iff it forms a one-bar session under the frozen session rule,
i.e. the start of the previous bar is >= 60 min earlier AND the start of the next bar is >= 60 min later.
H1: an H1 bar is removed iff no M15 bar remains in its hour after the M15 repair (derived, timestamps only).
Prices are never used to decide a removal; the price signature is computed afterwards as validation evidence only.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402
from zoneinfo import ZoneInfo                                                           # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw_full"
OUT = HERE / "repaired"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h3"))

WINDOW_START = "2017.05.01 00:00:00"          # warm-up month + era
WINDOW_END_EXCL = "2021.08.31 22:00:00"       # the 2021-09-01 trading session (holdout) opens here
ERA_START = pd.Timestamp("2017-06-01", tz="UTC")
NY = ZoneInfo("America/New_York")
FMT = "%Y.%m.%d %H:%M:%S"
# preregistered known genuine outages / short holes (DEEP_HISTORY_AUDIT.md): (last bar before, first bar after), UTC
KNOWN_OUTAGES = [("2018-01-31 14:00", "2018-02-02 12:45"), ("2018-08-16 08:45", "2018-08-16 09:30"),
                 ("2018-08-27 02:15", "2018-08-27 05:30"), ("2018-08-27 09:30", "2018-08-27 10:45")]
CLOSURE_DATES_NY = {"2017-05-29": "MEMORIAL_DAY_AFTER_EARLY_CLOSE", "2018-03-29": "GOOD_FRIDAY_EVE_AFTER_CLOSE",
                    "2018-12-25": "CHRISTMAS_DAY", "2019-12-25": "CHRISTMAS_DAY", "2020-01-01": "NEW_YEARS_DAY",
                    "2020-12-25": "CHRISTMAS_DAY", "2021-01-01": "NEW_YEARS_DAY", "2019-01-01": "NEW_YEARS_DAY",
                    "2018-01-01": "NEW_YEARS_DAY", "2017-12-25": "CHRISTMAS_DAY", "2019-04-19": "GOOD_FRIDAY",
                    "2020-04-10": "GOOD_FRIDAY", "2021-04-02": "GOOD_FRIDAY", "2019-04-18": "GOOD_FRIDAY_EVE_AFTER_CLOSE",
                    "2020-04-09": "GOOD_FRIDAY_EVE_AFTER_CLOSE", "2021-04-01": "GOOD_FRIDAY_EVE_AFTER_CLOSE"}


def read_window(tf: str) -> tuple[str, list[str]]:
    lines = []
    with open(RAW / f"xauusd_XAUUSDm_{tf}.csv") as fh:
        header = fh.readline()
        for line in fh:
            if WINDOW_START <= line[:19] < WINDOW_END_EXCL:
                lines.append(line)
    return header, lines


def one_bar_session_mask(timestamps: list[str]) -> np.ndarray:
    """THE REPAIR RULE — timestamps only. True where the bar is a one-bar session (both neighbouring bar starts
    >= 60 min away). First/last bar of the input: the missing neighbour counts as >= 60 min (a boundary bar can only
    be removed if its other neighbour is also >= 60 min away)."""
    t = pd.to_datetime(pd.Series(timestamps), format=FMT, utc=True)
    dp = t.diff().dt.total_seconds().div(60).fillna(np.inf)
    dn = (-t.diff(-1)).dt.total_seconds().div(60).fillna(np.inf)
    return ((dp >= 60) & (dn >= 60)).to_numpy()


def reason(ts: pd.Timestamp) -> str:
    ny = ts.tz_convert(NY)
    if ny.weekday() == 5:
        return "WEEKEND_SATURDAY_NY"
    if ny.weekday() == 6 and ny.hour < 17:
        return "WEEKEND_SUNDAY_NY_BEFORE_OPEN"
    code = CLOSURE_DATES_NY.get(ny.strftime("%Y-%m-%d"))
    return code if code else "UNCLASSIFIED"


def repair() -> dict:
    OUT.mkdir(exist_ok=True)
    rep = {}
    header, lines = read_window("M15")
    ts = [ln[:19] for ln in lines]
    mask = one_bar_session_mask(ts)
    kept = [ln for ln, m in zip(lines, mask) if not m]
    removed = [ln for ln, m in zip(lines, mask) if m]
    (OUT / "xauusd_XAUUSDm_M15_repaired.csv").write_text(header + "".join(kept))
    man = []
    t_all = pd.to_datetime(pd.Series(ts), format=FMT, utc=True)
    for i in np.flatnonzero(mask):
        t = t_all.iloc[i]
        man.append({"timeframe": "M15", "timestamp": ts[i], "reason_code": reason(t),
                    "ny_time": t.tz_convert(NY).strftime("%a %Y-%m-%d %H:%M"),
                    "gap_prev_min": (t - t_all.iloc[i - 1]).total_seconds() / 60 if i > 0 else None,
                    "gap_next_min": (t_all.iloc[i + 1] - t).total_seconds() / 60 if i + 1 < len(t_all) else None,
                    "raw_line": lines[i].rstrip("\n")})
    rep["M15"] = {"rows_before": len(lines), "rows_removed": len(removed), "rows_after": len(kept)}
    # H1: derived from the repaired M15 hours
    h_header, h_lines = read_window("H1")
    m15_hours = {k[:13] for k in (ln[:19] for ln in kept)}            # "YYYY.MM.DD HH"
    h_mask = np.array([ln[:13] not in m15_hours for ln in h_lines])
    h_kept = [ln for ln, m in zip(h_lines, h_mask) if not m]
    (OUT / "xauusd_XAUUSDm_H1_repaired.csv").write_text(h_header + "".join(h_kept))
    for i in np.flatnonzero(h_mask):
        t = pd.Timestamp(pd.to_datetime(h_lines[i][:19], format=FMT), tz="UTC")
        man.append({"timeframe": "H1", "timestamp": h_lines[i][:19], "reason_code": "H1_HOUR_WITHOUT_M15_AFTER_REPAIR",
                    "ny_time": t.tz_convert(NY).strftime("%a %Y-%m-%d %H:%M"), "gap_prev_min": None,
                    "gap_next_min": None, "raw_line": h_lines[i].rstrip("\n")})
    rep["H1"] = {"rows_before": len(h_lines), "rows_removed": int(h_mask.sum()), "rows_after": len(h_kept)}
    pd.DataFrame(man).to_csv(OUT / "removal_manifest.csv", index=False)
    (OUT / "repair_summary.json").write_text(json.dumps(rep, indent=1) + "\n")
    print(json.dumps(rep))
    return rep


def price_signature(f: pd.DataFrame, i: int) -> bool:
    """Validation only: does bar i's high/low/close equal the aggregate of the NEXT session up to 00:00 UTC?"""
    if i + 1 >= len(f):
        return False
    nxt = f["time"].iloc[i + 1]
    s = f[(f["time"] >= nxt) & (f["time"] < nxt.normalize() + pd.Timedelta(days=1))]
    r = f.iloc[i]
    return bool(r.high == s["high"].max() and r.low == s["low"].min() and r.close == s["close"].iloc[-1])


def audit() -> dict:
    import audit_history as ah
    import h1_study as h1
    res, checks = {}, {}
    rep = json.loads((OUT / "repair_summary.json").read_text())
    man = pd.read_csv(OUT / "removal_manifest.csv")
    m15_man = man[man["timeframe"] == "M15"]
    # A1 every removal is a one-bar session inside a known closure
    checks["A1_removals_all_in_known_closures"] = bool((m15_man["reason_code"] != "UNCLASSIFIED").all())
    res["removal_categories"] = man.groupby(["timeframe", "reason_code"]).size().astype(int).to_dict()
    res["removal_categories"] = {" ".join(k): v for k, v in res["removal_categories"].items()}
    # A2 untouched rows byte-identical to raw
    _, raw_lines = read_window("M15")
    rep_lines = (OUT / "xauusd_XAUUSDm_M15_repaired.csv").read_text().splitlines(keepends=True)[1:]
    raw_set = set(raw_lines)
    identical = sum(1 for ln in rep_lines if ln in raw_set)
    removed_set = set(m15_man["raw_line"] + "\n")
    checks["A2_untouched_rows_identical"] = bool(identical == len(rep_lines) == len(raw_lines) - len(m15_man)
                                                 and not (removed_set & set(rep_lines)))
    res["m15_rows"] = {"before": len(raw_lines), "removed": len(m15_man), "after": len(rep_lines),
                       "untouched_identical": identical}
    f = ah.parse(rep_lines)
    h = ah.parse((OUT / "xauusd_XAUUSDm_H1_repaired.csv").read_text().splitlines(keepends=True)[1:])
    # A3 no one-bar sessions, no Saturday-NY bars, no lone bars
    tday = h1.trading_days(f)
    sizes = f.groupby(tday).size()
    ny = f["time"].dt.tz_convert(NY)
    checks["A3_no_one_bar_sessions"] = bool((sizes > 1).all())
    checks["A3_no_saturday_ny_bars"] = bool((ny.dt.weekday != 5).sum() == len(f))
    # A4 integrity
    q, gaps = ah.quality(f, 15, "M15")
    checks["A4_integrity"] = bool(q["monotonic"] and q["duplicates"] == 0 and q["invalid_ohlc"] == 0
                                  and q["misaligned_timestamps"] == 0)
    dec = f["close_s"].str.split(".").str[1].str.len()
    checks["A4_precision_3_decimals"] = bool((dec == 3).all())
    # A5 every gap in the era explained or a preregistered known outage
    gaps["t"] = pd.to_datetime(gaps["prev_bar"])
    era_gaps = gaps[gaps["t"] >= ERA_START]
    known = {pd.Timestamp(a, tz="UTC") for a, _ in KNOWN_OUTAGES}
    unexpl = era_gaps[(era_gaps["kind"] == "UNEXPLAINED") & ~era_gaps["t"].isin(known)]
    checks["A5_all_era_gaps_explained_or_known"] = bool(len(unexpl) == 0)
    res["era_gap_kinds"] = era_gaps["kind"].value_counts().to_dict()
    res["era_unexplained_not_known"] = unexpl[["prev_bar", "next_bar", "gap_min", "close_ny", "reopen_ny"]].to_dict("records")
    res["warmup_gap_kinds"] = gaps[gaps["t"] < ERA_START]["kind"].value_counts().to_dict()
    res["holiday_gaps_era"] = era_gaps[era_gaps["kind"].isin(["holiday/early_close", "weekend+holiday"])][
        ["prev_bar", "next_bar", "gap_min", "close_ny", "reopen_ny"]].to_dict("records")
    res["daily_break_variants_era"] = era_gaps[era_gaps["kind"] == "daily_break_variant"][
        ["prev_bar", "next_bar", "gap_min", "close_ny", "reopen_ny"]].to_dict("records")
    # A6 small sessions must touch a known outage or a holiday/early close
    starts = f.groupby(tday)["time"].first()
    ends = f.groupby(tday)["time"].last()
    small = sizes[(sizes < 8) & (starts >= ERA_START)]
    explained_times = set(known) | set(pd.to_datetime(era_gaps[era_gaps["kind"].isin(
        ["holiday/early_close", "weekend+holiday"])]["prev_bar"]))
    unexplained_small = []
    for d in small.index:
        near = any(abs((x - starts[d]).total_seconds()) < 86400 or abs((x - ends[d]).total_seconds()) < 86400
                   for x in explained_times)
        if not near:
            unexplained_small.append({"start": str(starts[d]), "bars": int(sizes[d])})
    checks["A6_small_sessions_explained"] = bool(not unexplained_small)
    res["small_sessions_era"] = [{"start": str(starts[d]), "bars": int(sizes[d])} for d in small.index]
    # A7 M15/H1 consistency
    al = ah.m15_h1_alignment(f, h)
    checks["A7_m15_h1_consistent"] = bool(al["hours_only_in_m15"] == 0 and al["hours_only_in_h1"] == 0 and
                                          all(al[f"{c}_mismatch"] == 0 for c in ("open", "high", "low", "close", "tick_volume")))
    res["m15_h1_alignment"] = al
    # A8 future-leak validation (price signature, evidence only): no lone bars remain, and no session-opening bar
    # carries the next session's high/low/close
    first_idx = f.groupby(tday).head(1).index
    sig = [int(i) for i in first_idx if price_signature(f, i)]
    checks["A8_no_future_signature_on_session_openers"] = bool(len(sig) == 0)
    res["session_openers_checked"] = len(first_idx)
    res["session_openers_with_signature"] = [str(f["time"].iloc[i]) for i in sig]
    # signature on the removed bars (validation of the rule)
    raw_f = ah.parse(raw_lines)
    rem_idx = raw_f.index[raw_f["timestamp"].isin(set(m15_man["timestamp"]))]
    res["removed_bars_with_future_signature"] = int(sum(price_signature(raw_f, i) for i in rem_idx))
    # A10 frozen H3 implementation hash
    import hashlib
    h3_hash = hashlib.sha256((HERE.parent / "h3" / "h3_study.py").read_bytes()).hexdigest()
    checks["A10_h3_implementation_unchanged"] = h3_hash == "a6c8bb400f83a5af41fa92d63931878098c255f37298203a7aa65238a5262e99"
    # session regime descriptives
    wk = f[(f["time"].diff().dt.total_seconds().div(3600).fillna(99) > 40)]
    res["week_open_ny_by_year"] = {int(y): g["time"].dt.tz_convert(NY).dt.strftime("%a %H:%M").value_counts().to_dict()
                                   for y, g in wk.groupby(wk["time"].dt.year)}
    res["daily_break_pattern_by_year"] = q["daily_break_pattern_by_year"]
    res["by_year"] = {y: {k: v[k] for k in ("m15_bars", "trading_days", "bars_per_day", "price_decimals",
                                            "spread_points", "tick_volume", "real_volume_nonzero",
                                            "intraday_open_jumps_gt_0.5pct")}
                      for y, v in ah.by_year(f).items()}
    res["checks"] = checks
    res["result"] = "PASS" if all(checks.values()) else "UNUSABLE"
    (OUT / "repair_audit.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print(res["result"], json.dumps(checks))
    return res


def count() -> None:
    audit_res = json.loads((OUT / "repair_audit.json").read_text())
    assert audit_res["result"] == "PASS", "event counting is allowed only after a passing repair audit"
    passed = OUT / "causality_tests_passed.txt"                        # A9: written after tests/test_repair.py passes
    assert passed.exists() and "failed" not in passed.read_text(), "causality tests (A9) must pass first"
    import h1_study as h1
    import h3_study as h3
    raw = pd.read_csv(OUT / "xauusd_XAUUSDm_M15_repaired.csv")
    raw["time"] = pd.to_datetime(raw["timestamp"], format=FMT, utc=True)
    f = h3.h3_features(h1.features(raw.drop(columns=["timestamp"]).reset_index(drop=True)))
    events, counts, _ = h3.detect(f)                                   # detection only — forward() never called
    ev = events[events["signal_time"] >= ERA_START]
    by = ev.groupby([ev["signal_time"].dt.year, "direction"]).size().unstack(fill_value=0)
    sessions = f[f["time"] >= ERA_START].groupby("tday").size()
    out = {"events_era": len(ev), "warmup_events_excluded": int(len(events) - len(ev)),
           "sessions_era": int(len(sessions)), "full_sessions_era": int((sessions >= 60).sum()),
           "by_year": {int(y): {k: int(v) for k, v in r.items()} for y, r in by.iterrows()},
           "detection_counts": counts}
    (OUT / "h3_event_count_detection_only.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out))


if __name__ == "__main__":
    {"repair": repair, "audit": audit, "count": count}[sys.argv[1]]()

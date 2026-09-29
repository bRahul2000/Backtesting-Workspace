"""Gold V1 — expanded XAUUSDm history quality / coverage audit (no strategy outcomes).

    venv/bin/python research/gold_v1/history_expansion/audit_history.py

Row groups (by bar timestamp, UTC):
  NEW      < 2025-12-23           never-seen older history: full quality audit
  DEV      2025-12-23 … 2026-06-02 already-studied development rows: full value comparison vs Phase 2A
  SEALED   2026-06-03 … 2026-09-18 validation + final OOS: *line-text equality counts only* — no value is parsed,
                                   no statistic is computed, nothing is printed but match counts
  POST     after Phase 2A's last bar: row count only
Writes audit_results.json next to this file. Reads raw/ and data/exness/gold/phase2a/raw/ only.
"""
from __future__ import annotations

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import Easter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RAW = HERE / "raw"
P2A = ROOT / "data" / "exness" / "gold" / "phase2a" / "raw"
NY = ZoneInfo("America/New_York")
DEV_START, SEALED_START, SEALED_END_DAY = "2025.12.23", "2026.06.03", "2026.09.19"   # string prefixes (YYYY.MM.DD)
FMT = "%Y.%m.%d %H:%M:%S"


def split_lines(path: Path) -> dict[str, list[str]]:
    """Text-level split by the timestamp prefix, before any parsing (so sealed rows are never parsed)."""
    out = {"NEW": [], "DEV": [], "SEALED": [], "POST": []}
    with open(path) as fh:
        header = fh.readline()
        for line in fh:
            day = line[:10]
            if day < DEV_START:
                out["NEW"].append(line)
            elif day < SEALED_START:
                out["DEV"].append(line)
            elif day < SEALED_END_DAY:
                out["SEALED"].append(line)
            else:
                out["POST"].append(line)
    out["header"] = header
    return out


def parse(lines: list[str]) -> pd.DataFrame:
    rows = [ln.rstrip("\n").split(",") for ln in lines]
    f = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"])
    f["time"] = pd.to_datetime(f["timestamp"], format=FMT, utc=True)
    for c in ("open", "high", "low", "close"):
        f[c + "_s"] = f[c]
        f[c] = f[c].astype(float)
    for c in ("tick_volume", "spread", "real_volume"):
        f[c] = f[c].astype(np.int64)
    return f


def holidays(years) -> set:
    cal = USFederalHolidayCalendar().holidays(f"{min(years)}-01-01", f"{max(years)}-12-31")
    good_fridays = [pd.Timestamp(f"{y}-01-01") + Easter() - pd.Timedelta(days=2) for y in years]
    extra = [pd.Timestamp(f"{y}-12-24") for y in years] + [pd.Timestamp(f"{y}-12-31") for y in years]
    thanksgiving_fri = [d + pd.Timedelta(days=1) for d in cal if d.month == 11 and d.day >= 22]
    return {d.date() for d in list(cal) + good_fridays + extra + thanksgiving_fri}


def classify_gaps(f: pd.DataFrame, bar_minutes: int, hol: set) -> pd.DataFrame:
    t = f["time"]
    gap = t.diff().dt.total_seconds().div(60)
    idx = np.flatnonzero(gap.to_numpy() > bar_minutes)
    rows = []
    for i in idx:
        prev_open, nxt = t.iloc[i - 1], t.iloc[i]
        prev_close = prev_open + pd.Timedelta(minutes=bar_minutes)
        pc_ny, nx_ny = prev_close.tz_convert(NY), nxt.tz_convert(NY)
        minutes = (nxt - prev_close).total_seconds() / 60
        span_days = {(prev_close + pd.Timedelta(days=k)).tz_convert(NY).date()
                     for k in range(int((nxt - prev_close).days) + 2)}
        if pc_ny.weekday() == 4 and nx_ny.weekday() == 6 and minutes <= 3 * 1440:
            kind = "weekend"
        elif pc_ny.weekday() == 4 and nx_ny.weekday() in (0, 6) and any(d in hol for d in span_days):
            kind = "weekend+holiday"
        elif (pc_ny.hour, pc_ny.minute) == (17, 0) and nx_ny.hour == 18 and minutes <= 120:
            kind = "daily_break"
        elif any(d in hol for d in span_days) or pc_ny.date() in hol or nx_ny.date() in hol:
            kind = "holiday/early_close"
        elif minutes <= 120 and pc_ny.hour in (16, 17) and nx_ny.hour in (17, 18, 19):
            kind = "daily_break_variant"
        else:
            kind = "UNEXPLAINED"
        rows.append({"prev_bar": str(prev_open), "next_bar": str(nxt), "gap_min": minutes, "kind": kind,
                     "close_ny": pc_ny.strftime("%a %H:%M"), "reopen_ny": nx_ny.strftime("%a %H:%M"),
                     "year": prev_open.year})
    return pd.DataFrame(rows)


def quality(f: pd.DataFrame, bar_minutes: int, name: str) -> dict:
    hol = holidays(range(f["time"].dt.year.min(), f["time"].dt.year.max() + 1))
    r = {"rows": len(f), "first": str(f["time"].iloc[0]), "last": str(f["time"].iloc[-1]),
         "monotonic": bool(f["time"].is_monotonic_increasing), "duplicates": int(f["time"].duplicated().sum()),
         "misaligned_timestamps": int(((f["time"].dt.minute % bar_minutes != 0) | (f["time"].dt.second != 0)).sum())
         if bar_minutes < 60 else int(((f["time"].dt.minute != 0) | (f["time"].dt.second != 0)).sum())}
    bad = (f["high"] < f[["open", "close"]].max(axis=1)) | (f["low"] > f[["open", "close"]].min(axis=1)) | \
          (f["high"] < f["low"]) | (f[["open", "high", "low", "close"]] <= 0).any(axis=1)
    r["invalid_ohlc"] = int(bad.sum())
    gaps = classify_gaps(f, bar_minutes, hol)
    r["gaps_by_kind"] = gaps["kind"].value_counts().to_dict() if len(gaps) else {}
    r["unexplained_gaps"] = gaps[gaps["kind"] == "UNEXPLAINED"].to_dict("records") if len(gaps) else []
    r["holiday_gaps"] = gaps[gaps["kind"].isin(["holiday/early_close", "weekend+holiday"])][
        ["prev_bar", "next_bar", "gap_min", "close_ny", "reopen_ny"]].to_dict("records") if len(gaps) else []
    r["break_variants"] = gaps[gaps["kind"] == "daily_break_variant"].to_dict("records") if len(gaps) else []
    daily = gaps[gaps["kind"] == "daily_break"] if len(gaps) else gaps
    r["daily_break_pattern_by_year"] = {
        int(y): {f"{a}->{b} ({m:.0f}m)": int(n) for (a, b, m), n in
                 g.assign(a=g.close_ny.str[4:], b=g.reopen_ny.str[4:]).groupby(["a", "b", "gap_min"]).size().items()}
        for y, g in daily.groupby("year")} if len(daily) else {}
    return r, gaps


def by_year(m15: pd.DataFrame) -> dict:
    out = {}
    tday = (m15["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    m15 = m15.assign(tday=tday)
    for y, g in m15.groupby(m15["time"].dt.year):
        digits3 = g["close_s"].str.split(".").str[1].str.len()
        last_digit_zero = (g["close_s"].str[-1] == "0").mean()
        per_day = g.groupby("tday").size()
        rng = g["high"] - g["low"]
        jumps = (g["open"] - g["close"].shift()).abs() / g["close"].shift()
        same_session = g["tday"] == g["tday"].shift()
        intraday_jump = jumps[same_session]
        out[int(y)] = {
            "m15_bars": len(g), "trading_days": int(per_day.size),
            "bars_per_day": {int(k): int(v) for k, v in per_day.value_counts().sort_index().items()},
            "price_decimals": {int(k): int(v) for k, v in digits3.value_counts().items()},
            "share_last_digit_zero": round(float(last_digit_zero), 4),
            "close_min": float(g["close"].min()), "close_max": float(g["close"].max()),
            "spread_points": {"zero_share": round(float((g["spread"] == 0).mean()), 4),
                              "min": int(g["spread"].min()), "median": float(g["spread"].median()),
                              "p90": float(g["spread"].quantile(.9)), "max": int(g["spread"].max())},
            "tick_volume": {"median": float(g["tick_volume"].median()), "p10": float(g["tick_volume"].quantile(.1)),
                            "zero_bars": int((g["tick_volume"] == 0).sum())},
            "real_volume_nonzero": int((g["real_volume"] != 0).sum()),
            "median_range": round(float(rng.median()), 3),
            "median_range_pct": round(float((rng / g["close"]).median() * 100), 4),
            "bars_range_gt_10x_median": int((rng > 10 * rng.median()).sum()),
            "intraday_open_jumps_gt_0.5pct": int((intraday_jump > 0.005).sum()),
            "max_intraday_open_jump_pct": round(float(intraday_jump.max() * 100), 3),
            "flat_bars_o_h_l_c_equal": int(((g["high"] == g["low"])).sum()),
            "first_bar_of_week_ny": g.loc[g["time"].diff().dt.total_seconds().div(3600).fillna(99) > 40, "time"]
            .dt.tz_convert(NY).dt.strftime("%a %H:%M").value_counts().head(3).to_dict(),
        }
    return out


def jumps_list(f: pd.DataFrame, top=15) -> list:
    tday = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    j = (f["open"] - f["close"].shift()).abs() / f["close"].shift()
    same = tday == tday.shift()
    cand = f.assign(jump_pct=j * 100, same_session=same)
    cand = cand[cand["jump_pct"] > 0.5].sort_values("jump_pct", ascending=False).head(top)
    return [{"bar": str(r.time), "jump_pct": round(r.jump_pct, 3), "same_session": bool(r.same_session),
             "prev_close": float(f["close"].iloc[i - 1]), "open": r.open} for i, r in zip(cand.index, cand.itertuples())]


def m15_h1_alignment(m15: pd.DataFrame, h1: pd.DataFrame) -> dict:
    agg = m15.set_index("time").groupby(pd.Grouper(freq="1h")).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
        tick_volume=("tick_volume", "sum"), n=("open", "size"))
    agg = agg[agg["n"] > 0]
    h = h1.set_index("time")
    both = agg.join(h[["open", "high", "low", "close", "tick_volume"]], how="outer", lsuffix="_m", rsuffix="_h")
    only_m = both["open_h"].isna().sum()
    only_h = both["open_m"].isna().sum()
    b = both.dropna()
    tol = 5e-4
    res = {"hours_both": len(b), "hours_only_in_m15": int(only_m), "hours_only_in_h1": int(only_h)}
    for c in ("open", "high", "low", "close"):
        res[f"{c}_mismatch"] = int(((b[f"{c}_m"] - b[f"{c}_h"]).abs() > tol).sum())
    res["tick_volume_mismatch"] = int((b["tick_volume_m"] != b["tick_volume_h"]).sum())
    res["partial_hours_m15_lt_4_bars"] = int((b["n"] < 4).sum())
    mism = b[((b["open_m"] - b["open_h"]).abs() > tol) | ((b["close_m"] - b["close_h"]).abs() > tol) |
             ((b["high_m"] - b["high_h"]).abs() > tol) | ((b["low_m"] - b["low_h"]).abs() > tol)]
    res["ohlc_mismatch_examples"] = [str(t) for t in mism.index[:10]]
    return res


def overlap_dev(new_lines: list[str], old_lines: list[str]) -> dict:
    a, b = parse(new_lines), parse(old_lines)
    m = a.merge(b, on="timestamp", how="outer", suffixes=("_new", "_old"), indicator=True)
    both = m[m["_merge"] == "both"]
    r = {"rows_new": len(a), "rows_phase2a": len(b), "timestamps_in_both": len(both),
         "only_in_new": int((m["_merge"] == "left_only").sum()), "only_in_phase2a": int((m["_merge"] == "right_only").sum())}
    for c in ("open_s", "high_s", "low_s", "close_s"):
        r[f"{c[:-2]}_text_equal"] = int((both[f"{c}_new"] == both[f"{c}_old"]).sum())
    for c in ("tick_volume", "spread", "real_volume"):
        d = both[f"{c}_new"] - both[f"{c}_old"]
        r[f"{c}_equal"] = int((d == 0).sum())
        r[f"{c}_diff_examples"] = both.loc[d != 0, ["timestamp", f"{c}_new", f"{c}_old"]].head(5).astype(str).values.tolist()
    r["identical_lines"] = int(len(set(new_lines) & set(old_lines)))
    return r


def overlap_sealed_textonly(new_lines: list[str], old_lines: list[str]) -> dict:
    """Validation/OOS: compare raw text lines only. No parsing, no values, no statistics."""
    sn, so = set(new_lines), set(old_lines)
    ts_new = {ln[:19] for ln in new_lines}
    ts_old = {ln[:19] for ln in old_lines}
    return {"rows_new": len(new_lines), "rows_phase2a": len(old_lines), "identical_lines": len(sn & so),
            "timestamps_in_both": len(ts_new & ts_old), "timestamps_only_new": len(ts_new - ts_old),
            "timestamps_only_phase2a": len(ts_old - ts_new)}


def main() -> None:
    results = {}
    for tf, minutes in (("M15", 15), ("H1", 60)):
        new = split_lines(RAW / f"xauusd_XAUUSDm_{tf}.csv")
        old = split_lines(P2A / f"xauusd_XAUUSDm_{tf}.csv")
        r = {"header_equal": new["header"] == old["header"],
             "row_groups_new_export": {k: len(v) for k, v in new.items() if k != "header"},
             "row_groups_phase2a": {k: len(v) for k, v in old.items() if k != "header"}}
        r["overlap_dev_full"] = overlap_dev(new["DEV"], old["DEV"])
        r["overlap_sealed_text_only"] = overlap_sealed_textonly(new["SEALED"], old["SEALED"])
        audit_rows = parse(new["NEW"] + new["DEV"])          # quality audit: never-seen history + dev overlap
        q, gaps = quality(audit_rows, minutes, tf)
        r["quality_new_plus_dev"] = q
        if tf == "M15":
            r["by_year"] = by_year(audit_rows)
            r["largest_open_jumps"] = jumps_list(audit_rows)
            m15_rows = audit_rows
        else:
            r["m15_h1_alignment"] = m15_h1_alignment(m15_rows, audit_rows)
            r["h1_by_year"] = {int(y): len(g) for y, g in audit_rows.groupby(audit_rows["time"].dt.year)}
        gaps.to_csv(HERE / f"gaps_{tf}.csv", index=False)
        results[tf] = r
    (HERE / "audit_results.json").write_text(json.dumps(results, indent=1, default=str) + "\n")
    print(json.dumps(results, indent=1, default=str)[:200])


if __name__ == "__main__":
    main()

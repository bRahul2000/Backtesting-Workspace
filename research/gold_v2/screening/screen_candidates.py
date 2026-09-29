"""Gold V2 — NON-OUTCOME candidate screening (event frequency, control-pool size, cost scale, power).

    venv/bin/python research/gold_v2/screening/screen_candidates.py

Reads only the V2 development slice (2022-11-27 23:00 → 2025-12-22 21:45 UTC; the committed Gold V1 replication
slice, sha256 a6a503ff…) and the repaired 2017-06 → 2021-08 file for replication-era counts.
It computes NO post-event return, race, MFE/MAE or directional statistic. Allowed quantities: counts of event
occurrences (defined from information up to the event), volatility scale (ATR), spread (indicative), and power.
Sealed samples are never read.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
import math                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402
from zoneinfo import ZoneInfo                                                           # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DEV = ROOT / "research/gold_v1/history_expansion/h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv"
REP = ROOT / "research/gold_v1/history_expansion/repaired/xauusd_XAUUSDm_M15_repaired.csv"
NY, LON = ZoneInfo("America/New_York"), ZoneInfo("Europe/London")
POINT = 0.001


def load(path: Path, start: str | None = None) -> pd.DataFrame:
    f = pd.read_csv(path)
    f["time"] = pd.to_datetime(f["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    if start:
        f = f[f["time"] >= pd.Timestamp(start, tz="UTC")]
    f = f.reset_index(drop=True)
    f["tday"] = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    pc = f["close"].shift()
    tr = np.maximum(f["high"] - f["low"], np.maximum((f["high"] - pc).abs(), (f["low"] - pc).abs()))
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    ny = f["time"].dt.tz_convert(NY)
    lo = f["time"].dt.tz_convert(LON)
    f["ny_min"] = ny.dt.hour * 60 + ny.dt.minute
    f["lon_min"] = lo.dt.hour * 60 + lo.dt.minute
    f["ny_date"] = ny.dt.date
    f["month"] = f["time"].dt.strftime("%Y-%m")
    return f


def mde_prop(n: int, p0: float = 0.5, k: int = 5) -> float:
    """Detectable difference in a proportion (95% two-sided, 80% power) vs k matched controls per event."""
    return 2.8 * math.sqrt(p0 * (1 - p0) * (1 / n + 1 / (k * n))) * 100


def mde_corr(n: int) -> float:
    """Detectable correlation (95% two-sided, 80% power)."""
    return 2.8 / math.sqrt(n)


def c1_round_touches(f: pd.DataFrame, grid: float, offset: float = 0.0) -> pd.DataFrame:
    """First touch per session of each level L = k*grid + offset, from below (prev close < L <= high) or from
    above (prev close > L >= low). Uses only information up to the touching bar. No post-touch data."""
    rows = []
    pc = f["close"].shift().to_numpy()
    hi, lo, tday = f["high"].to_numpy(), f["low"].to_numpy(), f["tday"].to_numpy()
    seen = set()
    for i in range(1, len(f)):
        if tday[i] != tday[i - 1]:
            continue                                     # the session's first bar has no in-session prior close
        a, b = min(pc[i], lo[i]), max(pc[i], hi[i])
        k0, k1 = math.ceil((a - offset) / grid), math.floor((b - offset) / grid)
        for k in range(k0, k1 + 1):
            L = k * grid + offset
            if pc[i] < L <= hi[i]:
                side = "from_below"
            elif pc[i] > L >= lo[i]:
                side = "from_above"
            else:
                continue
            key = (tday[i], round(L, 3), side)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"i": i, "month": f["month"].iat[i], "level": L, "side": side})
    return pd.DataFrame(rows)


def screen(f: pd.DataFrame, label: str) -> dict:
    out = {"label": label, "bars": len(f), "sessions": int(f["tday"].nunique()),
           "first": str(f["time"].iloc[0]), "last": str(f["time"].iloc[-1]),
           "months": int(f["month"].nunique())}
    months = out["months"]
    # C1 round-number first touches ($50 grid, $100 subset) and placebo grids (same geometry, non-round offsets)
    r50 = c1_round_touches(f, 50.0)
    r100 = r50[(r50["level"] % 100) == 0]
    pl_a = c1_round_touches(f, 50.0, 17.30)
    pl_b = c1_round_touches(f, 50.0, 32.70)
    out["C1_round50_first_touches"] = len(r50)
    out["C1_round100_first_touches"] = len(r100)
    out["C1_placebo_touches_offset_17.30"] = len(pl_a)
    out["C1_placebo_touches_offset_32.70"] = len(pl_b)
    out["C1_per_month"] = round(len(r50) / months, 1)
    out["C1_per_year"] = {int(y): int(n) for y, n in r50.groupby(r50["month"].str[:4]).size().items()}
    out["C1_mde_pp_vs_2_placebo_grids"] = round(mde_prop(len(r50), 0.5, k=2), 1)
    # C2 LBMA auctions: days with the M15 bars covering 10:15-10:30 and 14:45-15:00 London (pre-auction windows)
    am = f[f["lon_min"] == 10 * 60 + 15].groupby("ny_date").size()
    pm = f[f["lon_min"] == 14 * 60 + 45].groupby("ny_date").size()
    out["C2_days_with_AM_window"] = int(len(am))
    out["C2_days_with_PM_window"] = int(len(pm))
    out["C2_mde_corr"] = round(mde_corr(len(pm)), 3)
    # C3 intraday momentum (GLD/ETF-session definition): days with 09:30/09:45 and 15:30/15:45 NY bars
    d = f.groupby("ny_date")["ny_min"].apply(set)
    ok3 = d.apply(lambda s: {570, 585, 930, 945} <= s)
    out["C3_valid_days"] = int(ok3.sum())
    out["C3_mde_corr"] = round(mde_corr(int(ok3.sum())), 3)
    # C4 cross-session: trading days with a US window (NY 08:00-16:59) and the following Asia window (00:00-06:59 UTC)
    has_us = f[(f["ny_min"] >= 480) & (f["ny_min"] < 1020)].groupby("tday").size() >= 30
    has_asia = f[f["time"].dt.hour < 7].groupby("tday").size() >= 24
    pairs = sum(1 for t in has_us.index if has_us[t] and has_asia.get(t + 1, False))
    out["C4_us_then_asia_pairs"] = int(pairs)
    out["C4_mde_corr"] = round(mde_corr(pairs), 3)
    # C6 08:30 NY release-time shocks: 08:30 bar range >= 2 x previous-bar ATR (range only, no direction)
    b830 = f.index[f["ny_min"] == 510]
    shocks = [i for i in b830 if i > 0 and (f["high"].iat[i] - f["low"].iat[i]) >= 2 * f["atr"].iat[i - 1]]
    out["C6_0830_shocks"] = len(shocks)
    out["C6_per_month"] = round(len(shocks) / months, 1)
    # placebo pool: same-size shocks at other NY minutes on weekdays 09:00-15:00
    big = (f["high"] - f["low"]) >= 2 * f["atr"].shift()
    out["C6_placebo_pool_same_size_0900_1500"] = int((big & (f["ny_min"] >= 540) & (f["ny_min"] <= 900)).sum())
    # C7 weekly reopen gaps >= 0.5 ATR (magnitude only)
    wk = f.index[f["time"].diff().dt.total_seconds().div(3600).fillna(0) > 40]
    gaps = [i for i in wk if abs(f["open"].iat[i] - f["close"].iat[i - 1]) >= 0.5 * f["atr"].iat[i - 1]]
    out["C7_week_opens"] = len(wk)
    out["C7_gaps_ge_0.5atr"] = len(gaps)
    # cost scale (indicative; spread semantics unresolved)
    by_year = {}
    for y, g in f.groupby(f["time"].dt.year):
        sp = g["spread"] * POINT
        by_year[int(y)] = {"median_spread_usd": float(sp.median()), "spread_zero_share": float((g["spread"] == 0).mean()),
                           "median_atr_usd": round(float(g["atr"].median()), 3),
                           "spread_over_atr_pct": round(float(sp.median() / g["atr"].median() * 100), 2),
                           "median_close": round(float(g["close"].median()), 1)}
    out["cost_scale_by_year"] = by_year
    return out


def main() -> None:
    dev = screen(load(DEV, "2023-01-01"), "V2 development candidate 2023-01-01 → 2025-12-22")
    rep = screen(load(REP, "2017-06-01"), "V2 replication candidate (repaired) 2017-06-01 → 2021-08-31")
    res = {"dev": dev, "rep": rep}
    (HERE / "screening_results.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    for k in ("dev", "rep"):
        r = res[k]
        print(r["label"], "| sessions", r["sessions"])
        print("  C1 $50 first touches", r["C1_round50_first_touches"], "($100:", r["C1_round100_first_touches"], ") placebo",
              r["C1_placebo_touches_offset_17.30"], r["C1_placebo_touches_offset_32.70"], "| /month", r["C1_per_month"],
              "| MDE pp", r["C1_mde_pp_vs_2_placebo_grids"], "| by year", r["C1_per_year"])
        print("  C2 AM/PM days", r["C2_days_with_AM_window"], r["C2_days_with_PM_window"], "MDE corr", r["C2_mde_corr"])
        print("  C3 days", r["C3_valid_days"], "MDE corr", r["C3_mde_corr"], "| C4 pairs", r["C4_us_then_asia_pairs"], "MDE corr", r["C4_mde_corr"])
        print("  C6 08:30 shocks", r["C6_0830_shocks"], "/month", r["C6_per_month"], "placebo pool", r["C6_placebo_pool_same_size_0900_1500"])
        print("  C7 week opens", r["C7_week_opens"], "gaps>=0.5ATR", r["C7_gaps_ge_0.5atr"])
        print("  cost", r["cost_scale_by_year"])


if __name__ == "__main__":
    main()

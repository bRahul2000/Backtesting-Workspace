"""Gold V2 — C4 US → next-Asia session momentum (implements C4_PREREGISTRATION.md exactly).

    venv/bin/python research/gold_v2/c4_session_momentum/c4_study.py dev [--dry]
    venv/bin/python research/gold_v2/c4_session_momentum/c4_study.py rep [--dry] [--threshold X]

--dry prints pair COUNTS only (no Asia return, no statistic). Sealed samples are never read.
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
ROOT = HERE.parents[2]
DATA = {
    "dev": (ROOT / "research/gold_v1/history_expansion/h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv",
            "2023-01-01", "2025-12-22 23:00"),
    "rep": (ROOT / "research/gold_v1/history_expansion/repaired/xauusd_XAUUSDm_M15_repaired.csv",
            "2017-06-01", "2021-08-31 22:00"),
}
NY = ZoneInfo("America/New_York")
US_FIRST, US_LAST = 8 * 60, 16 * 60 + 45          # NY local bar-start minutes (window 08:00 → 17:00 NY)
US_MIN_BARS, ASIA_MIN_BARS = 30, 24               # of 36 / 28 possible
MIN_SHIFT_DAYS = 5                                # circular shifts of at least one trading week
BOOT, SEED = 5000, 20260929
COST_MULTIPLE = 2.0
POINT = 0.001


def load(which: str):
    path, start, end = DATA[which]
    f = pd.read_csv(path)
    f["time"] = pd.to_datetime(f["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    assert f["time"].max() < t1, "data beyond the preregistered end"
    f["tday"] = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    pc = f["close"].shift()
    tr = np.maximum(f["high"] - f["low"], np.maximum((f["high"] - pc).abs(), (f["low"] - pc).abs()))
    tr.iloc[0] = f["high"].iloc[0] - f["low"].iloc[0]
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    ny = f["time"].dt.tz_convert(NY)
    f["ny_min"] = ny.dt.hour * 60 + ny.dt.minute
    f["utc_hour"] = f["time"].dt.hour
    return f, t0, t1


def pairs(f: pd.DataFrame, t0, t1) -> pd.DataFrame:
    """One row per trading session D with a complete US window, paired with session D+1's Asia window."""
    rows = []
    groups = {k: g for k, g in f.groupby("tday")}
    for d, g in groups.items():
        us = g[(g["ny_min"] >= US_FIRST) & (g["ny_min"] <= US_LAST)]
        nxt = groups.get(d + 1)
        if nxt is None or len(us) < US_MIN_BARS:
            continue
        if us["ny_min"].iloc[0] != US_FIRST or us["ny_min"].iloc[-1] != US_LAST:
            continue
        asia = nxt[nxt["utc_hour"] < 7]
        if len(asia) < ASIA_MIN_BARS:
            continue
        first, last = asia.iloc[0], asia.iloc[-1]
        if not (first["time"].hour == 0 and first["time"].minute == 0 and last["time"].hour == 6
                and last["time"].minute == 45):
            continue
        us_start = us["time"].iloc[0]
        if not (t0 <= us_start and last["time"] < t1):
            continue
        r_us = float(us["close"].iloc[-1] - us["open"].iloc[0])
        i_entry = int(first.name)
        rows.append({"us_date": us_start.tz_convert(NY).strftime("%Y-%m-%d"), "us_start": us_start,
                     "asia_entry": first["time"], "asia_exit_bar": last["time"], "r_us": r_us,
                     "entry_index": i_entry, "atr_entry": float(f["atr"].iat[i_entry - 1]),
                     "spread_entry_usd": float(f["spread"].iat[i_entry] * POINT),
                     "weekend_gap": bool((first["time"] - us["time"].iloc[-1]).total_seconds() > 40 * 3600),
                     "_asia_open": float(first["open"]), "_asia_close": float(last["close"])})
    p = pd.DataFrame(rows)
    p = p[p["r_us"] != 0].reset_index(drop=True)                 # zero US return excluded
    return p


def effect(s: np.ndarray, y: np.ndarray) -> float:
    """Predictive component: E[s*y] - E[s]E[y] (sample covariance with 1/n)."""
    return float(np.mean(s * y) - np.mean(s) * np.mean(y))


def stats(p: pd.DataFrame, threshold: float | None) -> dict:
    s = np.sign(p["r_us"].to_numpy())
    y = (p["y_atr"]).to_numpy()
    n = len(p)
    obs = effect(s, y)
    shifts = [k for k in range(MIN_SHIFT_DAYS, n - MIN_SHIFT_DAYS + 1)]
    null = np.array([effect(np.roll(s, k), y) for k in shifts])
    p_one = float((1 + np.sum(null >= obs)) / (1 + len(null)))
    # week-block bootstrap CI of the effect
    wk = p["us_start"].dt.tz_convert(NY).dt.strftime("%G-%V").to_numpy()
    uw = np.unique(wk)
    idx_by_week = {w: np.flatnonzero(wk == w) for w in uw}
    rng = np.random.default_rng(SEED)
    boots = np.empty(BOOT)
    for b in range(BOOT):
        pick = np.concatenate([idx_by_week[w] for w in rng.choice(uw, len(uw), replace=True)])
        boots[b] = effect(s[pick], y[pick])
    long_c = float(y[s > 0].mean() - y.mean())
    short_c = float(y.mean() - y[s < 0].mean())
    return {"n_pairs": n, "effect_atr": obs, "p_one_sided_circular_shift": p_one, "n_shifts": len(shifts),
            "null_mean": float(null.mean()), "ci_lo": float(np.percentile(boots, 2.5)), "ci_hi": float(np.percentile(boots, 97.5)),
            "mean_s_times_y": float(np.mean(s * y)), "mean_y": float(y.mean()), "share_s_pos": float((s > 0).mean()),
            "long_contribution": long_c, "short_contribution": short_c, "corr_s_y": float(np.corrcoef(s, y)[0, 1]),
            "threshold_atr": threshold}


def main(which: str, dry: bool, threshold_arg: float | None) -> None:
    f, t0, t1 = load(which)
    p = pairs(f, t0, t1)
    if dry:
        print(which, "pairs", len(p), "| first US date", p["us_date"].iloc[0], "last", p["us_date"].iloc[-1],
              "| weekend pairs", int(p["weekend_gap"].sum()))
        return
    p["y_atr"] = (p["_asia_close"] - p["_asia_open"]) / p["atr_entry"]
    p["cost_atr"] = p["spread_entry_usd"] / p["atr_entry"]
    p["s"] = np.sign(p["r_us"])
    out_dir = HERE / which
    out_dir.mkdir(exist_ok=True)
    p.drop(columns=["_asia_open", "_asia_close"]).assign(asia_open=p["_asia_open"], asia_close=p["_asia_close"]) \
        .to_csv(out_dir / "pairs.csv", index=False)
    if threshold_arg is not None:
        threshold = threshold_arg
    else:
        threshold = COST_MULTIPLE * float(p["cost_atr"].median())      # frozen formula; non-outcome input
    res = {"which": which, "primary": stats(p, threshold)}
    years = sorted(p["us_start"].dt.year.unique())
    res["by_year"] = {int(y): stats(p[p["us_start"].dt.year == y].reset_index(drop=True), threshold) for y in years}
    res["leave_one_year_out"] = {int(y): stats(p[p["us_start"].dt.year != y].reset_index(drop=True), threshold)
                                 for y in years}
    res["secondary_excluding_weekend_pairs"] = stats(p[~p["weekend_gap"]].reset_index(drop=True), threshold)
    res["cost"] = {"median_cost_atr": float(p["cost_atr"].median()), "spread_zero_share": float((p["spread_entry_usd"] == 0).mean())}
    (out_dir / "result.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    pr = res["primary"]
    print(json.dumps({k: pr[k] for k in ("n_pairs", "effect_atr", "p_one_sided_circular_shift", "ci_lo", "ci_hi",
                                         "long_contribution", "short_contribution", "corr_s_y", "threshold_atr")},
                     default=float),
          {y: round(v["effect_atr"], 3) for y, v in res["leave_one_year_out"].items()})


if __name__ == "__main__":
    thr = None
    if "--threshold" in sys.argv:
        thr = float(sys.argv[sys.argv.index("--threshold") + 1])
    main(sys.argv[1], "--dry" in sys.argv, thr)

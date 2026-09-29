"""Gold V2 C — Gold-vs-USD residual reversal (DXYm primary; USDJPYm secondary, non-decisional).

    venv/bin/python research/gold_v2/c_usd_residual/c_study.py dev [--dry] [--proxy USDJPYm]
    venv/bin/python research/gold_v2/c_usd_residual/c_study.py rep --threshold X [--proxy USDJPYm]

Implements C_PREREGISTRATION.md. All state (beta, residual sd, gold sd, vol regime) is computed from bars strictly
before t. --dry prints event/control-pool counts and the pre-outcome cost scale only.
"""
from __future__ import annotations

import glob
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
V2 = HERE.parent
sys.path.insert(0, str(V2 / "data"))
import v2_data as vd                                                                     # noqa: E402

R = V2 / "data/raw"
PERIODS = {  # (load start incl. warm-up, event start, event end exclusive, load end exclusive)
    "dev": ("2022.11.27 23:00:00", "2023-01-01", "2025-01-01", "2025.01.01 06:00:00"),
    "rep": ("2024.10.01 00:00:00", "2025-01-01", "2026-06-02 20:00", "2026.06.03 00:00:00"),
}
W = 480                     # rolling window: 480 valid M15 returns ≈ 20 sessions
Z_THR = 2.5
H = 8                       # horizon: 8 M15 bars = 2 h
CTRL_Z = 1.0
SIZE_TOL, SIZE_TOL_RELAXED = 0.15, 0.30
K_CTRL = 5
BOOT, SEED = 5000, 20261001
POINT = 0.001


def m15(sym: str, a: str, b: str) -> pd.DataFrame:
    f = vd.load_bars(sorted(glob.glob(str(R / f"v2_m1_{sym}_*.csv"))), a, b)
    agg = vd.aggregate(f, 15)
    last_spread = f.set_index("time")["spread"].groupby(pd.Grouper(freq="15min")).last()
    agg["spread"] = last_spread.reindex(agg.index)
    return agg


def build(which: str, proxy: str) -> pd.DataFrame:
    a, _, _, b = PERIODS[which]
    x, u = m15("XAUUSDm", a, b), m15(proxy, a, b)
    df = x[["open", "close", "spread"]].join(u[["close"]].rename(columns={"close": "u_close"}), how="inner")
    t = df.index.to_series()
    consec = t.diff() == pd.Timedelta(minutes=15)                  # same-session consecutive common bars only
    df["g"] = np.where(consec, np.log(df["close"]).diff(), np.nan)
    df["u"] = np.where(consec, np.log(df["u_close"]).diff(), np.nan)
    valid = df["g"].notna() & df["u"].notna()
    v = df[valid]
    # rolling state from the previous W valid returns (shift(1) => strictly before t)
    mg, mu = v["g"].rolling(W).mean().shift(), v["u"].rolling(W).mean().shift()
    cov = (v["g"] * v["u"]).rolling(W).mean().shift() - mg * mu
    var_u = v["u"].rolling(W).var(ddof=0).shift()
    beta = cov / var_u
    alpha = mg - beta * mu
    e = v["g"] - (alpha + beta * v["u"])
    # residual sd from previous W residuals, each residual computed with its own causal beta
    sd_e = e.rolling(W).std().shift()
    sd_g = v["g"].rolling(W).std().shift()
    vol_med = sd_g.rolling(W * 5).median().shift()
    df.loc[v.index, "beta"] = beta
    df.loc[v.index, "e"] = e
    df.loc[v.index, "z"] = e / sd_e
    df.loc[v.index, "sd_g"] = sd_g
    df.loc[v.index, "vol_regime"] = np.select([sd_g > 1.25 * vol_med, sd_g < 0.8 * vol_med], ["high", "low"], "mid")
    df.loc[vol_med.isna().reindex(df.index, fill_value=True).to_numpy() & valid.to_numpy(), "vol_regime"] = "na"
    hour = df.index.hour
    df["tod"] = np.select([hour < 7, hour < 12, hour < 17], ["asia", "london", "ny_overlap"], "late")
    df["pos"] = np.arange(len(df))
    # outcome window: entry at next bar open, exit at close of bar t+H; all H bars consecutive (same session)
    tt = df.index
    idx = np.arange(len(df))
    ends = idx + H
    inb = ends < len(df)
    same = np.zeros(len(df), dtype=bool)
    same[inb] = (tt[ends[inb]] - tt[idx[inb]]) == pd.Timedelta(minutes=15 * H)
    df["fwd_ok"] = same
    return df


def outcome(df: pd.DataFrame, pos: int, direction: float) -> float:
    entry = df["open"].iat[pos + 1]
    exitp = df["close"].iat[pos + H]
    return float(direction * math.log(exitp / entry) / df["sd_g"].iat[pos])


def select(df: pd.DataFrame, which: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    _, s, e, _ = PERIODS[which]
    t0, t1 = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
    base = df[(df.index >= t0) & (df.index < t1) & df["z"].notna() & df["sd_g"].notna() & df["fwd_ok"]
              & (df["vol_regime"] != "na")]
    cand = base[(base["z"].abs() >= Z_THR) & (np.sign(base["e"]) == np.sign(base["g"])) & (base["g"] != 0)]
    ev, last = [], -10 ** 9
    for t, r in cand.iterrows():                                          # spacing: one event per H bars
        if r["pos"] - last >= H:
            ev.append(t)
            last = r["pos"]
    events = base.loc[ev].copy()
    near = np.zeros(len(df), dtype=bool)
    for p in events["pos"]:
        near[max(0, int(p) - H): int(p) + H + 1] = True
    pool = base[(base["z"].abs() < CTRL_Z) & (base["g"] != 0) & ~near[base["pos"].to_numpy().astype(int)]].copy()
    return events, pool


def controls(df, events, pool):
    rng = np.random.default_rng(SEED)
    pool = pool.assign(size=(pool["g"].abs() / pool["sd_g"]), sgn=np.sign(pool["g"]))
    rows, relaxed = [], 0
    for t, r in events.iterrows():
        size = abs(r["g"]) / r["sd_g"]
        m = pool[(pool["sgn"] == np.sign(r["g"])) & (pool["tod"] == r["tod"]) & (pool["vol_regime"] == r["vol_regime"])]
        c = m[(m["size"] - size).abs() <= SIZE_TOL * size]
        if len(c) < K_CTRL:
            c = m[(m["size"] - size).abs() <= SIZE_TOL_RELAXED * size]
            relaxed += 1
        if len(c) == 0:
            continue
        pick = rng.choice(c["pos"].to_numpy().astype(int), size=K_CTRL, replace=len(c) < K_CTRL)
        for p in pick:
            rows.append({"event_time": t, "ctrl_pos": int(p), "y": outcome(df, int(p), -np.sign(r["g"]))})
    return pd.DataFrame(rows), relaxed


def paired_stats(ev: pd.DataFrame, ctrl: pd.DataFrame) -> dict:
    cm = ctrl.groupby("event_time")["y"].mean()
    e = ev.loc[ev.index.isin(cm.index)]
    d = e["y"] - cm.reindex(e.index)
    day = pd.Series(e.index.strftime("%Y-%m-%d"), index=e.index)      # amendment C-1: string day keys
    days = np.array(sorted(day.unique()))
    by_day = d.groupby(day.values)
    s_sum, s_n = by_day.sum(), by_day.size()
    rng = np.random.default_rng(SEED)
    boots = np.empty(BOOT)
    ss, nn = s_sum.reindex(days).to_numpy(), s_n.reindex(days).to_numpy()
    for b in range(BOOT):
        k = rng.integers(0, len(days), len(days))
        boots[b] = ss[k].sum() / nn[k].sum()
    delta = float(d.mean())
    se = float(boots.std(ddof=1))
    p = float(1 - 0.5 * (1 + math.erf((delta / se) / math.sqrt(2)))) if se > 0 else float("nan")
    return {"n_events": int(len(d)), "delta_sigma": delta, "mean_y_event": float(e["y"].mean()),
            "mean_y_control": float(cm.reindex(e.index).mean()), "se": se, "ci_lo": float(np.percentile(boots, 2.5)),
            "ci_hi": float(np.percentile(boots, 97.5)), "p_one_sided": p}


def main(which: str, proxy: str, dry: bool, thr_arg: float | None) -> None:
    df = build(which, proxy)
    events, pool = select(df, which)
    cost_sigma = (events["spread"] * POINT) / (events["open"] * events["sd_g"])
    threshold = thr_arg if thr_arg is not None else float(2 * cost_sigma.median())
    info = {"proxy": proxy, "period": which, "events": len(events), "control_pool": len(pool),
            "events_up": int((events["g"] > 0).sum()), "events_down": int((events["g"] < 0).sum()),
            "median_cost_sigma_units": float(cost_sigma.median()), "threshold_sigma": threshold,
            "median_beta": float(df["beta"].median()), "events_by_year": events.index.year.value_counts().sort_index().to_dict()}
    if dry:
        print(json.dumps(info, default=float))
        return
    events = events.assign(y=[outcome(df, int(p), -np.sign(g)) for p, g in zip(events["pos"], events["g"])])
    ctrl, relaxed = controls(df, events, pool)
    tag = which if proxy == "DXYm" else f"{which}_{proxy}_secondary"
    out = HERE / tag
    out.mkdir(exist_ok=True)
    events.drop(columns=["u_close"]).to_csv(out / "events.csv")
    ctrl.to_csv(out / "controls.csv", index=False)
    res = {"info": info, "controls_relaxed_events": relaxed, "primary": paired_stats(events, ctrl),
           "up_moves": paired_stats(events[events["g"] > 0], ctrl),
           "down_moves": paired_stats(events[events["g"] < 0], ctrl),
           "by_year": {int(y): paired_stats(events[events.index.year == y], ctrl) for y in sorted(set(events.index.year))},
           "leave_one_year_out": {int(y): paired_stats(events[events.index.year != y], ctrl)
                                  for y in sorted(set(events.index.year))}}
    (out / "result.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    p = res["primary"]
    print(json.dumps({k: p[k] for k in ("n_events", "delta_sigma", "mean_y_event", "mean_y_control", "ci_lo", "ci_hi", "p_one_sided")},
                     default=float), "threshold", round(threshold, 4), "up", round(res["up_moves"]["delta_sigma"], 3),
          "down", round(res["down_moves"]["delta_sigma"], 3), {y: round(v["delta_sigma"], 3) for y, v in res["leave_one_year_out"].items()})


if __name__ == "__main__":
    proxy = sys.argv[sys.argv.index("--proxy") + 1] if "--proxy" in sys.argv else "DXYm"
    thr = float(sys.argv[sys.argv.index("--threshold") + 1]) if "--threshold" in sys.argv else None
    main(sys.argv[1], proxy, "--dry" in sys.argv, thr)

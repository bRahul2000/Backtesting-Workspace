"""Gold V2 A — round-number continuation (RESULT-GENERATED hypothesis; first independent test on repaired 2017–2021 M1).

    venv/bin/python research/gold_v2/a_round_continuation/a_study.py [--dry]

Implements A_PREREGISTRATION.md. --dry prints event counts and the pre-outcome cost scale only.
"""
from __future__ import annotations

import hashlib
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

DATA = V2 / "data/derived/xauusd_m1_2017_2021_repaired.csv"
EXPECTED_SHA = json.loads((HERE / "m1_repair_summary.json").read_text())["repaired_sha256"]
T0, T1 = pd.Timestamp("2017-06-01", tz="UTC"), pd.Timestamp("2021-08-31 22:00", tz="UTC")
GRID = 50.0
PLACEBO = (17.30, 32.70)
HORIZON_M1 = 480                                    # 8 hours, the C1 horizon (32 M15 bars)
BOOT, SEED = 5000, 20261001
PRACTICAL_PP = 5.0
TICK_SPREAD_2026 = 0.264                            # median XAUUSDm spread in the 2026-02 tick sample (scenario only)


def load() -> pd.DataFrame:
    assert hashlib.sha256(DATA.read_bytes()).hexdigest() == EXPECTED_SHA, "repaired M1 hash mismatch"
    f = vd.load_bars([DATA], "2017.05.01 00:00:00", "2021.08.31 22:00:00")
    f["tday"] = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()
    m15 = vd.aggregate(f, 15)
    pc = m15["close"].shift()
    tr = np.maximum(m15["high"] - m15["low"], np.maximum((m15["high"] - pc).abs(), (m15["low"] - pc).abs()))
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    # d for a minute = ATR of the last COMPLETED M15 bar strictly before that minute's M15 bucket
    bucket = f["time"].dt.floor("15min")
    a = pd.DataFrame({"bstart": atr.index + pd.Timedelta(minutes=15), "atr_prev": atr.to_numpy()})
    left = pd.DataFrame({"bucket": bucket, "k": np.arange(len(f))})
    m = pd.merge_asof(left.sort_values("bucket"), a.sort_values("bstart"), left_on="bucket", right_on="bstart",
                      direction="backward").sort_values("k")
    f["d"] = m["atr_prev"].to_numpy()
    return f


def events(f: pd.DataFrame, offsets, label: str) -> pd.DataFrame:
    pc = f["close"].shift().to_numpy()
    hi, lo, tday, tm, d = f["high"].to_numpy(), f["low"].to_numpy(), f["tday"].to_numpy(), f["time"], f["d"].to_numpy()
    seen, rows = set(), []
    for i in range(1, len(f)):
        if tday[i] != tday[i - 1] or not (T0 <= tm.iat[i] < T1) or not d[i] > 0:
            continue
        a_, b_ = min(pc[i], lo[i]), max(pc[i], hi[i])
        for o in offsets:
            for k in range(math.ceil((a_ - o) / GRID), math.floor((b_ - o) / GRID) + 1):
                L = round(k * GRID + o, 3)
                if pc[i] > L >= lo[i]:
                    side = -1                      # approach from ABOVE (primary)
                elif pc[i] < L <= hi[i]:
                    side = 1                       # approach from below (non-decisional robustness only)
                else:
                    continue
                key = (tday[i], L, side)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"group": label, "i": i, "time": tm.iat[i], "tday": int(tday[i]), "level": L, "offset": o,
                             "side": side, "d": float(d[i])})
    return pd.DataFrame(rows)


def race(f: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """continuation target = L + side*d (through the level); reversal target = L - side*d.
    Touch bar: reversal-target hit -> ambiguous (extreme may precede the touch); continuation-only -> continuation."""
    hi, lo, tday = f["high"].to_numpy(), f["low"].to_numpy(), f["tday"].to_numpy()
    out = []
    for e in ev.itertuples():
        L, s, d, i = e.level, e.side, e.d, e.i
        cont, rev = L + s * d, L - s * d
        hit_c = (hi[i] >= cont) if s == 1 else (lo[i] <= cont)
        hit_r = (lo[i] <= rev) if s == 1 else (hi[i] >= rev)
        if hit_r:
            res = "ambiguous"
        elif hit_c:
            res = "continuation"
        else:
            res = "unresolved"
            j1 = min(len(f), i + 1 + HORIZON_M1)
            for j in range(i + 1, j1):
                if tday[j] != tday[i]:
                    break
                c = (hi[j] >= cont) if s == 1 else (lo[j] <= cont)
                r = (lo[j] <= rev) if s == 1 else (hi[j] >= rev)
                if c and r:
                    res = "ambiguous"
                    break
                if c:
                    res = "continuation"
                    break
                if r:
                    res = "reversal"
                    break
        out.append(res)
    ev = ev.copy()
    ev["result"] = out
    return ev


def p_cont(df):
    c = (df["result"] == "continuation").sum()
    n = df["result"].isin(["continuation", "reversal"]).sum()
    return (c / n if n else np.nan), int(n)


def delta(rd: pd.DataFrame, pl: pd.DataFrame) -> dict:
    pr, nr = p_cont(rd)
    pp, npl = p_cont(pl)
    dlt = (pr - pp) * 100
    days = np.array(sorted(set(rd["tday"]) | set(pl["tday"])))

    def agg(df):
        g = df[df["result"].isin(["continuation", "reversal"])].groupby("tday")["result"]
        return (g.apply(lambda x: (x == "continuation").sum()).reindex(days, fill_value=0).to_numpy(),
                g.size().reindex(days, fill_value=0).to_numpy())
    rc, rn = agg(rd)
    qc, qn = agg(pl)
    rng = np.random.default_rng(SEED)
    boots = np.empty(BOOT)
    for b in range(BOOT):
        idx = rng.integers(0, len(days), len(days))
        boots[b] = (rc[idx].sum() / rn[idx].sum() - qc[idx].sum() / qn[idx].sum()) * 100
    se = float(boots.std(ddof=1))
    p = float(1 - 0.5 * (1 + math.erf((dlt / se) / math.sqrt(2)))) if se > 0 else float("nan")
    return {"p_cont_round": pr, "n_round": nr, "p_cont_placebo": pp, "n_placebo": npl, "delta_pp": dlt, "se_pp": se,
            "ci_lo_pp": float(np.percentile(boots, 2.5)), "ci_hi_pp": float(np.percentile(boots, 97.5)), "p_one_sided": p}


def main(dry: bool) -> None:
    f = load()
    rd = events(f, (0.0,), "round")
    pl = events(f, PLACEBO, "placebo")
    ra, pa = rd[rd.side == -1], pl[pl.side == -1]
    cost = {"median_d": float(ra["d"].median()), "median_spread_over_d_2026_tick_scenario": float((TICK_SPREAD_2026 / ra["d"]).median()),
            "breakeven_p_cont_1to1_scenario": float(0.5 + (TICK_SPREAD_2026 / ra["d"]).median() / 2)}
    if dry:
        print("round from-above", len(ra), "| placebo from-above", len(pa), "| round from-below", int((rd.side == 1).sum()),
              "| placebo from-below", int((pl.side == 1).sum()), "| cost", {k: round(v, 4) for k, v in cost.items()})
        return
    out = HERE / "first_test"
    out.mkdir(exist_ok=True)
    rd, pl = race(f, rd), race(f, pl)
    ev = pd.concat([rd, pl], ignore_index=True)
    ev["year"] = ev["time"].dt.year
    ev.to_csv(out / "events.csv", index=False)
    ra, pa = rd[rd.side == -1], pl[pl.side == -1]
    res = {"primary_from_above": delta(ra, pa), "cost_scenario": cost,
           "result_counts_from_above": {g: d_[d_.side == -1]["result"].value_counts().to_dict() for g, d_ in (("round", rd), ("placebo", pl))},
           "by_year": {int(y): delta(ra[ra.time.dt.year == y], pa[pa.time.dt.year == y]) for y in sorted(ra.time.dt.year.unique())},
           "leave_one_year_out": {int(y): delta(ra[ra.time.dt.year != y], pa[pa.time.dt.year != y]) for y in sorted(ra.time.dt.year.unique())},
           "robustness_nondecisional": {
               "both_sides_pooled_continuation": delta(rd, pl),
               "from_below_continuation": delta(rd[rd.side == 1], pl[pl.side == 1]),
               "placebo_17.30_only": delta(ra, pa[pa.offset == 17.30]),
               "placebo_32.70_only": delta(ra, pa[pa.offset == 32.70]),
               "round_100_only": delta(ra[(ra.level % 100) == 0], pa),
               "conservative_ambiguous_as_reversal": delta(ra.assign(result=ra.result.replace("ambiguous", "reversal")),
                                                           pa.assign(result=pa.result.replace("ambiguous", "reversal")))}}
    (out / "result.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    pr = res["primary_from_above"]
    print(json.dumps({k: pr[k] for k in ("p_cont_round", "n_round", "p_cont_placebo", "n_placebo", "delta_pp", "ci_lo_pp",
                                         "ci_hi_pp", "p_one_sided")}, default=float),
          {y: round(v["delta_pp"], 1) for y, v in res["leave_one_year_out"].items()})


if __name__ == "__main__":
    main("--dry" in sys.argv)

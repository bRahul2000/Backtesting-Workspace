"""Gold V2 — C1 round-number barrier reaction (implements C1_PREREGISTRATION.md exactly).

    venv/bin/python research/gold_v2/c1_round_number/c1_study.py dev   [--dry]
    venv/bin/python research/gold_v2/c1_round_number/c1_study.py rep   [--dry]

--dry prints event COUNTS only (no race, no outcome). Data are read by timestamp text slice; sealed samples are
never read (dev slice ends 2025-12-22 21:45; repaired file ends 2021-08-31 20:45).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
import math                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

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
GRID = 50.0
PLACEBO_PRIMARY = (17.30, 32.70)          # one construction: levels $17.30 either side of every round level
PLACEBO_SECONDARY = {"offset_17.30_only": (17.30,), "offset_32.70_only": (32.70,)}
MAX_BARS = 32
BOOT, SEED = 5000, 20260929
PRACTICAL_PP = 5.0
POINT = 0.001


def load(which: str) -> tuple[pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    path, start, end = DATA[which]
    f = pd.read_csv(path)
    f["time"] = pd.to_datetime(f["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    t0, t1 = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    assert f["time"].max() < t1, "data beyond the preregistered end"
    f = f.reset_index(drop=True)
    f["tday"] = (f["time"].diff().dt.total_seconds().div(60).fillna(1e9) >= 60).cumsum()   # frozen session rule
    pc = f["close"].shift()
    tr = np.maximum(f["high"] - f["low"], np.maximum((f["high"] - pc).abs(), (f["low"] - pc).abs()))
    tr.iloc[0] = f["high"].iloc[0] - f["low"].iloc[0]
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()                                 # Wilder ATR(14)
    return f, t0, t1


def events(f: pd.DataFrame, offsets: tuple[float, ...], t0, t1, label: str) -> pd.DataFrame:
    """First touch per (session, level, approach side). Level set = {k*GRID + o : o in offsets}."""
    pc = f["close"].shift().to_numpy()
    hi, lo, tday, tm = f["high"].to_numpy(), f["low"].to_numpy(), f["tday"].to_numpy(), f["time"]
    seen, rows = set(), []
    for i in range(1, len(f)):
        if tday[i] != tday[i - 1] or not (t0 <= tm.iat[i] < t1):
            continue
        a, b = min(pc[i], lo[i]), max(pc[i], hi[i])
        for o in offsets:
            for k in range(math.ceil((a - o) / GRID), math.floor((b - o) / GRID) + 1):
                L = round(k * GRID + o, 3)
                if pc[i] < L <= hi[i]:
                    side = 1                    # approach from below
                elif pc[i] > L >= lo[i]:
                    side = -1                   # approach from above
                else:
                    continue
                key = (tday[i], L, side)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"group": label, "i": i, "time": tm.iat[i], "tday": int(tday[i]), "level": L,
                             "offset": o, "side": side, "d": float(f["atr"].iat[i - 1])})
    return pd.DataFrame(rows)


def race(f: pd.DataFrame, ev: pd.DataFrame) -> pd.DataFrame:
    """Anchored symmetric race from level L with half-width d = ATR[t-1].
    reversal target = L - side*d ; continuation target = L + side*d.
    Touch bar: continuation-only hit -> 'continuation' (unambiguous: price had to cross L);
               any reversal-target hit in the touch bar -> 'ambiguous' (the extreme may precede the touch).
    Later bars (same session, <= MAX_BARS): both targets in one bar -> 'ambiguous'; first hit decides;
    none -> 'unresolved'."""
    hi, lo, tday = f["high"].to_numpy(), f["low"].to_numpy(), f["tday"].to_numpy()
    out = []
    for e in ev.itertuples():
        L, s, d, i = e.level, e.side, e.d, e.i
        rev, cont = L - s * d, L + s * d
        hit_c = (hi[i] >= cont) if s == 1 else (lo[i] <= cont)
        hit_r = (lo[i] <= rev) if s == 1 else (hi[i] >= rev)
        if hit_r:
            res, n = "ambiguous", 0
        elif hit_c:
            res, n = "continuation", 0
        else:
            res, n = "unresolved", None
            for j in range(i + 1, min(len(f), i + 1 + MAX_BARS)):
                if tday[j] != tday[i]:
                    break
                c = (hi[j] >= cont) if s == 1 else (lo[j] <= cont)
                r = (lo[j] <= rev) if s == 1 else (hi[j] >= rev)
                if c and r:
                    res, n = "ambiguous", j - i
                    break
                if r:
                    res, n = "reversal", j - i
                    break
                if c:
                    res, n = "continuation", j - i
                    break
        out.append({"result": res, "bars_to_result": n})
    return pd.concat([ev.reset_index(drop=True), pd.DataFrame(out)], axis=1)


def p_rev(df: pd.DataFrame) -> tuple[float, int]:
    r = (df["result"] == "reversal").sum()
    n = df["result"].isin(["reversal", "continuation"]).sum()
    return (r / n if n else np.nan), int(n)


def delta_stats(rd: pd.DataFrame, pl: pd.DataFrame) -> dict:
    """Primary: Δ = P_rev(round) − P_rev(placebo); session-clustered bootstrap SE and 95% CI; one-sided p (Δ>0)
    from the normal approximation Δ/SE."""
    pr, nr = p_rev(rd)
    pp, npl = p_rev(pl)
    delta = (pr - pp) * 100
    rng = np.random.default_rng(SEED)
    days = np.array(sorted(set(rd["tday"]) | set(pl["tday"])))

    def agg(df):
        g = df[df["result"].isin(["reversal", "continuation"])].groupby("tday")["result"]
        return g.apply(lambda x: (x == "reversal").sum()).reindex(days, fill_value=0).to_numpy(), \
            g.size().reindex(days, fill_value=0).to_numpy()
    rr, rn = agg(rd)
    prr, pn = agg(pl)
    boots = np.empty(BOOT)
    for b in range(BOOT):
        idx = rng.integers(0, len(days), len(days))
        boots[b] = (rr[idx].sum() / rn[idx].sum() - prr[idx].sum() / pn[idx].sum()) * 100
    se = float(boots.std(ddof=1))
    p_one = float(1 - 0.5 * (1 + math.erf((delta / se) / math.sqrt(2)))) if se > 0 else float("nan")
    return {"p_rev_round": pr, "n_round": nr, "p_rev_placebo": pp, "n_placebo": npl, "delta_pp": delta,
            "se_pp": se, "ci_lo_pp": float(np.percentile(boots, 2.5)), "ci_hi_pp": float(np.percentile(boots, 97.5)),
            "p_one_sided": p_one}


def main(which: str, dry: bool) -> None:
    f, t0, t1 = load(which)
    rd = events(f, (0.0,), t0, t1, "round")
    pl = events(f, PLACEBO_PRIMARY, t0, t1, "placebo")
    if dry:
        print(which, "round events", len(rd), "(from below", int((rd.side == 1).sum()), "/ from above",
              int((rd.side == -1).sum()), ") | placebo events", len(pl), "| sessions", f[f["time"] >= t0]["tday"].nunique())
        return
    out_dir = HERE / which
    out_dir.mkdir(exist_ok=True)
    rd, pl = race(f, rd), race(f, pl)
    ev = pd.concat([rd, pl], ignore_index=True)
    ev["year"] = ev["time"].dt.year
    ev["spread_over_d"] = [f["spread"].iat[i] * POINT / d if d > 0 else np.nan for i, d in zip(ev["i"], ev["d"])]
    ev.to_csv(out_dir / "events.csv", index=False)
    primary = delta_stats(rd, pl)
    res = {"which": which, "primary": primary,
           "result_counts": {g: ev[ev.group == g]["result"].value_counts().to_dict() for g in ("round", "placebo")}}
    # conservative variant: ambiguous counted as continuation (against the hypothesis), both groups
    cons = ev.copy()
    cons.loc[cons["result"] == "ambiguous", "result"] = "continuation"
    res["conservative_ambiguous_as_continuation"] = delta_stats(cons[cons.group == "round"], cons[cons.group == "placebo"])
    res["by_side"] = {("from_below" if s == 1 else "from_above"): delta_stats(rd[rd.side == s], pl[pl.side == s])
                      for s in (1, -1)}
    res["by_year"] = {int(y): delta_stats(rd[rd.time.dt.year == y], pl[pl.time.dt.year == y])
                      for y in sorted(rd.time.dt.year.unique())}
    res["leave_one_year_out"] = {int(y): delta_stats(rd[rd.time.dt.year != y], pl[pl.time.dt.year != y])
                                 for y in sorted(rd.time.dt.year.unique())}
    res["secondary_placebos"] = {}
    for name, offs in PLACEBO_SECONDARY.items():
        res["secondary_placebos"][name] = delta_stats(rd, pl[pl["offset"].isin(offs)])
    rd100 = rd[(rd["level"] % 100) == 0]
    res["secondary_round100_vs_placebo"] = delta_stats(rd100, pl)
    # cost plausibility (dev only; spread recorded): 1:1 fade at d breaks even at 0.5 + median(spread/d)/2
    sp = ev.loc[ev.group == "round", "spread_over_d"]
    if (f["spread"] > 0).mean() > 0.5:
        res["cost"] = {"median_spread_over_d": float(sp.median()), "breakeven_p_rev_1to1": float(0.5 + sp.median() / 2),
                       "p90_spread_over_d": float(sp.quantile(0.9))}
    s = pd.concat([rd.assign(q="round"), pl.assign(q="placebo")])
    res["bars_to_result_median"] = {g: float(s[(s.q == g) & s.bars_to_result.notna()].bars_to_result.median())
                                    for g in ("round", "placebo")}
    (out_dir / "result.json").write_text(json.dumps(res, indent=1, default=float) + "\n")
    print(json.dumps({"primary": primary, "by_side": {k: round(v["delta_pp"], 2) for k, v in res["by_side"].items()},
                      "loyo": {k: round(v["delta_pp"], 2) for k, v in res["leave_one_year_out"].items()}}, default=float))


if __name__ == "__main__":
    main(sys.argv[1], "--dry" in sys.argv)

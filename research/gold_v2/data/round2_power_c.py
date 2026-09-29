"""Family C power screen — COUNTS ONLY. Event: gold M15 log-return residual vs a USD proxy (rolling OLS beta over the
previous 480 M15 bars ≈ 20 sessions, strictly causal) with |resid| >= 2.5 × rolling residual std. Uses only returns up
to and including the event bar; no forward return is computed. Sealed lines are never parsed.
    venv/bin/python research/gold_v2/data/round2_power_c.py
"""
import glob, json, math, sys
from pathlib import Path
import numpy as np, pandas as pd
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE)); import v2_data as vd
R = HERE / "raw"
def m15(sym, a, b):
    f = vd.load_bars(sorted(glob.glob(str(R / f"v2_m1_{sym}_*.csv"))), a, b)
    return vd.aggregate(f, 15)["close"]
def events(proxy, a, b, sign=1.0):
    x, p = m15("XAUUSDm", a, b), m15(proxy, a, b)
    df = pd.concat([np.log(x).diff().rename("g"), (sign * np.log(p)).diff().rename("u")], axis=1).dropna()
    df = df[(df["g"] != 0) | (df["u"] != 0)]
    w = 480
    cov = (df["g"] * df["u"]).rolling(w).mean().shift() - df["g"].rolling(w).mean().shift() * df["u"].rolling(w).mean().shift()
    var = df["u"].rolling(w).var(ddof=0).shift()
    beta = cov / var
    resid = df["g"] - beta * df["u"]
    sd = resid.rolling(w).std().shift()
    z = resid / sd
    ev = z.abs() >= 2.5
    r2 = (beta ** 2 * var / df["g"].rolling(w).var(ddof=0).shift())
    return {"bars": int(z.notna().sum()), "events": int(ev.sum()), "events_by_year": {int(y): int(n) for y, n in ev[ev].groupby(ev[ev].index.year).size().items()},
            "median_beta": round(float(beta.median()), 3), "median_rolling_R2": round(float(r2.median()), 3)}
out = {"DXYm_2022_11_2026_06": events("DXYm", "2022.11.27 23:00:00", "2026.06.03 00:00:00"),
       "EURUSDm_2022_11_2026_06": events("EURUSDm", "2022.11.27 23:00:00", "2026.06.03 00:00:00"),
       "USDJPYm_2017_05_2021_08": events("USDJPYm", "2017.05.01 00:00:00", "2021.08.31 22:00:00"),
       "USDJPYm_2022_11_2026_06": events("USDJPYm", "2022.11.27 23:00:00", "2026.06.03 00:00:00")}
for k, v in out.items():
    n = v["events"]; v["detectable_reversal_share_diff_pp_vs_1to1_control"] = round(2.8 * math.sqrt(0.25 * 2 / max(1, n)) * 100, 1)
(HERE / "audit" / "round2_power_c.json").write_text(json.dumps(out, indent=1) + "\n"); print(json.dumps(out, indent=1))

"""Gold V2 new-data audit (M1 bars, cross-market M1, tick samples, probe) — data quality only, no outcomes.

    venv/bin/python research/gold_v2/data/audit_v2_data.py snapshot   # copy Common Files exports -> raw/, hash first
    venv/bin/python research/gold_v2/data/audit_v2_data.py audit      # audit the snapshot (never touches Common Files)

Sealed rows are skipped by text before parsing (v2_data.load_bars). Writes data/audit/*.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import v2_data as vd                                                                     # noqa: E402

ROOT = HERE.parents[2]
AUD = HERE / "audit"
NY = ZoneInfo("America/New_York")
M15_REFS = {  # audited XAUUSDm M15 references (unsealed spans only)
    "repaired_2017_2021": (ROOT / "research/gold_v1/history_expansion/repaired/xauusd_XAUUSDm_M15_repaired.csv",
                           "2017.06.01 00:00:00", "2021.08.31 22:00:00"),
    "dev_2022_2025": (ROOT / "research/gold_v1/history_expansion/h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv",
                      "2022.11.27 23:00:00", "2025.12.22 23:00:00"),
}
H1_REF = ROOT / "research/gold_v1/history_expansion/raw_full/xauusd_XAUUSDm_H1.csv"


def m1_files(sym: str) -> list[Path]:
    return sorted(vd.RAW.glob(f"v2_m1_{sym}_*.csv"))


def integrity(f: pd.DataFrame, minutes: int = 1) -> dict:
    bad = (f["high"] < f[["open", "close"]].max(axis=1)) | (f["low"] > f[["open", "close"]].min(axis=1)) | \
          (f["high"] < f["low"]) | (f[["open", "high", "low", "close"]] <= 0).any(axis=1)
    gap = f["time"].diff().dt.total_seconds().div(60)
    ny = f["time"].dt.tz_convert(NY)
    wk = f[gap.fillna(0) > 40 * 60]
    per_year = {}
    for y, g in f.groupby(f["time"].dt.year):
        smp = g["close"].head(20000)
        dec = smp.map(lambda x: len(f"{x:.6f}".rstrip("0").split(".")[1]) if "." in f"{x:.6f}".rstrip("0") else 0)
        per_year[int(y)] = {"bars": len(g), "spread_zero_share": round(float((g["spread"] == 0).mean()), 4),
                            "median_spread_points": float(g["spread"].median()),
                            "median_tick_volume": float(g["tick_volume"].median()),
                            "real_volume_nonzero": int((g["real_volume"] != 0).sum()),
                            "max_decimals": int(dec.max()), "flat_bars_share": round(float((g["high"] == g["low"]).mean()), 4)}
    return {"rows": len(f), "first": str(f["time"].iloc[0]), "last": str(f["time"].iloc[-1]),
            "monotonic": bool(f["time"].is_monotonic_increasing), "duplicates": int(f["time"].duplicated().sum()),
            "invalid_ohlc": int(bad.sum()), "misaligned": int((f["time"].dt.second != 0).sum()),
            "gaps_gt_1bar": int((gap > minutes).sum()), "gaps_ge_60min": int((gap >= 60).sum()),
            "intraday_holes_2_to_59min": int(((gap > minutes) & (gap < 60)).sum()),
            "weekly_opens_ny": ny[wk.index].dt.strftime("%a %H:%M").value_counts().head(4).to_dict(),
            "sealed_lines_skipped": int(f.attrs.get("sealed_lines_skipped", 0)), "by_year": per_year}


def m15_equality(m1: pd.DataFrame) -> dict:
    out = {}
    agg = vd.aggregate(m1, 15)
    for name, (path, a, b) in M15_REFS.items():
        ref = vd.load_bars([path], a, b).set_index("time")
        sub = agg[(agg.index >= ref.index.min()) & (agg.index <= ref.index.max())]
        j = ref.join(sub, how="outer", lsuffix="_ref", rsuffix="_m1")
        both = j.dropna(subset=["open_ref", "open_m1"])
        res = {"ref_bars": int(ref.shape[0]), "m1_agg_bars": int(sub.shape[0]), "common": int(len(both)),
               "only_ref": int(j["open_m1"].isna().sum()), "only_m1": int(j["open_ref"].isna().sum())}
        for c in ("open", "high", "low", "close"):
            res[f"{c}_mismatch"] = int(((both[f"{c}_ref"] - both[f"{c}_m1"]).abs() > 5e-4).sum())
        res["tick_volume_mismatch"] = int((both["tick_volume_ref"] != both["tick_volume_m1"]).sum())
        res["only_ref_examples"] = [str(t) for t in j.index[j["open_m1"].isna()][:8]]
        res["only_m1_examples"] = [str(t) for t in j.index[j["open_ref"].isna()][:8]]
        out[name] = res
    return out


def h1_equality(m1: pd.DataFrame) -> dict:
    agg = vd.aggregate(m1, 60)
    res = {}
    for name, (a, b) in {"2017_2021": ("2017.06.01 00:00:00", "2021.08.31 22:00:00"),
                         "2022_2025": ("2022.11.27 23:00:00", "2025.12.22 23:00:00")}.items():
        ref = vd.load_bars([H1_REF], a, b).set_index("time")
        sub = agg[(agg.index >= ref.index.min()) & (agg.index <= ref.index.max())]
        both = ref.join(sub, how="inner", lsuffix="_ref", rsuffix="_m1")
        res[name] = {"ref": len(ref), "m1_agg": len(sub), "common": len(both),
                     **{f"{c}_mismatch": int(((both[f"{c}_ref"] - both[f"{c}_m1"]).abs() > 5e-4).sum())
                        for c in ("open", "high", "low", "close")}}
    return res


def cross_alignment(base: pd.DataFrame, other: pd.DataFrame) -> dict:
    a, b = set(base["time"]), set(other["time"])
    common = a & b
    return {"xau_bars": len(a), "other_bars": len(b), "common": len(common),
            "share_of_xau_with_other": round(len(common) / max(1, len(a)), 4),
            "other_only": len(b - a), "xau_only": len(a - b)}


def tick_audit() -> dict:
    out = {}
    for p in sorted(vd.RAW.glob("v2_ticks_*.csv")) + sorted(vd.RAW.glob("v2_probe_ticks_*.csv")):
        t = pd.read_csv(p)
        if t.empty:
            out[p.name] = {"ticks": 0}
            continue
        ts = pd.to_datetime(t["time_msc"], unit="ms", utc=True)
        keep = ~ts.dt.strftime("%Y.%m.%d %H:%M:%S").map(vd.is_sealed)
        t, ts = t[keep], ts[keep]
        d = t["time_msc"].diff()
        both = (t["bid"] > 0) & (t["ask"] > 0)
        sp = (t["ask"] - t["bid"])[both]
        out[p.name] = {"ticks": int(len(t)), "sealed_rows_dropped": int((~keep).sum()),
                       "monotonic_msc": bool((d.dropna() >= 0).all()), "backward_steps": int((d < 0).sum()),
                       "duplicate_msc": int(t["time_msc"].duplicated().sum()),
                       "share_nonzero_ms": round(float((t["time_msc"] % 1000 != 0).mean()), 4),
                       "share_bid_and_ask": round(float(both.mean()), 4),
                       "crossed_or_locked": int((sp <= 0).sum()),
                       "spread_median": float(sp.median()) if len(sp) else None,
                       "spread_p99": float(sp.quantile(0.99)) if len(sp) else None,
                       "flags_counts": {int(k): int(v) for k, v in t["flags"].value_counts().head(8).items()},
                       "max_gap_seconds": float(d.max() / 1000) if len(d) > 1 else None,
                       "first": str(ts.iloc[0]), "last": str(ts.iloc[-1])}
    return out


def main(mode: str) -> None:
    if mode == "snapshot":
        got = vd.snapshot(["v2_probe*.json", "v2_probe*.csv", "v2_m1_*.csv", "v2_m1_*.metadata.json", "v2_ticks_*.csv"])
        print(f"snapshot: {len(got)} files hashed into {vd.RAW}/SHA256SUMS")
        return
    AUD.mkdir(exist_ok=True)
    res = {"probe": json.loads((vd.RAW / "v2_probe.json").read_text()) if (vd.RAW / "v2_probe.json").exists() else None}
    syms = sorted({p.name[len("v2_m1_"):].rsplit("_", 1)[0] for p in vd.RAW.glob("v2_m1_*_*.csv")})
    frames = {}
    for s in syms:
        f = vd.load_bars(m1_files(s), "2014.01.01 00:00:00", "2026.06.03 00:00:00")
        frames[s] = f
        res[f"m1_{s}"] = integrity(f)
    if "XAUUSDm" in frames:
        res["xau_m1_vs_m15_refs"] = m15_equality(frames["XAUUSDm"])
        res["xau_m1_vs_h1_ref"] = h1_equality(frames["XAUUSDm"])
        for s, f in frames.items():
            if s != "XAUUSDm":
                res[f"alignment_XAUUSDm_vs_{s}"] = cross_alignment(frames["XAUUSDm"], f)
    res["ticks"] = tick_audit()
    (AUD / "v2_data_audit.json").write_text(json.dumps(res, indent=1, default=str) + "\n")
    print("audit written:", AUD / "v2_data_audit.json", "| symbols:", syms)


if __name__ == "__main__":
    main(sys.argv[1])

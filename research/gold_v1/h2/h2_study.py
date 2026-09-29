"""Gold V1 — H2 event study: trend pullback to TVWAP / trend-side 1σ (DEVELOPMENT DATA ONLY).

    venv/bin/python research/gold_v1/h2/h2_study.py

Implements research/gold_v1/h2/preregistration.md exactly (rule numbers are cited inline). It reuses the corrected
H1 pipeline read-only (loader with the development cut, gate, causal features, forward race), so the two studies
are comparable. Bytecode writing is disabled so the frozen H1 folder is never touched.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "h1"))
import h1_study as h1                                                                   # noqa: E402

OUT = Path(__file__).resolve().parent
ER_MIN = 0.35                      # design (rule 1)
CLOSE_LOC_MIN, BODY_MIN = 0.65, 0.5   # design (rule 8)
CONTROLS_PER_EVENT = h1.CONTROLS_PER_EVENT
SEED = h1.SEED


# ---- H2 context features -----------------------------------------------------------------------------------------

def h2_features(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    hour_key = f["time"].dt.floor("1h")
    h1c = f.groupby(hour_key).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"))
    net = h1c["c"] - h1c["c"].shift(h1.ER_LEN)                    # rule 2: same window as the ER
    direction = np.sign(net)
    f["dir_h1"] = hour_key.map(direction.shift(1)).fillna(0).astype(int)      # last completed H1 bar only
    prev_c = h1c["c"].shift()
    tr = np.maximum(h1c["h"] - h1c["l"], np.maximum((h1c["h"] - prev_c).abs(), (h1c["l"] - prev_c).abs()))
    atr = tr.ewm(alpha=1 / h1.ATR_LEN, adjust=False).mean()
    atr.iloc[:h1.ATR_LEN] = np.nan
    rng = (h1c["h"] - h1c["l"]).replace(0, np.nan)
    exp = ((h1c["h"] - h1c["l"]) >= 1.5 * atr.shift()) & ((h1c["c"] - h1c["o"]).abs() / rng >= 0.6)
    f["h1_expansion"] = hour_key.map(exp.shift(1)).fillna(False).astype(bool)
    f["upper1"] = f["tvwap"] + f["tvwap_sd"]
    f["lower1"] = f["tvwap"] - f["tvwap_sd"]
    rng15 = f["high"] - f["low"]
    f["body_range"] = ((f["close"] - f["open"]).abs() / rng15).where(rng15 > 0)
    f["cl_up"] = ((f["close"] - f["low"]) / rng15).where(rng15 > 0)
    f["cl_dn"] = ((f["high"] - f["close"]) / rng15).where(rng15 > 0)
    return f


def in_regime(row_er, row_dir, row_slope, d: int) -> bool:
    """Rules 1–3 at a bar."""
    return bool(row_er >= ER_MIN and row_dir == d and ((row_slope > 0) if d == 1 else (row_slope < 0)))


def is_rejection(o, h, l, c, level, d) -> bool:
    """Rule 8."""
    rng = h - l
    if not rng > 0:
        return False
    body = abs(c - o) / rng
    if d == 1:
        return c > o and c > level and (c - l) / rng >= CLOSE_LOC_MIN and body >= BODY_MIN
    return c < o and c < level and (h - c) / rng >= CLOSE_LOC_MIN and body >= BODY_MIN


def zone_levels(i, d, up1, lo1, tv):
    return {"A": up1[i] if d == 1 else lo1[i], "B": tv[i]}


def touches(i, level, d, high, low) -> bool:
    """Rule 6."""
    return low[i] <= level if d == 1 else high[i] >= level


# ---- detection -------------------------------------------------------------------------------------------------------

def detect(f: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    tv, up1, lo1 = f["tvwap"].to_numpy(), f["upper1"].to_numpy(), f["lower1"].to_numpy()
    er, dr, sl = f["er_h1"].to_numpy(), f["dir_h1"].to_numpy(), f["tvwap_slope"].to_numpy()
    tday = f["tday"].to_numpy()
    n = len(f)
    events = []
    counts = {"raw_qualifying_bars": {"long": 0, "short": 0}, "unique_sequences": {"long": 0, "short": 0},
              "sequences_started": {"long": 0, "short": 0}, "rejected_risk_le_0": 0,
              "rejected_no_next_bar": 0}

    # raw qualifying bars (rule 14): regime + touch + rejection, ignoring sequences and first touch
    for i in range(n):
        for d, name in ((1, "long"), (-1, "short")):
            if np.isnan(er[i]) or not in_regime(er[i], dr[i], sl[i], d):
                continue
            lv = zone_levels(i, d, up1, lo1, tv)
            if any(touches(i, lv[z], d, h, l) and is_rejection(o[i], h[i], l[i], c[i], lv[z], d) for z in "AB"):
                counts["raw_qualifying_bars"][name] += 1

    starts = np.flatnonzero(np.r_[True, tday[1:] != tday[:-1]])
    ends = np.r_[starts[1:], n]
    for s, e in zip(starts, ends):
        for d, name in ((1, "long"), (-1, "short")):
            run_hi, run_lo = h[s], l[s]
            seq = None                          # dict(ext, eligible, consumed, first_zone, touched_in_regime, pending)
            for i in range(s + 1, e):
                new_trend = (h[i] > run_hi) if d == 1 else (l[i] < run_lo)
                new_counter = (l[i] < run_lo) if d == 1 else (h[i] > run_hi)
                run_hi, run_lo = max(run_hi, h[i]), min(run_lo, l[i])
                if new_trend:                                                  # rule 4 / 10: new sequence
                    if seq and seq["touched_in_regime"]:
                        counts["unique_sequences"][name] += 1
                    lv = zone_levels(i, d, up1, lo1, tv)
                    elig = {z for z in "AB" if ((l[i] > lv[z]) if d == 1 else (h[i] < lv[z]))}   # rule 5
                    seq = {"ext": i, "eligible": elig, "consumed": set(), "first_zone": None,
                           "touched_in_regime": False, "pending": None} if elig else None
                    if seq:
                        counts["sequences_started"][name] += 1
                    continue
                if seq is None:
                    continue
                lv = zone_levels(i, d, up1, lo1, tv)
                touched = None                                                  # rule 7: deepest new touch
                for z in ("B", "A"):
                    if z in seq["eligible"] and z not in seq["consumed"] and touches(i, lv[z], d, h, l):
                        touched = z
                        break
                signal_zone, first_touch_bar = None, None
                if touched:
                    seq["consumed"] |= {"A", "B"} if touched == "B" else {"A"}
                    seq["first_zone"] = seq["first_zone"] or touched
                    seq["pending"] = None                                       # rule 9: deeper touch cancels T+1
                    regime = not np.isnan(er[i]) and in_regime(er[i], dr[i], sl[i], d)
                    seq["touched_in_regime"] |= regime
                    if regime and is_rejection(o[i], h[i], l[i], c[i], lv[touched], d):
                        signal_zone, first_touch_bar = touched, i
                    else:
                        seq["pending"] = (touched, i)
                elif seq["pending"]:
                    z, t = seq["pending"]
                    seq["pending"] = None
                    regime = not np.isnan(er[i]) and in_regime(er[i], dr[i], sl[i], d)
                    if not new_counter and regime and is_rejection(o[i], h[i], l[i], c[i], lv[z], d):
                        signal_zone, first_touch_bar = z, t
                if signal_zone:
                    ev = _event(f, name, d, seq, signal_zone, first_touch_bar, i, e, counts)
                    if ev:
                        events.append(ev)
                    if seq["touched_in_regime"]:
                        counts["unique_sequences"][name] += 1
                    seq = None                                                 # rule 13: one event per sequence
                    continue
                if seq["consumed"] >= seq["eligible"] and not seq["pending"]:
                    if seq["touched_in_regime"]:
                        counts["unique_sequences"][name] += 1
                    seq = None
            if seq and seq["touched_in_regime"]:
                counts["unique_sequences"][name] += 1
    ev = pd.DataFrame(events)
    if len(ev):
        ev = ev.sort_values(["signal_index", "direction"]).reset_index(drop=True)
    return ev, counts


def _event(f, name, d, seq, zone, touch_bar, j, session_end, counts) -> dict | None:
    if j + 1 >= session_end:                                               # rule 12: entry in the same session
        counts["rejected_no_next_bar"] += 1
        return None
    ext = seq["ext"]
    window = f.iloc[ext + 1: j + 1]
    stop = float(window["low"].min() if d == 1 else window["high"].max())   # rule 11
    sig, nxt, xb = f.iloc[j], f.iloc[j + 1], f.iloc[ext]
    entry = float(nxt["open"])
    risk = entry - stop if d == 1 else stop - entry
    if not risk > 0:
        counts["rejected_risk_le_0"] += 1
        return None
    atr = sig["atr"]
    extreme = xb["high"] if d == 1 else xb["low"]
    return {
        "direction": name, "zone": zone, "first_zone": seq["first_zone"], "extreme_index": ext,
        "touch_index": touch_bar, "signal_index": j, "entry_index": j + 1, "extreme_time": xb["time"],
        "signal_time": sig["time"], "entry_time": nxt["time"], "extreme": extreme,
        "zone_level": (sig["upper1"] if d == 1 else sig["lower1"]) if zone == "A" else sig["tvwap"],
        "signal_close": sig["close"], "entry": entry, "stop": stop, "risk": risk, "risk_atr": risk / atr,
        "spread_px": nxt["spread_px"], "spread_risk": nxt["spread_px"] / risk,
        "er_h1": sig["er_h1"], "atr_pct": sig["atr_pct"], "vol_regime": sig["vol_regime"],
        "tvwap_slope": sig["tvwap_slope"], "pullback_depth_atr": abs(extreme - stop) / atr,
        "travel_atr": abs(extreme - xb["tvwap"]) / xb["atr"], "pullback_bars": j - ext,
        "rejection_delay": j - touch_bar, "body_range": sig["body_range"],
        "close_location": sig["cl_up"] if d == 1 else sig["cl_dn"], "tv_ratio": sig["tv_ratio"],
        "session": sig["session"], "hour": int(sig["hour"]), "dow": sig["dow"],
        "pdh_dist_atr": (sig["pdh"] - sig["close"]) / atr, "pdl_dist_atr": (sig["close"] - sig["pdl"]) / atr,
        "h1_expansion_before": bool(xb["h1_expansion"]), "atr": atr, "month": sig["time"].strftime("%Y-%m"),
    }


# ---- controls --------------------------------------------------------------------------------------------------------

def raw_qualifying_mask(f: pd.DataFrame, d: int) -> np.ndarray:
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    up1, lo1, tv = f["upper1"].to_numpy(), f["lower1"].to_numpy(), f["tvwap"].to_numpy()
    mask = np.zeros(len(f), dtype=bool)
    for i in range(len(f)):
        lv = zone_levels(i, d, up1, lo1, tv)
        mask[i] = any(touches(i, lv[z], d, h, l) and is_rejection(o[i], h[i], l[i], c[i], lv[z], d) for z in "AB")
    return mask


def controls(f: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    n = len(f)
    near = np.zeros(n, dtype=bool)
    for i in events["signal_index"]:
        near[max(0, i - 8): i + 9] = True
    tday = f["tday"].to_numpy()
    same_next = np.r_[tday[1:] == tday[:-1], False]
    base = (~near) & same_next & f["atr"].notna().to_numpy() & (f["er_h1"].to_numpy() >= ER_MIN)
    pools = {}
    for d, name in ((1, "long"), (-1, "short")):
        slope_ok = (f["tvwap_slope"].to_numpy() > 0) if d == 1 else (f["tvwap_slope"].to_numpy() < 0)
        ok = base & (f["dir_h1"].to_numpy() == d) & slope_ok & ~raw_qualifying_mask(f, d)
        pools[name] = pd.DataFrame({"index": np.flatnonzero(ok), "session": f["session"].to_numpy()[ok],
                                    "vol_regime": f["vol_regime"].to_numpy()[ok]})
    rows = []
    for e in events.itertuples():
        pool = pools[e.direction]
        match = pool[(pool["session"] == e.session) & (pool["vol_regime"] == e.vol_regime)]
        if match.empty:
            continue
        d = 1 if e.direction == "long" else -1
        for j in rng.choice(match["index"].to_numpy(), size=CONTROLS_PER_EVENT, replace=True):
            entry = float(f["open"].iloc[j + 1])
            risk = e.risk_atr * float(f["atr"].iloc[j])
            fw = h1.forward(f, j + 1, d, entry, risk)
            rows.append({"event_signal_index": e.signal_index, "signal_index": int(j), "direction": e.direction,
                         "zone": e.zone, "session": e.session, "vol_regime": e.vol_regime,
                         "month": f["time"].iloc[j].strftime("%Y-%m"), "risk_atr": e.risk_atr, **fw})
    return pd.DataFrame(rows)


# ---- H2 gate additions -----------------------------------------------------------------------------------------------

def h2_gate(dev: pd.DataFrame, f: pd.DataFrame, events: pd.DataFrame) -> dict:
    checks = {}
    cut = int(len(dev) * 0.7)
    fp = h2_features(h1.features(dev.iloc[:cut].reset_index(drop=True)))
    same = all(np.array_equal(fp[c].to_numpy(), f[c].iloc[:cut].to_numpy()) for c in ("dir_h1", "h1_expansion"))
    same &= all(np.allclose(fp[c].to_numpy(float), f[c].iloc[:cut].to_numpy(float), equal_nan=True)
                for c in ("upper1", "lower1", "body_range"))
    ep, _ = detect(fp)
    key = ["direction", "signal_index", "zone", "stop"]
    inner = set(map(tuple, events[events["entry_index"] < cut][key].to_numpy()))
    prefix = set(map(tuple, ep[ep["entry_index"] < cut][key].to_numpy()))
    checks["h2_prefix_invariance"] = {"pass": bool(same and inner == prefix),
                                      "events_in_prefix": len(inner), "method": "features and events at 70 %"}
    stop_ok = all(
        e.stop == (f["low"].iloc[e.extreme_index + 1:e.signal_index + 1].min() if e.direction == "long"
                   else f["high"].iloc[e.extreme_index + 1:e.signal_index + 1].max())
        and e.entry_index == e.signal_index + 1 and e.extreme_index < e.touch_index <= e.signal_index
        for e in events.itertuples())
    checks["h2_stop_causal"] = {"pass": bool(stop_ok),
                                "method": "stop = extreme of bars (extreme, signal]; no pivot confirmation"}
    hour = f["time"].dt.floor("1h")
    checks["h2_direction_completed_hour"] = {"pass": bool((f.groupby(hour)["dir_h1"].nunique() == 1).all())}
    return checks


def main() -> None:
    dev = h1.load_dev()
    assert dev["time"].max() < h1.DEV_END
    base = h1.features(dev)
    gate = h1.quality_gate(dev, base)                    # the corrected H1 gate, unchanged
    f = h2_features(base)
    events, counts = detect(f)
    gate.update(h2_gate(dev, f, events))
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values() if isinstance(v, dict)) else "BLOCKED"
    (OUT / "data_quality.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("DATA QUALITY BLOCKED")
    fw = [h1.forward(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
          for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw)], axis=1)
    ctrl = controls(f, events)
    events.to_csv(OUT / "h2_events_dev.csv", index=False)
    ctrl.to_csv(OUT / "h2_controls_dev.csv", index=False)
    (OUT / "h2_counts_dev.json").write_text(json.dumps(counts, indent=1) + "\n")
    print("gate", gate["result"], "events", len(events), "controls", len(ctrl))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()

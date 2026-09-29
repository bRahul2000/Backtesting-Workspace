"""Gold V1 — H3 event study: compression → displacement → acceptance (DEVELOPMENT DATA ONLY).

    venv/bin/python research/gold_v1/h3/h3_study.py

Implements research/gold_v1/h3/preregistration.md exactly (rule numbers are cited inline). It reuses the corrected
H1 pipeline read-only (development cut, gate, causal features incl. rng8 / its trailing percentile / Wilder ATR /
expansion, and the forward race). Bytecode writing is disabled so the frozen H1 folder is never touched.
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
WINDOW, PCT_MAX, LIFETIME = 8, 20, 8                  # design
ATR_PCT_TOL = 10                                      # control matching (preregistered)
CONTROLS_PER_EVENT, SEED = h1.CONTROLS_PER_EVENT, h1.SEED


def h3_features(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    tday = f["tday"].to_numpy()
    same_day = np.r_[np.zeros(WINDOW - 1, dtype=bool), tday[WINDOW - 1:] == tday[:-(WINDOW - 1)]]
    f["compressed"] = (f["rng8_pct"] <= PCT_MAX).to_numpy() & same_day                  # rules 1–3
    prev = np.r_[False, f["compressed"].to_numpy()[:-1]]
    prev_day = np.r_[-1, tday[:-1]]
    new_run = f["compressed"].to_numpy() & ~(prev & (prev_day == tday))                  # rule 4
    run = np.cumsum(new_run)
    f["run_id"] = np.where(f["compressed"], run, 0)
    f["box_high"] = f["high"].rolling(WINDOW).max()
    f["box_low"] = f["low"].rolling(WINDOW).min()
    return f


def detect(f: pd.DataFrame) -> tuple[pd.DataFrame, dict, set]:
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    tday, comp, run = f["tday"].to_numpy(), f["compressed"].to_numpy(), f["run_id"].to_numpy()
    bh, bl, exp = f["box_high"].to_numpy(), f["box_low"].to_numpy(), f["expansion"].to_numpy()
    n = len(f)
    counts = {"raw_compression_structures": int(len(set(run[run > 0]))),
              "raw_displacement_bars": int(exp.sum()),
              "candidate_displacements": {"long": 0, "short": 0}, "candidates_two_sided": 0,
              "no_acceptance_bar": 0, "acceptance_failed": {"long": 0, "short": 0},
              "accepted_breakouts": {"long": 0, "short": 0}, "suppressed_duplicates": 0,
              "no_entry_bar": 0, "rejected_risk_le_0": 0}
    used, events, acceptance_bars = set(), [], set()
    last_comp, last_exp = -1, -1
    for D in range(n):
        if D > 0 and comp[D - 1]:
            last_comp = D - 1
        if D > 0 and exp[D - 1]:
            last_exp_before = D - 1
        else:
            last_exp_before = last_exp
        k = last_comp
        valid_ctx = k >= 0 and 1 <= D - k <= LIFETIME and tday[k] == tday[D]            # rule 5
        if exp[D]:
            last_exp = D
        if not (valid_ctx and exp[D]):
            continue
        hi, lo = bh[k], bl[k]
        between = c[k + 1:D]
        if ((between > hi) | (between < lo)).any():                                       # rule 6
            continue
        if c[D] > hi and c[D] > o[D]:                                                      # rules 8–9
            d, name = 1, "long"
        elif c[D] < lo and c[D] < o[D]:
            d, name = -1, "short"
        else:
            continue
        counts["candidate_displacements"][name] += 1
        two_sided = bool(h[D] > hi and l[D] < lo)                                          # rule 10
        counts["candidates_two_sided"] += two_sided
        A = D + 1
        if A >= n or tday[A] != tday[D]:
            counts["no_acceptance_bar"] += 1
            continue
        accepted = c[A] > hi if d == 1 else c[A] < lo                                      # rule 11
        if not accepted:
            counts["acceptance_failed"][name] += 1
            continue
        counts["accepted_breakouts"][name] += 1
        acceptance_bars.add(A)
        if (run[k], d) in used:                                                            # rule 15
            counts["suppressed_duplicates"] += 1
            continue
        used.add((run[k], d))
        if (l[A] <= hi) if d == 1 else (h[A] >= lo):                                       # rule 12
            shape = "wick_inside"
        elif (c[A] > c[D]) if d == 1 else (c[A] < c[D]):
            shape = "continues"
        else:
            shape = "stalls"
        E = A + 1
        if E >= n or tday[E] != tday[A]:                                                   # rule 13
            counts["no_entry_bar"] += 1
            continue
        entry = float(o[E])
        stop = float(l[D] if d == 1 else h[D])                                             # rule 14
        risk = entry - stop if d == 1 else stop - entry
        if not risk > 0:
            counts["rejected_risk_le_0"] += 1
            continue
        events.append(_event(f, name, d, k, D, A, E, entry, stop, risk, hi, lo, two_sided, shape,
                             last_exp_before))
    ev = pd.DataFrame(events)
    return ev, counts, acceptance_bars


def _event(f, name, d, k, D, A, E, entry, stop, risk, hi, lo, two_sided, shape, last_exp) -> dict:
    fk, fd, fa, fe = f.iloc[k], f.iloc[D], f.iloc[A], f.iloc[E]
    atr_k, atr_d, atr_a = fk["atr"], f["atr"].iloc[D - 1], fa["atr"]
    run_start = int(np.flatnonzero((f["run_id"].to_numpy() == fk["run_id"]))[0])
    rng = fd["high"] - fd["low"]
    boundary = hi if d == 1 else lo
    mid = (hi + lo) / 2
    return {
        "direction": name, "structure_id": int(fk["run_id"]), "compression_index": k, "displacement_index": D,
        "signal_index": A, "entry_index": E, "compression_time": fk["time"], "displacement_time": fd["time"],
        "signal_time": fa["time"], "entry_time": fe["time"], "box_high": hi, "box_low": lo,
        "box_width": hi - lo, "box_width_atr": (hi - lo) / atr_k, "compression_pct": fk["rng8_pct"],
        "compression_duration": k - run_start + 1, "bars_since_expansion": (D - last_exp) if last_exp >= 0 else np.nan,
        "bars_compression_to_displacement": D - k,
        "disp_range_atr": rng / atr_d, "disp_body_range": abs(fd["close"] - fd["open"]) / rng,
        "disp_close_location": ((fd["close"] - fd["low"]) if d == 1 else (fd["high"] - fd["close"])) / rng,
        "dist_beyond_atr": d * (fd["close"] - boundary) / atr_d, "disp_tv_ratio": fd["tv_ratio"],
        "two_sided": two_sided, "acceptance_shape": shape,
        "signal_close": fa["close"], "entry": entry, "stop": stop, "risk": risk, "risk_atr": risk / atr_a,
        "spread_px": fe["spread_px"], "spread_risk": fe["spread_px"] / risk,
        "er_h1": fa["er_h1"], "regime": fa["regime"], "atr_pct": fa["atr_pct"], "vol_regime": fa["vol_regime"],
        "tvwap_dist_atr": (fa["close"] - fa["tvwap"]) / atr_a, "tvwap_slope": fa["tvwap_slope"],
        "toward_tvwap": bool(np.sign(fk["tvwap"] - mid) == d), "tv_ratio": fa["tv_ratio"],
        "session": fa["session"], "hour": int(fa["hour"]), "dow": fa["dow"],
        "pdh_dist_atr": (fa["pdh"] - fa["close"]) / atr_a, "pdl_dist_atr": (fa["close"] - fa["pdl"]) / atr_a,
        "atr": atr_a, "month": fa["time"].strftime("%Y-%m"),
    }


def controls(f: pd.DataFrame, events: pd.DataFrame, acceptance_bars: set) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    n = len(f)
    near = np.zeros(n, dtype=bool)
    for i in events["signal_index"]:
        near[max(0, i - 8): i + 9] = True
    tday = f["tday"].to_numpy()
    ok = (~near) & np.r_[tday[1:] == tday[:-1], False] & f["atr"].notna().to_numpy() & f["atr_pct"].notna().to_numpy()
    ok[list(acceptance_bars)] = False
    pool = pd.DataFrame({"index": np.flatnonzero(ok), "session": f["session"].to_numpy()[ok],
                         "vol_regime": f["vol_regime"].to_numpy()[ok], "atr_pct": f["atr_pct"].to_numpy()[ok]})
    rows = []
    for e in events.itertuples():
        base = pool[(pool["session"] == e.session) & (pool["vol_regime"] == e.vol_regime)]
        near_pct = base[(base["atr_pct"] - e.atr_pct).abs() <= ATR_PCT_TOL]
        relaxed = len(near_pct) < CONTROLS_PER_EVENT
        match = base if relaxed else near_pct
        if match.empty:
            continue
        d = 1 if e.direction == "long" else -1
        for j in rng.choice(match["index"].to_numpy(), size=CONTROLS_PER_EVENT, replace=True):
            entry = float(f["open"].iloc[j + 1])
            risk = e.risk_atr * float(f["atr"].iloc[j])
            fw = h1.forward(f, j + 1, d, entry, risk)
            rows.append({"event_signal_index": e.signal_index, "signal_index": int(j), "direction": e.direction,
                         "session": e.session, "vol_regime": e.vol_regime, "atr_pct": float(f["atr_pct"].iloc[j]),
                         "event_atr_pct": e.atr_pct, "atr_pct_relaxed": relaxed, "risk_atr": e.risk_atr,
                         "two_sided": e.two_sided, "month": f["time"].iloc[j].strftime("%Y-%m"), **fw})
    return pd.DataFrame(rows)


def h3_gate(dev: pd.DataFrame, f: pd.DataFrame, events: pd.DataFrame) -> dict:
    checks = {}
    cut = int(len(dev) * 0.7)
    fp = h3_features(h1.features(dev.iloc[:cut].reset_index(drop=True)))
    same = all(np.array_equal(fp[c].to_numpy(), f[c].iloc[:cut].to_numpy()) for c in ("compressed", "run_id"))
    same &= all(np.allclose(fp[c].to_numpy(float), f[c].iloc[:cut].to_numpy(float), equal_nan=True)
                for c in ("box_high", "box_low", "rng8_pct"))
    ep, _, _ = detect(fp)
    key = ["direction", "displacement_index", "signal_index", "stop", "box_high", "box_low"]
    inner = set(map(tuple, events[events["entry_index"] < cut][key].to_numpy()))
    prefix = set(map(tuple, ep[ep["entry_index"] < cut][key].to_numpy())) if len(ep) else set()
    checks["h3_prefix_invariance"] = {"pass": bool(same and inner == prefix), "events_in_prefix": len(inner),
                                      "method": "features and events at 70 %"}
    tday = f["tday"].to_numpy()
    ok = True
    for e in events.itertuples():
        k, D = e.compression_index, e.displacement_index
        ok &= 1 <= D - k <= LIFETIME and tday[k - 7] == tday[k] == tday[D] == tday[e.signal_index] == tday[e.entry_index]
        ok &= e.box_high == f["high"].iloc[k - 7:k + 1].max() and e.box_low == f["low"].iloc[k - 7:k + 1].min()
        ok &= e.signal_index == D + 1 and e.entry_index == D + 2
        ok &= e.stop == (f["low"].iloc[D] if e.direction == "long" else f["high"].iloc[D])
        ok &= bool(f["compressed"].iloc[k]) and f["rng8_pct"].iloc[k] <= PCT_MAX
    checks["h3_structure_causal"] = {"pass": bool(ok), "method": "box = bars k−7..k < D (same day), D−k ≤ 8, "
                                     "A = D+1, E = D+2, stop = displacement bar's opposite side"}
    return checks


def main() -> None:
    dev = h1.load_dev()
    assert dev["time"].max() < h1.DEV_END
    base = h1.features(dev)
    gate = h1.quality_gate(dev, base)
    f = h3_features(base)
    events, counts, acc = detect(f)
    gate.update(h3_gate(dev, f, events))
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values() if isinstance(v, dict)) else "BLOCKED"
    (OUT / "data_quality.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("DATA QUALITY BLOCKED")
    fw = [h1.forward(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
          for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw)], axis=1)
    ctrl = controls(f, events, acc)
    events.to_csv(OUT / "h3_events_dev.csv", index=False)
    ctrl.to_csv(OUT / "h3_controls_dev.csv", index=False)
    (OUT / "h3_counts_dev.json").write_text(json.dumps(counts, indent=1) + "\n")
    print("gate", gate["result"], "events", len(events), "controls", len(ctrl))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()

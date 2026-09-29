"""Gold V1 — H5 event study: New York opening-range acceptance (DEVELOPMENT DATA ONLY).

    venv/bin/python research/gold_v1/h5/h5_study.py

Implements research/gold_v1/h5/preregistration.md exactly (item numbers are cited inline). It reuses the corrected
H1 pipeline read-only (development cut, gate, causal features, forward race). Bytecode writing is disabled so the
frozen H1 folder is never touched.
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
OR_BARS = (9 * 60 + 30, 9 * 60 + 45)            # item 1: bar starts, New York local minutes
FIRST_OUTSIDE = 10 * 60                         # item 4
FIRST_CONFIRM = 10 * 60 + 15
LAST_CONFIRM = 12 * 60 + 45                     # item 15: closes by 13:00 New York
LATE_BAR = 16 * 60 + 45                         # us_short_session flag
ATR_PCT_TOL = 10
CONTROLS_PER_EVENT, SEED = h1.CONTROLS_PER_EVENT, h1.SEED


def ny_minutes(f: pd.DataFrame) -> np.ndarray:
    """Item 2: bar-start wall-clock minutes in America/New_York (zoneinfo, DST-aware)."""
    local = f["time"].dt.tz_convert(h1.NEW_YORK)
    return (local.dt.hour * 60 + local.dt.minute).to_numpy()


def opening_ranges(f: pd.DataFrame) -> pd.DataFrame:
    """One row per trading day that has both OR bars (items 1–3). Causal: uses only the two OR bars."""
    nym = ny_minutes(f)
    rows = []
    for day, idx in pd.Series(np.arange(len(f))).groupby(f["tday"].to_numpy()):
        idx = idx.to_numpy()
        a = idx[nym[idx] == OR_BARS[0]]
        b = idx[nym[idx] == OR_BARS[1]]
        if len(a) != 1 or len(b) != 1 or b[0] != a[0] + 1:
            continue
        o1, o2 = a[0], b[0]
        hi = max(f["high"].iloc[o1], f["high"].iloc[o2])
        lo = min(f["low"].iloc[o1], f["low"].iloc[o2])
        atr = f["atr"].iloc[o2]
        rows.append({"tday": day, "or_first": o1, "or_last": o2, "day_first": idx[0], "day_last": idx[-1],
                     "or_high": hi, "or_low": lo, "or_mid": (hi + lo) / 2, "or_width": hi - lo, "or_atr": atr,
                     "or_width_atr": (hi - lo) / atr if atr else np.nan,
                     "or_time_utc": f["time"].iloc[o1]})
    ors = pd.DataFrame(rows)
    w = ors["or_width_atr"].to_numpy()
    pct = np.full(len(ors), np.nan)
    for i in range(len(ors)):
        prev = w[max(0, i - 20):i]
        prev = prev[~np.isnan(prev)]
        if len(prev) >= 10 and not np.isnan(w[i]):
            pct[i] = (prev < w[i]).mean() * 100
    ors["or_width_pct"] = pct
    return ors


def _pos(x, hi, lo):
    if np.isnan(hi) or np.isnan(lo):
        return "na"
    return "above" if x > hi else ("below" if x < lo else "inside")


def detect(f: pd.DataFrame, ors: pd.DataFrame) -> tuple[pd.DataFrame, dict, pd.DataFrame, set]:
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = f["time"].to_numpy()
    nym = ny_minutes(f)
    last_start = pd.Series(nym).groupby(f["tday"].to_numpy()).last()
    counts = {"days_studied": int(f["tday"].nunique()), "days_with_or": int(len(ors)),
              "raw_outside_closes": {"long": 0, "short": 0}, "confirmations": {"long": 0, "short": 0},
              "suppressed_duplicates": {"long": 0, "short": 0}, "no_entry_bar": 0, "rejected_risk_le_0": 0}
    events, days, confirm_bars = [], [], set()
    for r in ors.itertuples():
        idx = np.arange(r.or_last + 1, r.day_last + 1)
        window = idx[(nym[idx] >= FIRST_OUTSIDE) & (nym[idx] <= LAST_CONFIRM)]
        streak = {1: 0, -1: 0}
        fired = {1: None, -1: None}
        prev_i = None
        for i in window:
            contiguous = prev_i is not None and i == prev_i + 1 and \
                (t[i] - t[prev_i]) == np.timedelta64(15, "m")
            for d, name in ((1, "long"), (-1, "short")):
                outside = c[i] > r.or_high if d == 1 else c[i] < r.or_low                # item 5
                if outside:
                    counts["raw_outside_closes"][name] += 1
                    streak[d] = streak[d] + 1 if (streak[d] and contiguous) else 1       # items 7–9
                else:
                    streak[d] = 0
                if streak[d] >= 2 and nym[i] >= FIRST_CONFIRM:
                    counts["confirmations"][name] += 1
                    confirm_bars.add(int(i))
                    if fired[d] is not None:                                              # item 12
                        counts["suppressed_duplicates"][name] += 1
                        continue
                    fired[d] = i
            prev_i = i
        order = sorted([(i, d) for d, i in fired.items() if i is not None])
        for rank, (i, d) in enumerate(order):
            ev = _event(f, r, d, i, rank, len(order) == 2, counts, nym, last_start, o, h, l, c)
            if ev:
                events.append(ev)
        # descriptive break analysis (trade-through, 10:00 New York → end of the trading day; uses the future)
        after = idx[nym[idx] >= FIRST_OUTSIDE]
        up = after[h[after] > r.or_high]
        dn = after[l[after] < r.or_low]
        first_up, first_dn = (up[0] if len(up) else None), (dn[0] if len(dn) else None)
        if first_up is None and first_dn is None:
            first = "none"
        elif first_dn is None or (first_up is not None and first_up < first_dn):
            first = "up"
        elif first_up is None or first_dn < first_up:
            first = "down"
        else:
            first = "both_same_bar"
        days.append({"tday": r.tday, "or_width_pct": r.or_width_pct, "first_break": first,
                     "broke_up": first_up is not None, "broke_down": first_dn is not None,
                     "long_event": fired[1] is not None, "short_event": fired[-1] is not None,
                     "us_short_session": bool(last_start[r.tday] < LATE_BAR)})
    ev = pd.DataFrame(events)
    if len(ev):
        ev = ev.sort_values(["signal_index", "direction"]).reset_index(drop=True)
    return ev, counts, pd.DataFrame(days), confirm_bars


def _event(f, r, d, i, rank, both, counts, nym, last_start, o, h, l, c) -> dict | None:
    E = i + 1
    if E > r.day_last:                                                                    # item 11
        counts["no_entry_bar"] += 1
        return None
    entry = float(o[E])
    risk = entry - r.or_mid if d == 1 else r.or_mid - entry                               # item 10
    if not risk > 0:
        counts["rejected_risk_le_0"] += 1
        return None
    sig, prev, ent = f.iloc[i], f.iloc[i - 1], f.iloc[E]
    atr = sig["atr"]
    boundary = r.or_high if d == 1 else r.or_low

    def close_stats(j):
        rng = h[j] - l[j]
        wick = max(0.0, (boundary - l[j]) if d == 1 else (h[j] - boundary))
        return (d * (c[j] - boundary) / atr, wick / atr, abs(c[j] - o[j]) / rng if rng else np.nan,
                (((c[j] - l[j]) if d == 1 else (h[j] - c[j])) / rng) if rng else np.nan)
    d1, w1, b1, cl1 = close_stats(i - 1)
    d2, w2, b2, cl2 = close_stats(i)
    span = np.arange(r.or_last + 1, i + 1)
    span = span[nym[span] >= FIRST_OUTSIDE]
    up = span[h[span] > r.or_high]
    dn = span[l[span] < r.or_low]
    if len(up) and len(dn):
        first = "up" if up[0] < dn[0] else ("down" if dn[0] < up[0] else "both_same_bar")
    else:
        first = "up" if len(up) else ("down" if len(dn) else "none")
    opposite_swept = bool(len(dn)) if d == 1 else bool(len(up))
    fo2 = f.iloc[r.or_last]
    day_open = f["open"].iloc[r.day_first]
    local = sig["time"].tz_convert(h1.NEW_YORK)
    return {
        "direction": "long" if d == 1 else "short", "tday": r.tday, "first_close_index": i - 1, "signal_index": i,
        "entry_index": E, "signal_time": sig["time"], "signal_time_ny": local.strftime("%H:%M"),
        "entry_time": ent["time"], "or_time_utc": r.or_time_utc, "or_high": r.or_high, "or_low": r.or_low,
        "or_mid": r.or_mid, "or_width": r.or_width, "or_width_atr": r.or_width_atr, "or_width_pct": r.or_width_pct,
        "overnight_dist_atr": (r.or_mid - day_open) / fo2["atr"],
        "or_vs_pd": _pos(r.or_mid, fo2["pdh"], fo2["pdl"]), "or_vs_asia": _pos(r.or_mid, fo2["asia_high"], fo2["asia_low"]),
        "first_break": first, "opposite_swept_before": opposite_swept,
        "close1_dist_atr": d1, "close1_wick_atr": w1, "close1_body_range": b1, "close1_close_loc": cl1,
        "close2_dist_atr": d2, "close2_wick_atr": w2, "close2_body_range": b2, "close2_close_loc": cl2,
        "tv_ratio": sig["tv_ratio"], "signal_close": sig["close"], "entry": entry, "stop": r.or_mid, "risk": risk,
        "risk_atr": risk / atr, "spread_px": ent["spread_px"], "spread_risk": ent["spread_px"] / risk,
        "er_h1": sig["er_h1"], "regime": sig["regime"], "atr_pct": sig["atr_pct"], "vol_regime": sig["vol_regime"],
        "tvwap_pos_atr": (sig["close"] - sig["tvwap"]) / atr, "tvwap_slope": sig["tvwap_slope"],
        "dow": sig["dow"], "session": sig["session"], "both_directions_day": both,
        "opposite_confirmed_earlier": bool(both and rank == 1),
        "us_short_session": bool(last_start[r.tday] < LATE_BAR), "atr": atr,
        "month": sig["time"].strftime("%Y-%m"),
    }


def tercile(p):
    return "na" if np.isnan(p) else ("low" if p < 100 / 3 else ("mid" if p < 200 / 3 else "high"))


def controls(f: pd.DataFrame, ors: pd.DataFrame, events: pd.DataFrame, confirm_bars: set) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    n = len(f)
    nym = ny_minutes(f)
    near = np.zeros(n, dtype=bool)
    for i in events["signal_index"]:
        near[max(0, i - 8): i + 9] = True
    tday = f["tday"].to_numpy()
    or_days = set(ors["tday"])
    day_pct = dict(zip(ors["tday"], ors["or_width_pct"]))
    ok = (~near) & (nym >= FIRST_CONFIRM) & (nym <= LAST_CONFIRM) & np.isin(tday, list(or_days))
    ok &= np.r_[tday[1:] == tday[:-1], False] & f["atr"].notna().to_numpy() & f["atr_pct"].notna().to_numpy()
    ok[list(confirm_bars)] = False
    idx = np.flatnonzero(ok)
    pool = pd.DataFrame({"index": idx, "vol_regime": f["vol_regime"].to_numpy()[idx],
                         "atr_pct": f["atr_pct"].to_numpy()[idx],
                         "or_terc": [tercile(day_pct[d]) for d in tday[idx]]})
    rows = []
    for e in events.itertuples():
        base = pool[pool["vol_regime"] == e.vol_regime]
        by_atr = base[(base["atr_pct"] - e.atr_pct).abs() <= ATR_PCT_TOL]
        terc = tercile(e.or_width_pct)
        by_or = by_atr[by_atr["or_terc"] == terc] if terc != "na" else by_atr.iloc[0:0]
        or_relaxed, atr_relaxed = len(by_or) < CONTROLS_PER_EVENT, False
        match = by_atr if or_relaxed else by_or
        if len(match) < CONTROLS_PER_EVENT:
            match, atr_relaxed = base, True
        if match.empty:
            continue
        d = 1 if e.direction == "long" else -1
        for j in rng.choice(match["index"].to_numpy(), size=CONTROLS_PER_EVENT, replace=True):
            entry = float(f["open"].iloc[j + 1])
            risk = e.risk_atr * float(f["atr"].iloc[j])
            fw = h1.forward(f, j + 1, d, entry, risk)
            rows.append({"event_signal_index": e.signal_index, "signal_index": int(j), "direction": e.direction,
                         "vol_regime": e.vol_regime, "atr_pct": float(f["atr_pct"].iloc[j]),
                         "event_atr_pct": e.atr_pct, "or_terc": tercile(day_pct[tday[j]]), "event_or_terc": terc,
                         "or_pct_relaxed": or_relaxed, "atr_pct_relaxed": atr_relaxed, "risk_atr": e.risk_atr,
                         "both_directions_day": e.both_directions_day,
                         "month": f["time"].iloc[j].strftime("%Y-%m"), **fw})
    return pd.DataFrame(rows)


def h5_gate(dev, f, ors, events) -> dict:
    checks = {}
    local = ors["or_time_utc"].dt.tz_convert(h1.NEW_YORK)
    est = local.dt.strftime("%z") == "-0500"
    ok_dst = bool(((local.dt.hour == 9) & (local.dt.minute == 30)).all()
                  and (ors.loc[est, "or_time_utc"].dt.hour == 14).all()
                  and (ors.loc[~est, "or_time_utc"].dt.hour == 13).all())
    checks["h5_or_dst_mapping"] = {"pass": ok_dst, "est_days": int(est.sum()), "edt_days": int((~est).sum()),
                                   "method": "every OR starts 09:30 New York = 14:30 UTC (EST) / 13:30 UTC (EDT)"}
    nym = ny_minutes(f)
    ok = True
    for e in events.itertuples():
        r = ors[ors["tday"] == e.tday].iloc[0]
        ok &= r.or_last < e.first_close_index and e.signal_index == e.first_close_index + 1
        ok &= FIRST_CONFIRM <= nym[e.signal_index] <= LAST_CONFIRM and nym[e.first_close_index] >= FIRST_OUTSIDE
        ok &= e.or_high == max(f["high"].iloc[r.or_first], f["high"].iloc[r.or_last])
        ok &= e.or_low == min(f["low"].iloc[r.or_first], f["low"].iloc[r.or_last])
        ok &= e.entry_index == e.signal_index + 1 and e.stop == e.or_mid
    checks["h5_or_causal"] = {"pass": bool(ok), "method": "OR from the 09:30/09:45 bars only; both confirming closes "
                              "after 10:00 New York; confirmation ≤ 12:45 bar; entry next bar; stop OR mid"}
    cut = int(len(dev) * 0.7)
    fp = h1.features(dev.iloc[:cut].reset_index(drop=True))
    orp = opening_ranges(fp)
    ep, _, _, _ = detect(fp, orp)
    key = ["direction", "signal_index", "or_high", "or_low", "entry", "stop"]
    inner = set(map(tuple, events[events["entry_index"] < cut][key].to_numpy()))
    prefix = set(map(tuple, ep[ep["entry_index"] < cut][key].to_numpy()))
    checks["h5_prefix_invariance"] = {"pass": bool(inner == prefix), "events_in_prefix": len(inner)}
    return checks


def main() -> None:
    dev = h1.load_dev()
    assert dev["time"].max() < h1.DEV_END
    f = h1.features(dev)
    gate = h1.quality_gate(dev, f)
    ors = opening_ranges(f)
    events, counts, days, confirm_bars = detect(f, ors)
    gate.update(h5_gate(dev, f, ors, events))
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values() if isinstance(v, dict)) else "BLOCKED"
    (OUT / "data_quality.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("DATA QUALITY BLOCKED")
    fw = [h1.forward(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
          for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw)], axis=1)
    ctrl = controls(f, ors, events, confirm_bars)
    events.to_csv(OUT / "h5_events_dev.csv", index=False)
    ctrl.to_csv(OUT / "h5_controls_dev.csv", index=False)
    days.to_csv(OUT / "h5_days_dev.csv", index=False)
    ors.to_csv(OUT / "h5_opening_ranges_dev.csv", index=False)
    (OUT / "h5_counts_dev.json").write_text(json.dumps(counts, indent=1) + "\n")
    print("gate", gate["result"], "events", len(events), "controls", len(ctrl))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()

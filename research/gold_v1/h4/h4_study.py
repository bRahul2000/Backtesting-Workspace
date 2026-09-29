"""Gold V1 — H4 event study: TVWAP ±2σ exhaustion → ±1σ reentry fade (DEVELOPMENT DATA ONLY).

    venv/bin/python research/gold_v1/h4/h4_study.py

Implements research/gold_v1/h4/preregistration.md exactly (item numbers are cited inline). It reuses the corrected
H1 pipeline read-only (development cut, gate, causal features, standard forward race). Bytecode writing is disabled
so the frozen H1 folder is never touched.
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
ER_MAX = 0.15                                   # design (item 2)
WINDOW = 2                                      # design (item 6)
MIN_BAR = 4                                     # item 17: X is at least the 5th bar of its session (0-based 4)
NY_OPEN = (9 * 60 + 30, 10 * 60 + 15)           # item 18: reentry bars starting 09:30–10:15 New York
ATR_PCT_TOL, DIST_TOL = 10, 0.25
CONTROLS_PER_EVENT, SEED = h1.CONTROLS_PER_EVENT, h1.SEED
SIDES = ((-1, "short", "upper"), (1, "long", "lower"))


def h4_features(f: pd.DataFrame) -> pd.DataFrame:
    f = f.copy()
    sd = f["tvwap_sd"]
    f["u2"], f["u1"] = f["tvwap"] + 2 * sd, f["tvwap"] + sd
    f["l1"], f["l2"] = f["tvwap"] - sd, f["tvwap"] - 2 * sd
    f["bar_no"] = f.groupby("tday").cumcount()
    local = f["time"].dt.tz_convert(h1.NEW_YORK)
    nym = local.dt.hour * 60 + local.dt.minute
    f["ny_open_hour"] = (nym >= NY_OPEN[0]) & (nym <= NY_OPEN[1])
    f["session_last"] = f.groupby("tday")["time"].transform("size") - 1 - f["bar_no"] + np.arange(len(f))
    return f


def outside(c, u2, l2, d):
    """Item 3 (d = trade direction: −1 short fades the upper band, +1 long fades the lower band)."""
    return c > u2 if d == -1 else c < l2


def inside1(c, u1, l1):
    """Item 4."""
    return l1 < c < u1


def detect(f: pd.DataFrame) -> tuple[pd.DataFrame, dict, set]:
    o, h, l, c = (f[k].to_numpy() for k in ("open", "high", "low", "close"))
    u2, u1, l1, l2 = (f[k].to_numpy() for k in ("u2", "u1", "l1", "l2"))
    tv, er, bar_no = f["tvwap"].to_numpy(), f["er_h1"].to_numpy(), f["bar_no"].to_numpy()
    ny_open, tday, sess_last = f["ny_open_hour"].to_numpy(), f["tday"].to_numpy(), f["session_last"].to_numpy()
    n = len(f)
    counts = {k: {"long": 0, "short": 0} for k in (
        "raw_2sigma_closes", "eligible_2sigma_closes", "streaks", "reentries_within_2", "expired_no_reentry",
        "cancelled_opposite_2sigma", "excluded_not_range_regime", "excluded_ny_open_hour", "events")}
    counts.update({"no_entry_bar": 0, "rejected_risk_le_0": 0, "rejected_target_le_0": 0})
    events, reentry_bars = [], set()
    for d, name, band in SIDES:
        pending = None              # (X, streak_start, streak_len, touches_before)
        streak_start, streak_len, touches = None, 0, 0
        for i in range(n):
            if i == 0 or tday[i] != tday[i - 1]:                                           # item 14: new session
                if pending:
                    counts["expired_no_reentry"][name] += 1
                pending, streak_start, streak_len, touches = None, None, 0, 0
            if outside(c[i], u2[i], l2[i], d):
                counts["raw_2sigma_closes"][name] += 1
                if streak_start is not None and i > 0 and tday[i - 1] == tday[i] and \
                        outside(c[i - 1], u2[i - 1], l2[i - 1], d):
                    streak_len += 1
                else:
                    if streak_start is not None:
                        touches += 1
                    streak_start, streak_len = i, 1
                    counts["streaks"][name] += 1
                if bar_no[i] >= MIN_BAR:                                                   # item 17
                    counts["eligible_2sigma_closes"][name] += 1
                    pending = (i, streak_start, streak_len, touches)                       # item 6: latest X
                continue
            if pending is None:
                continue
            X, s0, slen, tch = pending
            if outside(c[i], u2[i], l2[i], -d):                                            # item 13
                counts["cancelled_opposite_2sigma"][name] += 1
                pending = None
                continue
            if i - X > WINDOW:                                                             # item 11
                counts["expired_no_reentry"][name] += 1
                pending = None
                continue
            if not inside1(c[i], u1[i], l1[i]):
                if i - X == WINDOW:
                    counts["expired_no_reentry"][name] += 1
                    pending = None
                continue
            R = i                                                                          # first reentry: item 10
            pending = None
            counts["reentries_within_2"][name] += 1
            reentry_bars.add(R)
            if not er[R] <= ER_MAX:                                                        # item 2 (NaN fails)
                counts["excluded_not_range_regime"][name] += 1
                continue
            if ny_open[R]:                                                                 # item 18
                counts["excluded_ny_open_hour"][name] += 1
                continue
            E = R + 1
            if E >= n or tday[E] != tday[R]:
                counts["no_entry_bar"] += 1
                continue
            entry = float(o[E])
            stop = float(h[s0:R + 1].max() if d == -1 else l[s0:R + 1].min())              # item 8
            risk = (stop - entry) if d == -1 else (entry - stop)                           # item 9
            if not risk > 0:
                counts["rejected_risk_le_0"] += 1
                continue
            target_r = d * (tv[R] - entry) / risk                                          # item 16
            if not target_r > 0:
                counts["rejected_target_le_0"] += 1
                continue
            counts["events"][name] += 1
            events.append(_event(f, name, d, band, X, s0, slen, tch, R, E, entry, stop, risk, target_r))
    ev = pd.DataFrame(events)
    if len(ev):
        ev = ev.sort_values(["reentry_index", "direction"]).reset_index(drop=True)
    return ev, counts, reentry_bars


def _event(f, name, d, band, X, s0, slen, tch, R, E, entry, stop, risk, target_r) -> dict:
    fx, fr, fe = f.iloc[X], f.iloc[R], f.iloc[E]
    atr = fr["atr"]
    edge = fx["u2"] if d == -1 else fx["l2"]
    exp_span = f["expansion"].iloc[max(s0 - 1, 0):X + 1]
    return {
        "direction": name, "band": band, "streak_start_index": s0, "exhaustion_index": X, "reentry_index": R,
        "signal_index": R, "entry_index": E, "exhaustion_time": fx["time"], "reentry_time": fr["time"],
        "entry_time": fe["time"], "entry": entry, "stop": stop, "risk": risk, "risk_atr": risk / atr,
        "tvwap_at_reentry": fr["tvwap"], "u1": fr["u1"], "u2": fr["u2"], "l1": fr["l1"], "l2": fr["l2"],
        "target_r": target_r, "spread_px": fe["spread_px"], "spread_risk": fe["spread_px"] / risk,
        "spread_target": fe["spread_px"] / (target_r * risk),
        "exh_dist_sigma": -d * (fx["close"] - edge) / fx["tvwap_sd"], "exh_dist_atr": -d * (fx["close"] - edge) / fx["atr"],
        "streak_len": slen, "reentry_delay": R - X, "tvwap_slope": fr["tvwap_slope"],
        "sigma_atr": fr["tvwap_sd"] / atr, "er_h1": fr["er_h1"], "atr_pct": fr["atr_pct"],
        "vol_regime": fr["vol_regime"], "tv_ratio": fr["tv_ratio"], "session": fr["session"], "hour": int(fr["hour"]),
        "dow": fr["dow"], "close_tvwap_atr": abs(fr["close"] - fr["tvwap"]) / atr,
        "pdh_dist_atr": (fr["pdh"] - fr["close"]) / atr, "pdl_dist_atr": (fr["close"] - fr["pdl"]) / atr,
        "asia_high_dist_atr": (fr["asia_high"] - fr["close"]) / atr, "asia_low_dist_atr": (fr["close"] - fr["asia_low"]) / atr,
        "expansion_before": bool(exp_span.any()), "prior_touches_session": tch, "atr": atr,
        "month": fr["time"].strftime("%Y-%m"),
    }


def tvwap_race(f: pd.DataFrame, E: int, d: int, entry: float, risk: float) -> dict:
    """Primary outcome (preregistration 'Primary outcome', items 14–15): live causal TVWAP vs the −1R stop,
    within the session. During bar j the target level is TVWAP[j−1]."""
    o, h, l, c, tv = (f[k].to_numpy() for k in ("open", "high", "low", "close", "tvwap"))
    last = int(f["session_last"].iloc[E])
    stop = entry - d * risk
    for j in range(E, last + 1):
        level = tv[j - 1]
        if (o[j] >= level) if d == 1 else (o[j] <= level):                               # opens at/through target
            return {"tv_outcome": "hit", "tv_bars": j - E + 1, "tv_minutes": 15 * (j - E + 1),
                    "tv_realized_r": d * (o[j] - entry) / risk, "tv_outcome_r": d * (o[j] - entry) / risk}
        if (o[j] <= stop) if d == 1 else (o[j] >= stop):                                  # opens through stop
            return {"tv_outcome": "stop", "tv_bars": j - E + 1, "tv_minutes": 15 * (j - E + 1),
                    "tv_realized_r": np.nan, "tv_outcome_r": -1.0}
        hit = (h[j] >= level) if d == 1 else (l[j] <= level)
        stopped = (l[j] <= stop) if d == 1 else (h[j] >= stop)
        if hit and stopped:
            return {"tv_outcome": "ambiguous", "tv_bars": j - E + 1, "tv_minutes": 15 * (j - E + 1),
                    "tv_realized_r": np.nan, "tv_outcome_r": -1.0}                        # conservative for economics
        if hit:
            r = d * (level - entry) / risk
            return {"tv_outcome": "hit", "tv_bars": j - E + 1, "tv_minutes": 15 * (j - E + 1),
                    "tv_realized_r": r, "tv_outcome_r": r}
        if stopped:
            return {"tv_outcome": "stop", "tv_bars": j - E + 1, "tv_minutes": 15 * (j - E + 1),
                    "tv_realized_r": np.nan, "tv_outcome_r": -1.0}
    return {"tv_outcome": "session_end", "tv_bars": last - E + 1, "tv_minutes": 15 * (last - E + 1),
            "tv_realized_r": np.nan, "tv_outcome_r": d * (c[last] - entry) / risk}


RACE_MAP = {"hit": "win", "stop": "loss", "ambiguous": "ambiguous", "session_end": "none"}


def outcomes(f, E, d, entry, risk) -> dict:
    tr = tvwap_race(f, E, d, entry, risk)
    return {**tr, "r_tv": RACE_MAP[tr["tv_outcome"]], **h1.forward(f, E, d, entry, risk)}


def controls(f: pd.DataFrame, events: pd.DataFrame, reentry_bars: set) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(SEED)
    n = len(f)
    near = np.zeros(n, dtype=bool)
    for i in events["reentry_index"]:
        near[max(0, i - 8): i + 9] = True
    tday = f["tday"].to_numpy()
    ok = (~near) & (f["er_h1"].to_numpy() <= ER_MAX) & ~f["ny_open_hour"].to_numpy()
    ok &= (f["bar_no"].to_numpy() >= MIN_BAR) & np.r_[tday[1:] == tday[:-1], False]
    ok &= f["atr"].notna().to_numpy() & f["atr_pct"].notna().to_numpy()
    ok[list(reentry_bars)] = False
    idx = np.flatnonzero(ok)
    close, tv, atr = f["close"].to_numpy(), f["tvwap"].to_numpy(), f["atr"].to_numpy()
    pool = pd.DataFrame({"index": idx, "session": f["session"].to_numpy()[idx],
                         "atr_pct": f["atr_pct"].to_numpy()[idx], "side": np.sign(tv[idx] - close[idx]),
                         "dist": np.abs(close[idx] - tv[idx]) / atr[idx]})
    rows, stats = [], {"discarded_target_le_0": 0, "dist_relaxed_events": 0, "atr_relaxed_events": 0,
                       "events_without_controls": 0}
    for e in events.itertuples():
        d = 1 if e.direction == "long" else -1
        base = pool[(pool["session"] == e.session) & (pool["side"] == d)]
        by_atr = base[(base["atr_pct"] - e.atr_pct).abs() <= ATR_PCT_TOL]
        by_dist = by_atr[(by_atr["dist"] - e.close_tvwap_atr).abs() <= DIST_TOL]
        dist_relaxed, atr_relaxed = len(by_dist) < CONTROLS_PER_EVENT, False
        match = by_atr if dist_relaxed else by_dist
        if len(match) < CONTROLS_PER_EVENT:
            match, atr_relaxed = base, True
        stats["dist_relaxed_events"] += dist_relaxed
        stats["atr_relaxed_events"] += atr_relaxed
        if match.empty:
            stats["events_without_controls"] += 1
            continue
        for j in rng.choice(match["index"].to_numpy(), size=CONTROLS_PER_EVENT, replace=True):
            entry = float(f["open"].iloc[j + 1])
            risk = e.risk_atr * float(atr[j])
            target_r = d * (tv[j] - entry) / risk
            if not target_r > 0:
                stats["discarded_target_le_0"] += 1
                continue
            rows.append({"event_signal_index": e.signal_index, "signal_index": int(j), "direction": e.direction,
                         "session": e.session, "atr_pct": float(f["atr_pct"].iloc[j]), "event_atr_pct": e.atr_pct,
                         "dist": float(abs(close[j] - tv[j]) / atr[j]), "event_dist": e.close_tvwap_atr,
                         "dist_relaxed": dist_relaxed, "atr_relaxed": atr_relaxed, "risk_atr": e.risk_atr,
                         "target_r": target_r, "spread_risk": float(f["spread_px"].iloc[j + 1]) / risk,
                         "month": f["time"].iloc[j].strftime("%Y-%m"), **outcomes(f, j + 1, d, entry, risk)})
    return pd.DataFrame(rows), stats


def h4_gate(dev, f, events) -> dict:
    checks = {}
    ok = True
    for e in events.itertuples():
        d = 1 if e.direction == "long" else -1
        X, R, s0 = e.exhaustion_index, e.reentry_index, e.streak_start_index
        fx, fr = f.iloc[X], f.iloc[R]
        ok &= bool(outside(fx["close"], fx["u2"], fx["l2"], d))
        ok &= inside1(fr["close"], fr["u1"], fr["l1"]) and 1 <= R - X <= WINDOW
        ok &= f["tday"].iloc[s0] == f["tday"].iloc[R] == f["tday"].iloc[e.entry_index] and e.entry_index == R + 1
        ok &= f["bar_no"].iloc[X] >= MIN_BAR and fr["er_h1"] <= ER_MAX and not fr["ny_open_hour"]
        span = f.iloc[s0:R + 1]
        ok &= e.stop == (span["high"].max() if d == -1 else span["low"].min())
        ok &= all(outside(f["close"].iloc[k], f["u2"].iloc[k], f["l2"].iloc[k], d) for k in range(s0, X + 1))
    checks["h4_structure_causal"] = {"pass": bool(ok), "method": "X outside 2σ, R inside 1σ within 2 bars, same "
                                     "session, warm-up, ER ≤ 0.15 at R, not NY open hour, stop = extreme of "
                                     "streak start..R, entry = R+1"}
    cut = int(len(dev) * 0.7)
    fp = h4_features(h1.features(dev.iloc[:cut].reset_index(drop=True)))
    ep, _, _ = detect(fp)
    key = ["direction", "exhaustion_index", "reentry_index", "stop", "entry", "target_r"]
    inner = set(map(tuple, events[events["entry_index"] < cut][key].to_numpy()))
    prefix = set(map(tuple, ep[ep["entry_index"] < cut][key].to_numpy()))
    checks["h4_prefix_invariance"] = {"pass": bool(inner == prefix), "events_in_prefix": len(inner)}
    return checks


def main() -> None:
    dev = h1.load_dev()
    assert dev["time"].max() < h1.DEV_END
    base = h1.features(dev)
    gate = h1.quality_gate(dev, base)
    f = h4_features(base)
    events, counts, reentry_bars = detect(f)
    gate.update(h4_gate(dev, f, events))
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values() if isinstance(v, dict)) else "BLOCKED"
    (OUT / "data_quality.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("DATA QUALITY BLOCKED")
    out = [outcomes(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
           for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(out)], axis=1)
    ctrl, cstats = controls(f, events, reentry_bars)
    counts["controls"] = cstats
    events.to_csv(OUT / "h4_events_dev.csv", index=False)
    ctrl.to_csv(OUT / "h4_controls_dev.csv", index=False)
    (OUT / "h4_counts_dev.json").write_text(json.dumps(counts, indent=1) + "\n")
    print("gate", gate["result"], "events", len(events), "controls", len(ctrl))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()

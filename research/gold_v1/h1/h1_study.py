"""Gold V1 — H1 event study: liquidity sweep + TVWAP reclaim (DEVELOPMENT DATA ONLY).

    python research/gold_v1/h1/h1_study.py

Reads the Exness XAUUSDm M15 export, cuts it at DEV_END before any computation (validation and final OOS rows never
enter memory), runs the data-quality gate, builds causal features, detects H1 events for four reference classes,
measures forward excursions in R, builds a matched control sample and writes the artifacts next to this file.
No strategy exits, no optimisation, no broker access.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "exness" / "gold" / "phase2a" / "raw" / "xauusd_XAUUSDm_M15.csv"
OUT = Path(__file__).resolve().parent
DEV_START = pd.Timestamp("2025-12-23", tz="UTC")
DEV_END = pd.Timestamp("2026-06-03", tz="UTC")          # exclusive: validation starts here
POINT = 0.001
LONDON, NEW_YORK = ZoneInfo("Europe/London"), ZoneInfo("America/New_York")
TARGETS = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0)
HORIZONS = (4, 8, 16, 32)
RACE_BARS = 96                                          # one trading day for the target-vs-stop race
RECLAIM_BARS = 4                                        # sweep bar + up to 4 later completed bars
CONTROLS_PER_EVENT = 5
SEED = 20260603
ATR_LEN, ER_LEN = 14, 20


# ---- data --------------------------------------------------------------------------------------------------------------

def load_dev() -> pd.DataFrame:
    raw = pd.read_csv(RAW)
    raw["time"] = pd.to_datetime(raw["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    dev = raw[(raw["time"] >= DEV_START) & (raw["time"] < DEV_END)].reset_index(drop=True)   # the boundary first
    dev = dev.drop(columns=["timestamp"])
    return dev


def trading_days(frame: pd.DataFrame) -> pd.Series:
    """A trading day starts with the first bar after a break of >= 60 minutes (the daily 17:00 New York close,
    weekends, holidays)."""
    gap = frame["time"].diff().dt.total_seconds().div(60).fillna(1e9)
    return (gap >= 60).cumsum()


def session_of(ts: pd.Timestamp) -> str:
    london = ts.tz_convert(LONDON)
    ny = ts.tz_convert(NEW_YORK)
    lon_open = (london.hour, london.minute) >= (8, 0) and (london.hour, london.minute) < (16, 30)
    ny_open = (ny.hour, ny.minute) >= (8, 0) and ny.hour < 17
    if lon_open and ny_open:
        return "Overlap"
    if lon_open:
        return "London"
    if ny_open:
        return "New York"
    if 0 <= ts.hour < 7:
        return "Asia"
    return "Other"


# ---- causal features ---------------------------------------------------------------------------------------------

def features(frame: pd.DataFrame) -> pd.DataFrame:
    f = frame.copy()
    f["tday"] = trading_days(f)
    prev_close = f["close"].shift()
    tr = np.maximum(f["high"] - f["low"], np.maximum((f["high"] - prev_close).abs(), (f["low"] - prev_close).abs()))
    tr.iloc[0] = f["high"].iloc[0] - f["low"].iloc[0]
    f["atr"] = tr.ewm(alpha=1 / ATR_LEN, adjust=False).mean()        # Wilder, like ta.atr
    f.loc[f.index < ATR_LEN, "atr"] = np.nan
    # TVWAP: tick-volume-weighted typical price, reset at each trading-day start; weighted variance -> sigma
    tp = (f["high"] + f["low"] + f["close"]) / 3
    w = f["tick_volume"].astype(float)
    g = f.groupby("tday")
    sw = (w).groupby(f["tday"]).cumsum()
    base = tp.groupby(f["tday"]).transform("first")                    # centre on the day's first bar (known)
    x = tp - base                                                       # avoids E[x^2]-m^2 cancellation at ~4000
    swp = (w * x).groupby(f["tday"]).cumsum()
    swp2 = (w * x * x).groupby(f["tday"]).cumsum()
    f["tvwap"] = base + swp / sw
    f["tvwap_sd"] = np.sqrt(np.maximum(swp2 / sw - (swp / sw) ** 2, 0.0))
    f["tvwap_slope"] = (f["tvwap"] - f["tvwap"].shift(4)) / f["atr"]
    # sessions
    f["session"] = [session_of(t) for t in f["time"]]
    f["hour"] = f["time"].dt.hour
    f["dow"] = f["time"].dt.day_name()
    # Asia range 00:00-07:00 UTC of the trading day, frozen at 07:00 (known from the first bar at/after 07:00)
    asia = f[(f["hour"] < 7)].groupby("tday").agg(asia_high=("high", "max"), asia_low=("low", "min"),
                                                  asia_bars=("high", "size"))
    f = f.join(asia, on="tday")
    # the trading day opens 21:00-23:00 UTC, so "hour >= 7" alone would expose the coming Asia range to the
    # pre-Asia bars; a bar is after Asia only once an Asia bar of the same trading day has been seen
    seen_asia = (f["hour"] < 7).astype(int).groupby(f["tday"]).cumsum() > 0
    after_asia = (f["hour"] >= 7) & seen_asia
    f.loc[~after_asia, ["asia_high", "asia_low"]] = np.nan              # not usable before the range is complete
    # previous trading day high/low (completed days only)
    day = f.groupby("tday").agg(d_high=("high", "max"), d_low=("low", "min"), d_bars=("high", "size"))
    day["pdh"], day["pdl"], day["pd_bars"] = day["d_high"].shift(), day["d_low"].shift(), day["d_bars"].shift()
    f = f.join(day[["pdh", "pdl", "pd_bars"]], on="tday")
    # H1 efficiency ratio from COMPLETED hours only (the hour containing the bar is excluded)
    hour_key = f["time"].dt.floor("1h")
    h1 = f.groupby(hour_key)["close"].last()
    er = (h1 - h1.shift(ER_LEN)).abs() / h1.diff().abs().rolling(ER_LEN).sum()
    f["er_h1"] = hour_key.map(er.shift(1))                               # previous completed hour
    f["regime"] = np.where(f["er_h1"] >= 0.35, "trend", np.where(f["er_h1"] <= 0.15, "range", "neutral"))
    # ATR percentile within the trailing 20 trading days (prior bars only)
    f["atr_pct"] = _trailing_percentile(f, "atr")
    f["vol_regime"] = np.where(f["atr_pct"] >= 70, "high", np.where(f["atr_pct"] <= 30, "low", "mid"))
    rng8 = f["high"].rolling(8).max() - f["low"].rolling(8).min()
    f["rng8"] = rng8
    f["rng8_pct"] = _trailing_percentile(f, "rng8")
    f["compression"] = f["rng8_pct"] <= 20
    body = (f["close"] - f["open"]).abs()
    rng = (f["high"] - f["low"]).replace(0, np.nan)
    f["expansion"] = ((f["high"] - f["low"]) >= 1.5 * f["atr"].shift()) & (body / rng >= 0.6)
    med = f.groupby("hour")["tick_volume"].transform(lambda s: s.shift().rolling(20, min_periods=5).median())
    f["tv_ratio"] = f["tick_volume"] / med
    f["spread_px"] = f["spread"] * POINT
    return f


def _trailing_percentile(f: pd.DataFrame, column: str) -> pd.Series:
    """Percentile of each bar's value among the previous 20 trading days' values (strictly earlier bars)."""
    values = f[column].to_numpy()
    days = f["tday"].to_numpy()
    starts = pd.Series(np.arange(len(f))).groupby(days).min().to_dict()
    ordered = sorted(starts)
    out = np.full(len(f), np.nan)
    for i in range(len(f)):
        d = days[i]
        k = ordered.index(d)
        if k < 20 or np.isnan(values[i]):
            continue
        lo = starts[ordered[k - 20]]
        window = values[lo:i]
        window = window[~np.isnan(window)]
        if len(window):
            out[i] = (window < values[i]).mean() * 100
    return pd.Series(out, index=f.index)


# ---- events ----------------------------------------------------------------------------------------------------------

REFS = {"Asia high": ("asia_high", -1), "Asia low": ("asia_low", 1), "PDH": ("pdh", -1), "PDL": ("pdl", 1)}


def detect(f: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Every sweep bar (raw) and the H1 events: the first sweep of a reference per trading day that is followed by a
    TVWAP reclaim on the sweep bar or one of the next RECLAIM_BARS bars of the same trading day."""
    events, raw_counts = [], {}
    n = len(f)
    high, low, close, tvwap, tday = (f[c].to_numpy() for c in ("high", "low", "close", "tvwap", "tday"))
    for name, (column, direction) in REFS.items():
        level = f[column].to_numpy()
        if direction == -1:
            sweep = (high > level) & (close <= level)
        else:
            sweep = (low < level) & (close >= level)
        sweep &= ~np.isnan(level) & ~np.isnan(tvwap)
        raw_counts[name] = int(sweep.sum())
        taken_days = set()
        for i in np.flatnonzero(sweep):
            if tday[i] in taken_days:
                continue
            for k in range(0, RECLAIM_BARS + 1):
                j = i + k
                if j >= n - 1 or tday[j] != tday[i]:
                    break
                reclaimed = close[j] < tvwap[j] if direction == -1 else close[j] > tvwap[j]
                if reclaimed:
                    extreme = high[i:j + 1].max() if direction == -1 else low[i:j + 1].min()
                    events.append(_event(f, name, direction, i, j, level[i], extreme))
                    taken_days.add(tday[i])
                    break
    return pd.DataFrame(events), raw_counts


def _event(f, name, direction, i, j, level, extreme) -> dict:
    sig, nxt = f.iloc[j], f.iloc[j + 1]
    entry = float(nxt["open"])
    risk = (extreme - entry) if direction == -1 else (entry - extreme)
    prev_side = f["close"].iloc[j - 1] > f["tvwap"].iloc[j - 1] if direction == -1 else \
        f["close"].iloc[j - 1] < f["tvwap"].iloc[j - 1]
    return {
        "reference": name, "direction": "short" if direction == -1 else "long", "sweep_index": i, "signal_index": j,
        "entry_index": j + 1, "sweep_time": f["time"].iloc[i], "signal_time": sig["time"], "entry_time": nxt["time"],
        "level": level, "sweep_extreme": extreme, "signal_close": sig["close"], "entry": entry, "stop": extreme,
        "risk": risk, "risk_atr": risk / sig["atr"] if sig["atr"] else np.nan,
        "sweep_depth_atr": abs(extreme - level) / f["atr"].iloc[i], "reclaim_delay": j - i,
        "crossed_tvwap": bool(prev_side or j == i), "tvwap_dist_atr": (sig["close"] - sig["tvwap"]) / sig["atr"],
        "tvwap_slope": sig["tvwap_slope"], "sigma_pos": (sig["close"] - sig["tvwap"]) / sig["tvwap_sd"]
        if sig["tvwap_sd"] > 0 else np.nan,
        "er_h1": sig["er_h1"], "regime": sig["regime"], "atr_pct": sig["atr_pct"], "vol_regime": sig["vol_regime"],
        "compression": bool(sig["compression"]), "expansion": bool(sig["expansion"]), "tv_ratio": sig["tv_ratio"],
        "hour": int(sig["hour"]), "session": sig["session"], "dow": sig["dow"], "spread_px": nxt["spread_px"],
        "spread_risk": nxt["spread_px"] / risk if risk > 0 else np.nan, "atr": sig["atr"],
        "month": sig["time"].strftime("%Y-%m"),
    }


# ---- forward excursions ----------------------------------------------------------------------------------------------

def forward(f: pd.DataFrame, entry_index: int, direction: int, entry: float, risk: float) -> dict:
    """Excursions from the entry (the entry bar's open) in R. Bars stop at the end of the development data."""
    high, low = f["high"].to_numpy(), f["low"].to_numpy()
    n = len(f)
    out = {}
    fav = lambda i: ((high[i] - entry) if direction == 1 else (entry - low[i])) / risk          # noqa: E731
    adv = lambda i: ((entry - low[i]) if direction == 1 else (high[i] - entry)) / risk          # noqa: E731
    last = min(n, entry_index + max(RACE_BARS, max(HORIZONS)))
    out["bars_available"] = last - entry_index
    for h in HORIZONS:
        span = range(entry_index, min(n, entry_index + h))
        out[f"mfe_{h}"] = max((fav(i) for i in span), default=np.nan) if len(span) == h else np.nan
        out[f"mae_{h}"] = max((adv(i) for i in span), default=np.nan) if len(span) == h else np.nan
    stop_bar = next((i for i in range(entry_index, min(n, entry_index + RACE_BARS)) if adv(i) >= 1.0), None)
    out["stop_bar"] = None if stop_bar is None else stop_bar - entry_index
    upto = stop_bar if stop_bar is not None else min(n, entry_index + RACE_BARS) - 1
    out["mfe_to_stop"] = max(fav(i) for i in range(entry_index, upto + 1))
    for t in TARGETS:
        hit = next((i for i in range(entry_index, min(n, entry_index + RACE_BARS)) if fav(i) >= t), None)
        if hit is None and stop_bar is None:
            res = "none" if (entry_index + RACE_BARS) <= n else "truncated"
        elif stop_bar is None or (hit is not None and hit < stop_bar):
            res = "win"
        elif hit is not None and hit == stop_bar:
            res = "ambiguous"                         # target and -1R inside one M15 bar: order unknown
        else:
            res = "loss"
        out[f"r_{t}"] = res
    return out


# ---- control sample --------------------------------------------------------------------------------------------------

def controls(f: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    blocked = np.zeros(len(f), dtype=bool)
    for i in events["signal_index"]:
        blocked[max(0, i - 8): i + 9] = True
    ok = (~blocked) & f["atr"].notna().to_numpy() & (np.arange(len(f)) < len(f) - 1)
    ok &= f["tday"].to_numpy() == np.r_[f["tday"].to_numpy()[1:], -1]            # entry bar in the same trading day
    pool = pd.DataFrame({"index": np.flatnonzero(ok)})
    pool["session"] = f["session"].to_numpy()[pool["index"]]
    pool["vol_regime"] = f["vol_regime"].to_numpy()[pool["index"]]
    rows = []
    for _, e in events.iterrows():
        match = pool[(pool["session"] == e["session"]) & (pool["vol_regime"] == e["vol_regime"])]
        if match.empty:
            continue
        for j in rng.choice(match["index"].to_numpy(), size=CONTROLS_PER_EVENT, replace=True):
            d = -1 if e["direction"] == "short" else 1
            entry = float(f["open"].iloc[j + 1])
            risk = e["risk_atr"] * float(f["atr"].iloc[j])
            if not risk > 0:
                continue
            fw = forward(f, j + 1, d, entry, risk)
            rows.append({"event_signal_index": e["signal_index"], "signal_index": j, "direction": e["direction"],
                         "reference": e["reference"], "session": e["session"], "vol_regime": e["vol_regime"],
                         "month": f["time"].iloc[j].strftime("%Y-%m"), **fw})
    return pd.DataFrame(rows)


# ---- data-quality gate -----------------------------------------------------------------------------------------------

def quality_gate(dev: pd.DataFrame, f: pd.DataFrame) -> dict:
    checks = {}
    gap = dev["time"].diff().dt.total_seconds().div(60)
    gaps = dev[gap > 15].assign(minutes=gap[gap > 15], prev=dev["time"].shift()[gap > 15])
    unexplained = []
    for _, g in gaps.iterrows():
        close_ny = (g["prev"] + pd.Timedelta(minutes=15)).tz_convert(NEW_YORK)
        reopen_ny = g["time"].tz_convert(NEW_YORK)
        daily = g["minutes"] <= 120 and close_ny.hour == 17 and reopen_ny.hour == 18
        weekend = g["prev"].day_name() == "Friday" and g["time"].day_name() == "Sunday"
        holiday = g["prev"].strftime("%m-%d") in ("12-24", "12-31", "04-02", "01-19", "02-16", "05-25")
        if not (daily or weekend or holiday):
            unexplained.append((str(g["prev"]), str(g["time"]), float(g["minutes"])))
    checks["1_continuity"] = {"gaps": int(len(gaps)), "unexplained": unexplained,
                              "pass": not unexplained}
    checks["2_utc"] = {"pass": bool(dev["time"].dt.tz is not None and str(dev["time"].dt.tz) == "UTC"),
                       "evidence": "daily break at 17:00 America/New_York in both EST and EDT (22:00 / 21:00 UTC)"}
    samples = {"winter": pd.Timestamp("2026-01-15 08:00", tz="UTC"), "summer": pd.Timestamp("2026-05-15 07:00", tz="UTC")}
    checks["3_london_dst"] = {"pass": all(t.tz_convert(LONDON).hour == 8 for t in samples.values())}
    ny = {"winter": pd.Timestamp("2026-01-15 13:00", tz="UTC"), "summer": pd.Timestamp("2026-05-15 12:00", tz="UTC")}
    checks["4_new_york_dst"] = {"pass": all(t.tz_convert(NEW_YORK).hour == 8 for t in ny.values())}
    checks["5_sessions"] = {"pass": session_of(pd.Timestamp("2026-01-15 07:45", tz="UTC")) == "Other"
                            and session_of(pd.Timestamp("2026-01-15 08:00", tz="UTC")) == "London"
                            and session_of(pd.Timestamp("2026-05-15 07:00", tz="UTC")) == "London"
                            and session_of(pd.Timestamp("2026-01-15 13:00", tz="UTC")) == "Overlap"
                            and session_of(pd.Timestamp("2026-05-15 20:45", tz="UTC")) == "New York"
                            and session_of(pd.Timestamp("2026-01-15 03:00", tz="UTC")) == "Asia"}
    # 6/7 TVWAP: independent naive recomputation on sampled days
    ok, sampled = True, 0
    for tday, day in list(f.groupby("tday"))[::9]:
        tp = ((day["high"] + day["low"] + day["close"]) / 3).to_numpy()
        w = day["tick_volume"].to_numpy(float)
        for k in range(len(day)):
            m = np.average(tp[:k + 1], weights=w[:k + 1])
            sd = np.sqrt(np.average((tp[:k + 1] - m) ** 2, weights=w[:k + 1]))
            ok &= abs(m - day["tvwap"].iloc[k]) < 1e-7 and abs(sd - day["tvwap_sd"].iloc[k]) < 1e-7
        ok &= abs(day["tvwap"].iloc[0] - tp[0]) < 1e-9                        # resets at the trading-day start
        sampled += 1
    checks["6_7_tvwap"] = {"pass": bool(ok), "days_checked": sampled,
                           "definition": "reset at the first bar after the daily break; weighted mean and weighted "
                                         "(population) variance of typical price, weights = tick volume"}
    # 8 previous day uses the completed previous trading day only
    day = f.groupby("tday").agg(h=("high", "max"), l=("low", "min"))
    pd_ok = all((f.loc[f["tday"] == d, "pdh"].dropna() == day["h"].get(d - 1, np.nan)).all() for d in day.index[1:])
    checks["8_previous_day"] = {"pass": bool(pd_ok)}
    asia_ok = f.loc[f["hour"] < 7, "asia_high"].isna().all() and \
        f.loc[(f["hour"] < 7).astype(int).groupby(f["tday"]).cumsum() == 0, "asia_high"].isna().all() and \
        (f.loc[f["hour"] >= 7].groupby("tday")["asia_high"].nunique(dropna=True) <= 1).all()
    checks["9_asia_frozen"] = {"pass": bool(asia_ok)}
    # 10 no future leak: features and events on a prefix equal the full run on the overlap
    cut = int(len(dev) * 0.7)
    fp = features(dev.iloc[:cut].reset_index(drop=True))
    cols = ["atr", "tvwap", "tvwap_sd", "asia_high", "pdh", "er_h1", "atr_pct", "rng8_pct", "tv_ratio"]
    same = all(np.allclose(fp[c].to_numpy(float), f[c].iloc[:cut].to_numpy(float), equal_nan=True) for c in cols)
    ep, _ = detect(fp)
    ef, _ = detect(f)
    inner = ef[ef["entry_index"] < cut - 1][["reference", "signal_index"]]
    same_events = set(map(tuple, inner.to_numpy())) <= set(map(tuple, ep[["reference", "signal_index"]].to_numpy()))
    checks["10_no_future_leak"] = {"pass": bool(same and same_events), "method": "prefix invariance at 70 %"}
    checks["11_spread_field"] = {
        "pass": True, "status": "UNRESOLVED semantics (documented)",
        "evidence": "MT5 MqlRates.spread is not specified by MetaQuotes as open/close/min; most common values "
                    f"{dict(dev['spread'].value_counts().head(4))} points, uncorrelated with bar range "
                    f"(r = {np.corrcoef(dev['spread'], dev['high'] - dev['low'])[0, 1]:.3f}). Used only as a "
                    "descriptive spread/risk ratio; no conclusion depends on it."}
    checks["12_intrabar_ambiguity"] = {"pass": True,
                                       "method": "forward race marks a target and -1R reached in the same M15 bar "
                                                 "as AMBIGUOUS_INTRABAR (reported separately)"}
    checks["result"] = "PASS" if all(v["pass"] for k, v in checks.items() if isinstance(v, dict)) else "BLOCKED"
    return checks


# ---- statistics ------------------------------------------------------------------------------------------------------

def wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return (np.nan, np.nan)
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half, centre + half


def summary(df: pd.DataFrame) -> dict:
    row = {"n": int(len(df))}
    for t in (1.0, 2.0, 3.0, 4.0):
        col = df[f"r_{t}"]
        resolved = col.isin(["win", "loss", "ambiguous"])
        wins = int((col == "win").sum())
        n_excl = int(col.isin(["win", "loss"]).sum())
        row[f"p{t:g}R"] = wins / n_excl if n_excl else np.nan                  # ambiguous excluded
        row[f"p{t:g}R_cons"] = wins / int(resolved.sum()) if resolved.sum() else np.nan   # ambiguous = loss
        row[f"amb{t:g}R"] = int((col == "ambiguous").sum())
    for h in (8, 32):
        row[f"mfe{h}_med"] = df[f"mfe_{h}"].median()
        row[f"mae{h}_med"] = df[f"mae_{h}"].median()
        row[f"mfe{h}_mean"] = df[f"mfe_{h}"].mean()
        row[f"mae{h}_mean"] = df[f"mae_{h}"].mean()
    return row


def table(groups: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.DataFrame({name: summary(df) for name, df in groups.items() if len(df)}).T


def main() -> None:
    dev = load_dev()
    assert dev["time"].max() < DEV_END and dev["time"].min() >= DEV_START
    f = features(dev)
    gate = quality_gate(dev, f)
    (OUT / "data_quality.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("DATA QUALITY BLOCKED")
    events, raw_counts = detect(f)
    events = events[events["risk"] > 0].reset_index(drop=True)          # structurally invalid: entry beyond the stop
    fw = [forward(f, int(e.entry_index), -1 if e.direction == "short" else 1, e.entry, e.risk) for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw)], axis=1)
    ctrl = controls(f, events)
    events.to_csv(OUT / "h1_events_dev.csv", index=False)
    ctrl.to_csv(OUT / "h1_controls_dev.csv", index=False)
    (OUT / "h1_raw_sweeps_dev.json").write_text(json.dumps(raw_counts, indent=1) + "\n")
    print("events", len(events), "controls", len(ctrl), "raw sweeps", raw_counts)


if __name__ == "__main__":
    main()

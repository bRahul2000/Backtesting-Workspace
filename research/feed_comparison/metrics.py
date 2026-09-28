"""Pure comparison metrics for two candle feeds of one market (no I/O).

Every feed is a frame with a UTC ``timestamp`` column and open/high/low/close/
volume. Indicators and events are computed on each feed's OWN series; the two
feeds only meet when candles with the identical UTC timestamp are compared.
Nothing is forward-filled, interpolated or fabricated.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd

from strategies.pine_indicators import ATR as PineATR, EMA as PineEMA
from ui.tradingview_mode.indicators import calculate_indicator

from . import thresholds as TH

OHLC = ("open", "high", "low", "close")
PERCENTILES = (5, 25, 75, 95, 99)


class FeedError(ValueError):
    """A feed that cannot be compared as given."""


# ---------------------------------------------------------------------------
# Feed validation and matching
# ---------------------------------------------------------------------------

def validate_feed(frame: pd.DataFrame, seconds: int, name: str) -> pd.DataFrame:
    """UTC, on the timeframe grid, strictly increasing, no duplicates, sane OHLC."""
    missing = [c for c in ("timestamp", *OHLC, "volume") if c not in frame.columns]
    if missing:
        raise FeedError(f"{name}: missing column(s) {missing}.")
    ts = frame["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(ts) or ts.dt.tz is None or str(ts.dt.tz) != "UTC":
        raise FeedError(f"{name}: timestamps must be UTC.")
    if ts.duplicated().any():
        raise FeedError(f"{name}: {int(ts.duplicated().sum())} duplicate timestamp(s).")
    epoch = epoch_seconds(ts)
    if len(epoch) > 1 and np.any(np.diff(epoch) <= 0):
        raise FeedError(f"{name}: timestamps must be strictly increasing.")
    if np.any(epoch % seconds):
        raise FeedError(f"{name}: timestamps not aligned to the {seconds}s grid.")
    values = frame[list(OHLC)].to_numpy(dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise FeedError(f"{name}: prices must be finite and positive.")
    if np.any(frame["high"] < frame[["open", "close"]].max(axis=1)) or np.any(frame["low"] > frame[["open", "close"]].min(axis=1)):
        raise FeedError(f"{name}: high/low inconsistent with open/close.")
    return frame.reset_index(drop=True)


def epoch_seconds(ts: pd.Series) -> np.ndarray:
    return ts.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[s]").astype(np.int64)


@dataclass(frozen=True)
class Matched:
    """Candles present in both feeds at the identical UTC timestamp."""

    frame: pd.DataFrame          # timestamp, b_open..b_volume, e_open..e_volume
    coverage: dict


def match(binance: pd.DataFrame, exness: pd.DataFrame, seconds: int) -> Matched:
    """Inner join on timestamp inside the overlapping window. No fill, no interpolation."""
    if binance.empty or exness.empty:
        raise FeedError("both feeds need candles.")
    start = max(binance["timestamp"].iloc[0], exness["timestamp"].iloc[0])
    end = min(binance["timestamp"].iloc[-1], exness["timestamp"].iloc[-1])
    if start > end:
        raise FeedError("the feeds do not overlap in time.")
    b = binance[(binance["timestamp"] >= start) & (binance["timestamp"] <= end)]
    e = exness[(exness["timestamp"] >= start) & (exness["timestamp"] <= end)]
    joined = b.add_prefix("b_").rename(columns={"b_timestamp": "timestamp"}).merge(
        e.add_prefix("e_").rename(columns={"e_timestamp": "timestamp"}), on="timestamp", how="inner")
    grid = int((end - start).total_seconds() // seconds) + 1
    coverage = {
        "overlap_start": start.isoformat(), "overlap_end": end.isoformat(), "grid_slots": grid,
        "binance_bars": int(len(b)), "exness_bars": int(len(e)), "matched_bars": int(len(joined)),
        "unmatched_binance": int(len(b) - len(joined)), "unmatched_exness": int(len(e) - len(joined)),
        "coverage_of_binance_pct": pct(len(joined), len(b)), "coverage_of_exness_pct": pct(len(joined), len(e)),
    }
    return Matched(joined.reset_index(drop=True), coverage)


def pct(part: float, whole: float) -> float | None:
    return None if not whole else round(100.0 * part / whole, 4)


# ---------------------------------------------------------------------------
# Distributions and correlation
# ---------------------------------------------------------------------------

def distribution(values: pd.Series | np.ndarray) -> dict:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if not len(array):
        return {"count": 0}
    out = {"count": int(len(array)), "mean": float(array.mean()), "median": float(np.median(array)),
           "std": float(array.std(ddof=1)) if len(array) > 1 else 0.0,
           "min": float(array.min()), "max": float(array.max())}
    out.update({f"p{p}": float(np.percentile(array, p)) for p in PERCENTILES})
    return out


def price_offsets(m: pd.DataFrame) -> dict:
    """Binance - Exness per field, absolute and relative (% of the Exness price)."""
    return {field: {"absolute": distribution(m[f"b_{field}"] - m[f"e_{field}"]),
                    "relative_pct": distribution((m[f"b_{field}"] - m[f"e_{field}"]) / m[f"e_{field}"] * 100.0)}
            for field in OHLC}


def spearman(a: pd.Series, b: pd.Series) -> float | None:
    """Spearman rank correlation (Pearson of average ranks; no SciPy needed)."""
    if len(a) < 3:
        return None
    return _finite(a.rank().corr(b.rank()))


def _finite(value) -> float | None:
    return None if value is None or not math.isfinite(value) else float(value)


def return_correlations(m: pd.DataFrame, seconds: int, horizons: tuple[int, ...] = (1, 3, 5)) -> dict:
    """k-bar log returns, only where both the candle and the one k bars earlier
    (by time) exist in BOTH feeds. Returns over data gaps are never formed."""
    indexed = m.set_index("timestamp")
    out = {}
    for k in horizons:
        earlier = indexed.index - pd.Timedelta(seconds=k * seconds)
        present = earlier.isin(indexed.index)
        now = indexed[present]
        before = indexed.loc[earlier[present]]
        rb = np.log(now["b_close"].to_numpy() / before["b_close"].to_numpy())
        re = np.log(now["e_close"].to_numpy() / before["e_close"].to_numpy())
        sb, se = pd.Series(rb), pd.Series(re)
        out[f"{k}_bar"] = {"pairs": int(len(rb)), "pearson": _finite(sb.corr(se)) if len(rb) > 2 else None,
                           "spearman": spearman(sb, se),
                           "sign_agreement_pct": pct(int(np.sum(np.sign(rb) == np.sign(re))), len(rb))}
    return out


def lag_alignment(m: pd.DataFrame, seconds: int, lags: tuple[int, ...] = (-3, -2, -1, 0, 1, 2, 3)) -> dict:
    """Time-alignment check: correlation of Binance 1-bar returns with Exness
    1-bar returns shifted by `lag` bars. Correctly aligned UTC feeds peak at 0;
    a timestamp offset in either feed would move the peak."""
    def returns(prefix: str) -> pd.Series:
        indexed = m.set_index("timestamp")[f"{prefix}_close"]
        full = indexed.reindex(pd.date_range(indexed.index[0], indexed.index[-1], freq=f"{seconds}s"))
        return np.log(full / full.shift(1))
    rb, re = returns("b"), returns("e")
    out = {str(lag): _finite(rb.corr(re.shift(-lag))) for lag in lags}
    best = max(out, key=lambda k: out[k] if out[k] is not None else -2)
    return {"correlation_by_lag_bars": out, "peak_lag_bars": int(best)}


# ---------------------------------------------------------------------------
# Candles: direction, shape, levels
# ---------------------------------------------------------------------------

def direction(open_: pd.Series, close: pd.Series, digits: int) -> np.ndarray:
    """+1 bull, -1 bear, 0 flat (close == open at the feed's own precision)."""
    delta = close.round(digits).to_numpy() - open_.round(digits).to_numpy()
    tolerance = 0.5 * 10.0 ** -digits
    return np.where(delta > tolerance, 1, np.where(delta < -tolerance, -1, 0))


def direction_agreement(m: pd.DataFrame, digits_b: int, digits_e: int) -> dict:
    db, de = direction(m["b_open"], m["b_close"], digits_b), direction(m["e_open"], m["e_close"], digits_e)
    names = {1: "bull", -1: "bear", 0: "flat"}
    confusion = {f"binance_{names[a]}__exness_{names[b]}": int(np.sum((db == a) & (de == b)))
                 for a in (1, -1, 0) for b in (1, -1, 0)}
    n = len(m)
    both_directional = (db != 0) & (de != 0)
    return {
        "matched": n, "same_pct": pct(int(np.sum(db == de)), n),
        "opposite_pct": pct(int(np.sum(db * de == -1)), n),
        "flat_disagreement_pct": pct(int(np.sum((db != de) & ((db == 0) | (de == 0)))), n),
        "same_pct_excluding_flats": pct(int(np.sum((db == de) & both_directional)), int(np.sum(both_directional))),
        "confusion": confusion,
    }, db, de


def shape(frame_prefix: str, m: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (m[f"{frame_prefix}_{f}"] for f in OHLC)
    rng = (h - l).replace(0.0, np.nan)   # a zero-range candle has no shape
    return pd.DataFrame({"body": (c - o).abs() / rng * 100, "upper": (h - np.maximum(o, c)) / rng * 100,
                         "lower": (np.minimum(o, c) - l) / rng * 100, "range": h - l})


def shape_similarity(m: pd.DataFrame) -> dict:
    sb, se = shape("b", m), shape("e", m)
    out = {}
    for part in ("body", "upper", "lower"):
        diff = (sb[part] - se[part]).abs()
        out[f"{part}_pct_abs_diff"] = {"median": _q(diff, 50), "p95": _q(diff, 95)}
    ratio = sb["range"] / se["range"].replace(0.0, np.nan)
    out["range_ratio_binance_over_exness"] = {"median": _q(ratio, 50), "p5": _q(ratio, 5), "p95": _q(ratio, 95)}
    out["range_correlation"] = _finite(sb["range"].corr(se["range"]))
    out["zero_range_candles"] = {"binance": int((m["b_high"] == m["b_low"]).sum()), "exness": int((m["e_high"] == m["e_low"]).sum())}
    return out


def _q(series: pd.Series, q: float) -> float | None:
    values = series.to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    return float(np.percentile(values, q)) if len(values) else None


def level_agreement(m: pd.DataFrame, atr_e: pd.Series) -> dict:
    """High/low/range differences: raw, % of Exness price, ATR-normalized, and
    basis-adjusted (excursion from each feed's own open, so the constant price
    offset between the two instruments does not count as disagreement)."""
    out = {}
    atr = atr_e.replace(0.0, np.nan)
    series = {
        "high": m["b_high"] - m["e_high"], "low": m["b_low"] - m["e_low"],
        "range": (m["b_high"] - m["b_low"]) - (m["e_high"] - m["e_low"]),
        "high_excursion": (m["b_high"] - m["b_open"]) - (m["e_high"] - m["e_open"]),
        "low_excursion": (m["b_open"] - m["b_low"]) - (m["e_open"] - m["e_low"]),
    }
    base = {"high": m["e_high"], "low": m["e_low"], "range": m["e_close"], "high_excursion": m["e_close"],
            "low_excursion": m["e_close"]}
    for name, diff in series.items():
        out[name] = {"abs_median": _q(diff.abs(), 50), "abs_p95": _q(diff.abs(), 95),
                     "pct_median": _q((diff / base[name]).abs() * 100, 50), "pct_p95": _q((diff / base[name]).abs() * 100, 95),
                     "atr_median": _q((diff / atr).abs(), 50), "atr_p95": _q((diff / atr).abs(), 95)}
    return out


# ---------------------------------------------------------------------------
# Indicators (the strategies' own Pine implementations; VWAP from the chart module)
# ---------------------------------------------------------------------------

def pine_ema(close: pd.Series, length: int) -> pd.Series:
    ema = PineEMA(length)
    values = [ema.update(float(price)) for price in close]
    out = pd.Series(values, index=close.index, dtype=float)
    out.iloc[: length - 1] = np.nan   # warm-up: not yet a meaningful EMA
    return out


def pine_atr(frame: pd.DataFrame, length: int = TH.ATR_LENGTH) -> pd.Series:
    atr = PineATR(length)
    values = [atr.update(SimpleNamespace(high=h, low=l, close=c))
              for h, l, c in zip(frame["high"].astype(float), frame["low"].astype(float), frame["close"].astype(float))]
    return pd.Series([np.nan if v is None else v for v in values], index=frame.index, dtype=float)


def vwap(frame: pd.DataFrame) -> pd.Series:
    """Session VWAP with the daily UTC reset used by the TradingView chart."""
    return calculate_indicator(frame, "vwap", {})["value"]


def with_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for length in TH.EMA_LENGTHS:
        out[f"ema{length}"] = pine_ema(out["close"], length)
    out["atr"] = pine_atr(out)
    out["vwap"] = vwap(out)
    return out


# ---------------------------------------------------------------------------
# Events (each on its own feed)
# ---------------------------------------------------------------------------

def onset(condition: pd.Series) -> pd.Series:
    """True where the condition starts (false or undefined on the previous candle)."""
    condition = condition.fillna(False).astype(bool)
    return condition & ~condition.shift(1, fill_value=False)


def swings(frame: pd.DataFrame, window: int) -> tuple[pd.Series, pd.Series]:
    """Fractal swings: the high is strictly above the `window` candles on each side
    (and the low strictly below). Needs `window` later candles to confirm."""
    high, low = frame["high"], frame["low"]
    left_h = high.shift(1).rolling(window).max()
    right_h = high[::-1].shift(1).rolling(window).max()[::-1]
    left_l = low.shift(1).rolling(window).min()
    right_l = low[::-1].shift(1).rolling(window).min()[::-1]
    return (high > left_h) & (high > right_h), (low < left_l) & (low < right_l)


def breakouts(frame: pd.DataFrame, n: int, basis: str = "close") -> tuple[pd.Series, pd.Series]:
    """Onset of breaking the previous n-candle high (up) / low (down).
    basis 'close': the close breaks the level; 'wick': the high/low trades through it."""
    prior_high = frame["high"].shift(1).rolling(n).max()
    prior_low = frame["low"].shift(1).rolling(n).min()
    up_price = frame["close"] if basis == "close" else frame["high"]
    down_price = frame["close"] if basis == "close" else frame["low"]
    return onset(up_price > prior_high), onset(down_price < prior_low)


def crosses(price: pd.Series, line: pd.Series) -> tuple[pd.Series, pd.Series]:
    above = price > line
    valid = line.notna() & line.shift(1).notna()
    return onset(above) & valid, onset(~above & line.notna()) & valid


def atr_expansion(atr: pd.Series) -> pd.Series:
    median = atr.shift(1).rolling(TH.ATR_EXPANSION_MEDIAN_BARS).median()
    return onset((atr > median) & median.notna())


def proxy_events(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """The neutral signal proxies A-G plus the structure events, all on one feed."""
    up20, down20 = breakouts(frame, 20, "close")
    ema_up, ema_down = crosses(frame["close"], frame["ema20"])
    vwap_up, vwap_down = crosses(frame["close"], frame["vwap"])
    events = {
        "A_close_cross_above_ema20": ema_up, "B_close_cross_below_ema20": ema_down,
        "C_close_moves_above_vwap": vwap_up, "D_close_moves_below_vwap": vwap_down,
        "E_20bar_breakout_up": up20, "F_20bar_breakout_down": down20,
        "G_atr_expansion": atr_expansion(frame["atr"]),
    }
    for n in TH.BREAKOUT_NS:
        for basis in ("close", "wick"):
            up, down = breakouts(frame, n, basis)
            events[f"breakout_{basis}_{n}_up"] = up
            events[f"breakout_{basis}_{n}_down"] = down
    for window in TH.SWING_WINDOWS:
        high, low = swings(frame, window)
        events[f"swing_{window}_high"] = high
        events[f"swing_{window}_low"] = low
    return events


def event_times(frame: pd.DataFrame, flags: pd.Series, allowed: np.ndarray) -> np.ndarray:
    """Epoch seconds of flagged candles, restricted to the matched timestamps."""
    times = epoch_seconds(frame["timestamp"])[flags.to_numpy(dtype=bool)]
    return times[np.isin(times, allowed)]


def match_events(b: np.ndarray, e: np.ndarray, seconds: int, tolerance_bars: int = 1) -> dict:
    """One-to-one event matching: identical timestamps first, then remaining events
    at most `tolerance_bars` apart, nearest first. See thresholds.py."""
    b, e = np.unique(b), np.unique(e)
    exact = np.intersect1d(b, e)
    rest_b = np.setdiff1d(b, exact)
    rest_e = np.setdiff1d(e, exact)
    tol = tolerance_bars * seconds
    candidates = []
    j = 0
    for tb in rest_b:
        while j < len(rest_e) and rest_e[j] < tb - tol:
            j += 1
        k = j
        while k < len(rest_e) and rest_e[k] <= tb + tol:
            candidates.append((abs(int(rest_e[k]) - int(tb)), int(tb), int(rest_e[k])))
            k += 1
    used_b, used_e, offsets = set(), set(), Counter()
    for dt, tb, te in sorted(candidates):
        if tb in used_b or te in used_e:
            continue
        used_b.add(tb)
        used_e.add(te)
        offsets[(te - tb) // seconds] += 1
    near = len(used_b)
    matched = len(exact) + near
    b_only, e_only = len(b) - matched, len(e) - matched
    return {
        "binance_events": int(len(b)), "exness_events": int(len(e)), "same_bar": int(len(exact)),
        "within_tolerance": int(matched), "binance_only": int(b_only), "exness_only": int(e_only),
        "agreement_same_bar_pct": pct(len(exact), len(b) + len(e) - len(exact)),
        "agreement_tolerance_pct": pct(matched, matched + b_only + e_only),
        "offset_bars_exness_minus_binance": {str(k): v for k, v in sorted(offsets.items())},
        "_binance_only_times": sorted(set(map(int, b)) - set(map(int, exact)) - used_b),
        "_exness_only_times": sorted(set(map(int, e)) - set(map(int, exact)) - used_e),
    }


def pooled(*results: dict) -> dict:
    """Combine event matches of several event types (e.g. up + down)."""
    keys = ("binance_events", "exness_events", "same_bar", "within_tolerance", "binance_only", "exness_only")
    total = {k: sum(r[k] for r in results) for k in keys}
    total["agreement_same_bar_pct"] = pct(total["same_bar"], total["binance_events"] + total["exness_events"] - total["same_bar"])
    total["agreement_tolerance_pct"] = pct(total["within_tolerance"],
                                           total["within_tolerance"] + total["binance_only"] + total["exness_only"])
    return total


# ---------------------------------------------------------------------------
# Indicator comparisons on matched candles
# ---------------------------------------------------------------------------

def aligned(frame: pd.DataFrame, column: str, timestamps: pd.Series) -> pd.Series:
    return frame.set_index("timestamp")[column].reindex(timestamps).reset_index(drop=True)


def atr_comparison(ib: pd.DataFrame, ie: pd.DataFrame, ts: pd.Series) -> dict:
    ab, ae = aligned(ib, "atr", ts), aligned(ie, "atr", ts)
    ok = ab.notna() & ae.notna() & (ae > 0)
    diff = ((ab - ae) / ae * 100)[ok]
    return {"pairs": int(ok.sum()), "correlation": _finite(ab[ok].corr(ae[ok])),
            "median_pct_diff": _q(diff, 50), "median_abs_pct_diff": _q(diff.abs(), 50), "p95_abs_pct_diff": _q(diff.abs(), 95)}


def ema_comparison(ib: pd.DataFrame, ie: pd.DataFrame, ts: pd.Series) -> dict:
    out = {}
    atr = aligned(ie, "atr", ts).replace(0.0, np.nan)
    cb, ce = aligned(ib, "close", ts), aligned(ie, "close", ts)
    for length in TH.EMA_LENGTHS:
        eb, ee = aligned(ib, f"ema{length}", ts), aligned(ie, f"ema{length}", ts)
        ok = eb.notna() & ee.notna() & atr.notna()
        level = ((eb - ee) / atr)[ok]
        # Close-to-EMA distance in ATR units: invariant to the constant basis between instruments.
        position = (((cb - eb) - (ce - ee)) / atr)[ok]
        sb, se = np.sign(eb.diff()), np.sign(ee.diff())
        slope_ok = ok & sb.notna() & se.notna()
        side_b, side_e = np.sign(cb - eb), np.sign(ce - ee)
        out[f"ema{length}"] = {
            "pairs": int(ok.sum()),
            "level_diff_atr": {"median": _q(level, 50), "abs_median": _q(level.abs(), 50), "abs_p95": _q(level.abs(), 95)},
            "close_distance_diff_atr": {"abs_median": _q(position.abs(), 50), "abs_p95": _q(position.abs(), 95)},
            "slope_direction_agreement_pct": pct(int((sb[slope_ok] == se[slope_ok]).sum()), int(slope_ok.sum())),
            "close_side_agreement_pct": pct(int((side_b[ok] == side_e[ok]).sum()), int(ok.sum())),
        }
    return out


def vwap_comparison(ib: pd.DataFrame, ie: pd.DataFrame, ts: pd.Series) -> dict:
    vb, ve = aligned(ib, "vwap", ts), aligned(ie, "vwap", ts)
    cb, ce = aligned(ib, "close", ts), aligned(ie, "close", ts)
    atr = aligned(ie, "atr", ts).replace(0.0, np.nan)
    ok = vb.notna() & ve.notna()
    state_b, state_e = np.sign(cb - vb)[ok], np.sign(ce - ve)[ok]
    distance = (((cb - vb) - (ce - ve)) / atr)[ok]
    return {
        "volume_semantics": ("Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume "
                             "(price-change count), not traded quantity. The two VWAPs weight prices differently "
                             "and are NOT the same quantity; only the price-vs-VWAP state is compared."),
        "pairs": int(ok.sum()),
        "binance_vwap": distribution(vb[ok]), "exness_vwap": distribution(ve[ok]),
        "state_agreement_pct": pct(int((state_b == state_e).sum()), int(ok.sum())),
        "above_both": int(((state_b > 0) & (state_e > 0)).sum()), "below_both": int(((state_b < 0) & (state_e < 0)).sum()),
        "binance_above_exness_below": int(((state_b > 0) & (state_e < 0)).sum()),
        "binance_below_exness_above": int(((state_b < 0) & (state_e > 0)).sum()),
        "distance_diff_atr": {"abs_median": _q(distance.abs(), 50), "abs_p95": _q(distance.abs(), 95)},
    }


# ---------------------------------------------------------------------------
# Time-of-day / weekday breakdowns and outliers
# ---------------------------------------------------------------------------

def grouped_summary(m: pd.DataFrame, db: np.ndarray, de: np.ndarray, breakout_miss: np.ndarray,
                    breakout_any: np.ndarray, key: pd.Series) -> list[dict]:
    frame = pd.DataFrame({"key": key.to_numpy(), "same": db == de,
                          "close_diff": (m["b_close"] - m["e_close"]).to_numpy(),
                          "miss": breakout_miss, "any": breakout_any})
    rows = []
    for value, group in frame.groupby("key", sort=True):
        rows.append({"key": value if not isinstance(value, np.integer) else int(value), "matched_bars": int(len(group)),
                     "direction_agreement_pct": pct(int(group["same"].sum()), len(group)),
                     "median_close_diff": float(group["close_diff"].median()),
                     "median_abs_close_diff": float(group["close_diff"].abs().median()),
                     "breakout_events": int(group["any"].sum()), "breakout_disagreements": int(group["miss"].sum()),
                     "breakout_disagreement_pct": pct(int(group["miss"].sum()), int(group["any"].sum()))})
    return rows


def session_edges(m: pd.DataFrame, seconds: int, gap_hours: float = 12.0) -> dict:
    """Candles right after a market pause in the Exness series (e.g. weekend reopen)
    and right before one (e.g. Friday close), compared with all other candles."""
    t = m["timestamp"]
    gap_before = t.diff() > pd.Timedelta(hours=gap_hours)
    gap_after = (-t.diff(-1)) > pd.Timedelta(hours=gap_hours)
    return {"reopen_candles": gap_before, "pre_pause_candles": gap_after}


def outliers(m: pd.DataFrame, score: pd.Series, kind: str, count: int = TH.OUTLIERS_PER_KIND) -> list[dict]:
    order = score.abs().sort_values(ascending=False).index[:count]
    rows = []
    for i in order:
        if not np.isfinite(score.loc[i]):
            continue
        row = m.loc[i]
        rows.append({"kind": kind, "timestamp": row["timestamp"].isoformat(), "difference": float(score.loc[i]),
                     **{f"binance_{f}": float(row[f"b_{f}"]) for f in OHLC},
                     **{f"exness_{f}": float(row[f"e_{f}"]) for f in OHLC}})
    return rows

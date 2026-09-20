"""R2 — Exness BTCUSDm versus Bitstamp BTC/USD market-data comparison.

Quantifies feed divergence on the exact overlapping timestamps. It does not try
to make the feeds agree: they are different venues with different pricing bases
(Exness broker Bid quotes against Bitstamp last-traded prices), so a systematic
offset is an expected finding, not a defect.

Reuses services.exness_m15.align_price_feeds for the M15 join and difference
summary; everything added here is the material that routine does not cover
(H1, range/ATR relationships, discontinuity comparison, weekend behaviour and
the Bid-versus-last pricing-basis test).

Bitstamp publishes no native H1 series, so the H1 comparison aggregates
Bitstamp M15 into complete four-bar hours and compares that against the
broker-native Exness H1. That asymmetry is recorded in the report.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.fingerprints import sha256_file
from services.exness_m15 import align_price_feeds
from utils.data_validation import continuous_segments

ROOT = Path(__file__).resolve().parents[1]
EXNESS_M15 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"
EXNESS_H1 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_H1.csv"
BITSTAMP = ROOT / "data/btcusd_15m.csv"
REPORT_JSON = ROOT / "reports/validation/exness_btc_market_data_comparison.json"
REPORT_MD = ROOT / "reports/validation/exness_btc_market_data_comparison.md"

FIELDS = ("open", "high", "low", "close")


def load_exness(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp_utc"] = pd.to_datetime(frame.timestamp_utc, utc=True)
    return frame


def load_bitstamp() -> pd.DataFrame:
    frame = pd.read_csv(BITSTAMP)
    frame["timestamp"] = pd.to_datetime(frame.timestamp, utc=True)
    return frame


def aggregate_h1(m15: pd.DataFrame, *, stamp: str = "timestamp") -> pd.DataFrame:
    """Complete four-bar hours only; partial hours are dropped, never padded."""
    work = m15.copy()
    work["hour"] = work[stamp].dt.floor("h")
    grouped = work.groupby("hour").agg(
        bars=(stamp, "size"), open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"))
    complete = grouped.loc[grouped.bars == 4].drop(columns="bars").reset_index()
    return complete.rename(columns={"hour": stamp})


def _atr(frame: pd.DataFrame, high: str, low: str, close: str,
         segment: pd.Series, length: int = 14) -> pd.Series:
    previous = frame.groupby(segment)[close].shift(1)
    true_range = pd.concat([frame[high] - frame[low],
                            (frame[high] - previous).abs(),
                            (frame[low] - previous).abs()], axis=1).max(axis=1)
    return true_range.groupby(segment).transform(
        lambda s: s.rolling(length, min_periods=length).mean())


def _segment_profile(frame: pd.DataFrame, stamp: str, step_seconds: int) -> dict[str, Any]:
    segments = continuous_segments(frame.rename(columns={stamp: "timestamp"}),
                                   step_seconds=step_seconds)
    return {"candles": int(len(frame)), "continuous_segments": len(segments),
            "largest_segment_candles": max((s.candles for s in segments), default=0)}


def compare(exness: pd.DataFrame, bitstamp: pd.DataFrame, *, step_minutes: int,
            label: str) -> dict[str, Any]:
    """One timeframe's full divergence profile on the exact timestamp overlap."""
    step_seconds = step_minutes * 60
    lo = max(exness.timestamp_utc.min(), bitstamp.timestamp.min())
    hi = min(exness.timestamp_utc.max(), bitstamp.timestamp.max())
    left = exness.loc[exness.timestamp_utc.between(lo, hi)].reset_index(drop=True)
    right = bitstamp.loc[bitstamp.timestamp.between(lo, hi)].reset_index(drop=True)

    common, stats = align_price_feeds(left, right)
    step = pd.Timedelta(minutes=step_minutes)
    segment = common.timestamp.diff().ne(step).cumsum()
    adjacent = common.timestamp.diff().eq(step)

    # Range and ATR are scale descriptors, never strategy inputs here.
    common["range_exness"] = common.high_exness - common.low_exness
    common["range_bitstamp"] = common.high_bitstamp - common.low_bitstamp
    common["atr14_exness"] = _atr(common, "high_exness", "low_exness", "close_exness", segment)
    common["atr14_bitstamp"] = _atr(common, "high_bitstamp", "low_bitstamp", "close_bitstamp", segment)
    atr_ratio = (common.atr14_exness / common.atr14_bitstamp).replace([float("inf")], pd.NA).dropna()

    # align_price_feeds hardcodes a 15-minute adjacency step for its return and
    # ATR columns, so those are recomputed here at this timeframe's real step.
    exness_return = common.close_exness.pct_change().where(adjacent)
    bitstamp_return = common.close_bitstamp.pct_change().where(adjacent)
    pairs = exness_return.notna() & bitstamp_return.notna()
    return_correlation = (float(exness_return.corr(bitstamp_return))
                          if pairs.sum() >= 2 else None)

    # Pricing basis: Exness quotes Bid, Bitstamp reports last traded. A Bid feed
    # should sit systematically below a last/mid feed by roughly half the spread.
    signed = common.close_exness - common.close_bitstamp
    half_spread = common.spread_price / 2 if "spread_price" in common else None

    weekend = common.timestamp.dt.dayofweek >= 5
    result = {
        "timeframe": label,
        "overlap": {"start_utc": lo.isoformat(), "end_utc": hi.isoformat(),
                    "exness_candles_in_window": int(len(left)),
                    "bitstamp_candles_in_window": int(len(right))},
        "alignment": {
            "matched_candles": int(len(common)),
            "exness_only_timestamps": int(len(left) - len(common)),
            "bitstamp_only_timestamps": int(len(right) - len(common)),
            "matched_percent_of_exness": float(100 * len(common) / len(left)) if len(left) else None,
            "matched_percent_of_bitstamp": float(100 * len(common) / len(right)) if len(right) else None,
        },
        "correlation": {
            "close_level": stats["close_correlation"],
            "close_return": return_correlation,
            "high_low_range": float(common.range_exness.corr(common.range_bitstamp)),
            "atr14": float(common.atr14_exness.corr(common.atr14_bitstamp)),
        },
        "price_difference": {
            field: {**stats["absolute_difference_summary"][field],
                    # Recomputed at this timeframe's step, replacing the M15-only value.
                    "median_atr": float((common[f"{field}_difference_usd"].abs()
                                         / common.atr14_exness).replace(
                                             [float("inf")], pd.NA).dropna().median())}
            for field in FIELDS},
        "signed_close_difference_usd": {
            "mean": float(signed.mean()), "median": float(signed.median()),
            "p05": float(signed.quantile(.05)), "p95": float(signed.quantile(.95)),
            "share_negative_percent": float(100 * (signed < 0).mean()),
        },
        "range_and_atr": {
            "median_range_exness_usd": float(common.range_exness.median()),
            "median_range_bitstamp_usd": float(common.range_bitstamp.median()),
            "median_range_ratio": float((common.range_exness / common.range_bitstamp)
                                        .replace([float("inf")], pd.NA).dropna().median()),
            "median_atr14_exness_usd": float(common.atr14_exness.median()),
            "median_atr14_bitstamp_usd": float(common.atr14_bitstamp.median()),
            "median_atr14_ratio": float(atr_ratio.median()) if len(atr_ratio) else None,
        },
        "discontinuity": {
            "exness": _segment_profile(left, "timestamp_utc", step_seconds),
            "bitstamp": _segment_profile(right, "timestamp", step_seconds),
            "matched": _segment_profile(common, "timestamp", step_seconds),
        },
        "weekend": {
            "matched_weekend_candles": int(weekend.sum()),
            "weekend_share_percent": float(100 * weekend.mean()),
            "median_absolute_close_difference_weekend_usd":
                float(common.loc[weekend, "close_difference_usd"].abs().median()) if weekend.any() else None,
            "median_absolute_close_difference_weekday_usd":
                float(common.loc[~weekend, "close_difference_usd"].abs().median()),
            "note": "Both venues trade through the weekend; Exness pauses only briefly.",
        },
    }
    if half_spread is not None:
        result["pricing_basis"] = {
            "hypothesis": ("Exness candles are broker Bid quotes; Bitstamp reports last traded "
                           "price. A Bid feed should sit below a last/mid feed by roughly half "
                           "the quoted spread."),
            "median_signed_close_difference_usd": float(signed.median()),
            "median_half_spread_usd": float(half_spread.median()),
            "median_difference_plus_half_spread_usd": float((signed + half_spread).median()),
        }

    # Notable divergence periods: worst months by median absolute close difference.
    monthly = common.assign(month=common.timestamp.dt.strftime("%Y-%m")).groupby("month")
    months = monthly.apply(lambda g: pd.Series({
        "candles": len(g),
        "median_absolute_close_difference_usd": g.close_difference_usd.abs().median(),
        "p95_absolute_close_difference_usd": g.close_difference_usd.abs().quantile(.95),
        "median_close_difference_percent": g.close_difference_percent.median(),
    }), include_groups=False).reset_index()
    result["monthly"] = months.to_dict("records")
    result["notable_divergence_months"] = (
        months.nlargest(5, "median_absolute_close_difference_usd").to_dict("records"))
    return result


def build() -> dict[str, Any]:
    exness_m15 = load_exness(EXNESS_M15)
    exness_h1 = load_exness(EXNESS_H1)
    bitstamp_m15 = load_bitstamp()
    bitstamp_h1 = aggregate_h1(bitstamp_m15)

    report = {
        "phase": "R2 — Exness BTCUSDm vs Bitstamp BTC/USD market-data comparison",
        "purpose": ("Quantify feed divergence on exact overlapping timestamps. No attempt is "
                    "made to reconcile the feeds; they are different venues."),
        "sources": {
            "exness_m15": {"path": str(EXNESS_M15.relative_to(ROOT)), "sha256": sha256_file(EXNESS_M15)},
            "exness_h1": {"path": str(EXNESS_H1.relative_to(ROOT)), "sha256": sha256_file(EXNESS_H1)},
            "bitstamp_m15": {"path": str(BITSTAMP.relative_to(ROOT)), "sha256": sha256_file(BITSTAMP)},
            "bitstamp_h1": "derived: complete four-bar aggregation of Bitstamp M15 (no native H1 series exists)",
        },
        "timezone_basis": ("Both series are UTC. Exness server offset is 0 at capture "
                           "(btcusd_BTCUSDm_M15.csv.metadata.json), so no shift is applied."),
        "M15": compare(exness_m15, bitstamp_m15, step_minutes=15, label="M15"),
        "H1": compare(exness_h1, bitstamp_h1, step_minutes=60, label="H1"),
        "limitations": [
            "Exness candles are broker Bid quotes; Bitstamp reports last traded price. A systematic offset is expected.",
            "Bitstamp has no native H1 series; its H1 is aggregated from complete four-bar M15 groups.",
            "Exness volume is tick count, Bitstamp volume is traded BTC; the two are not comparable and volume is not compared.",
            "Exness real_volume is 0 throughout, so no true traded volume is available from the broker feed.",
            "ATR here is a descriptive 14-bar true-range mean reset across gaps, not a strategy input.",
        ],
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


if __name__ == "__main__":
    output = build()
    for label in ("M15", "H1"):
        block = output[label]
        align = block["alignment"]
        corr = block["correlation"]
        print(f"=== {label} ===")
        print(f"  overlap {block['overlap']['start_utc']} -> {block['overlap']['end_utc']}")
        print(f"  matched {align['matched_candles']:,} "
              f"({align['matched_percent_of_exness']:.2f}% of Exness, "
              f"{align['matched_percent_of_bitstamp']:.2f}% of Bitstamp); "
              f"exness-only {align['exness_only_timestamps']:,}, "
              f"bitstamp-only {align['bitstamp_only_timestamps']:,}")
        print(f"  corr level={corr['close_level']:.6f} return={corr['close_return']:.6f} "
              f"range={corr['high_low_range']:.6f} atr={corr['atr14']:.6f}")
        close = block["price_difference"]["close"]
        print(f"  |close diff| median ${close['median_usd']:.2f} p95 ${close['p95_usd']:.2f} "
              f"max ${close['maximum_usd']:.2f} ({close['median_percent']:.4f}% median)")
        signed = block["signed_close_difference_usd"]
        print(f"  signed close diff median ${signed['median']:+.2f} "
              f"({signed['share_negative_percent']:.1f}% negative)")
        print(f"  median ATR ratio {block['range_and_atr']['median_atr14_ratio']:.4f}")

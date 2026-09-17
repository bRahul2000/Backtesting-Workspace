"""Audit the real Exness MT5 Bid M15 export without changing source bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from services.history import CANONICAL_DATA_FILE
from utils.data_validation import continuous_segments, invalid_ohlcv_mask, missing_gaps


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/exness/raw/BTCUSDm_M15_202311090000_202609171715.csv"
PROCESSED = ROOT / "data/exness/processed/btcusdm_m15.csv"
REPORT = ROOT / "reports/broker/exness/native_validation"
COLUMNS = ("<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>",
           "<TICKVOL>", "<VOL>", "<SPREAD>")
STEP = pd.Timedelta(minutes=15)


def parse_mt5_m15(path: Path) -> tuple[pd.DataFrame, dict]:
    """Interpret Exness server wall time as UTC+0; never sort or repair source."""
    path = Path(path)
    raw = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    if tuple(raw.columns) != COLUMNS:
        raise ValueError(f"Unexpected MT5 M15 schema: {tuple(raw.columns)}")
    stamps = pd.to_datetime(raw["<DATE>"] + " " + raw["<TIME>"],
                            format="%Y.%m.%d %H:%M:%S", utc=True, errors="coerce")
    numbers = raw[list(COLUMNS[2:])].apply(pd.to_numeric, errors="coerce")
    frame = pd.DataFrame({"timestamp_utc": stamps,
                          "open": numbers["<OPEN>"], "high": numbers["<HIGH>"],
                          "low": numbers["<LOW>"], "close": numbers["<CLOSE>"],
                          "tick_volume": numbers["<TICKVOL>"],
                          "real_volume": numbers["<VOL>"],
                          "spread_points": numbers["<SPREAD>"]})
    frame["spread_price"] = frame.spread_points * .01
    check = frame.rename(columns={"timestamp_utc": "timestamp",
                                  "tick_volume": "volume"})
    invalid = invalid_ohlcv_mask(check)
    invalid |= frame[["real_volume", "spread_points"]].isna().any(axis=1)
    invalid |= (frame.real_volume < 0) | (frame.spread_points < 0)
    offgrid = stamps.isna() | (stamps.dt.minute % 15 != 0) | (stamps.dt.second != 0)
    audit = {"raw_rows": len(raw), "first_timestamp_utc": str(stamps.iloc[0]),
             "last_timestamp_utc": str(stamps.iloc[-1]),
             "duplicate_full_rows": int(raw.duplicated().sum()),
             "duplicate_timestamps": int(stamps.duplicated().sum()),
             "invalid_ohlc_rows": int(invalid.sum()),
             "off_grid_timestamps": int(offgrid.sum()),
             "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "source_file": path.name, "point_size": .01,
             "source_timezone": "Exness server UTC+0"}
    if stamps.isna().any() or not stamps.is_monotonic_increasing:
        raise ValueError("MT5 M15 timestamps are invalid or out of order.")
    if audit["duplicate_timestamps"] or audit["invalid_ohlc_rows"] or audit["off_grid_timestamps"]:
        raise ValueError(f"MT5 M15 audit failed: {audit}")
    gaps = missing_gaps(check)
    audit.update({"expected_intervals": len(frame) + sum(g.missing_candles for g in gaps),
                  "missing_intervals": sum(g.missing_candles for g in gaps),
                  "gap_count": len(gaps),
                  "largest_gap": max((g.missing_candles for g in gaps), default=0),
                  "segments": len(continuous_segments(check))})
    return frame, audit


def validate_tick_overlap(bars: pd.DataFrame, processed_dir: Path) -> tuple[dict, pd.DataFrame]:
    """Check all five reconstructed tick samples against MT5 Bid OHLC and bar min spread."""
    broker = bars.set_index("timestamp_utc")
    rows = []
    for bid_path in sorted(processed_dir.glob("btcusdm_s*_bid_15m_server_time.csv")):
        sample_id = bid_path.name.split("_")[1]
        bid = pd.read_csv(bid_path)
        bid["timestamp_utc"] = pd.to_datetime(bid.timestamp_server, format="mixed", utc=True)
        ticks = pd.read_csv(processed_dir / f"btcusdm_{sample_id}_ticks_server_time.csv",
                            usecols=["timestamp_server", "spread_price"])
        ticks["timestamp_utc"] = pd.to_datetime(ticks.timestamp_server, format="mixed", utc=True)
        minimum = ticks.groupby(ticks.timestamp_utc.dt.floor("15min")).spread_price.min()
        for candle in bid.itertuples(index=False):
            stamp = candle.timestamp_utc
            if stamp not in broker.index:
                continue
            historical = broker.loc[stamp]
            ohlc_match = all(getattr(candle, name) == historical[name]
                             for name in ("open", "high", "low", "close"))
            tick_min = float(minimum.loc[stamp])
            spread_match = abs(tick_min - historical.spread_price) < 1e-8
            rows.append({"sample_id": sample_id, "timestamp_utc": stamp,
                         "ohlc_exact_match": ohlc_match,
                         "bar_spread_price": historical.spread_price,
                         "tick_min_spread_price": tick_min,
                         "spread_min_match": spread_match})
    details = pd.DataFrame(rows)
    return ({"overlapping_candles": len(details),
             "exact_ohlc_matches": int(details.ohlc_exact_match.sum()),
             "ohlc_mismatches": int((~details.ohlc_exact_match).sum()),
             "spread_min_matches": int(details.spread_min_match.sum()),
             "spread_min_mismatches": int((~details.spread_min_match).sum())}, details)


def spread_history(bars: pd.DataFrame) -> pd.DataFrame:
    data = bars.copy()
    time = data.timestamp_utc
    data["year"] = time.dt.year.astype(str)
    data["month"] = time.dt.strftime("%Y-%m")
    data["utc_hour"] = time.dt.hour.astype(str)
    data["weekday"] = time.dt.day_name()
    rows = []
    for kind, groups in (("overall", [("all", data)]),
                         ("year", data.groupby("year")),
                         ("month", data.groupby("month")),
                         ("utc_hour", data.groupby("utc_hour")),
                         ("weekday", data.groupby("weekday"))):
        for label, group in groups:
            s = group.spread_price
            rows.append({"group_type": kind, "group": label, "candles": len(group),
                         "minimum": s.min(), "median": s.median(), "mean": s.mean(),
                         "p75": s.quantile(.75), "p90": s.quantile(.90),
                         "p95": s.quantile(.95), "p99": s.quantile(.99),
                         "maximum": s.max()})
    return pd.DataFrame(rows)


def align_price_feeds(exness: pd.DataFrame, bitstamp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Exact timestamp inner join; ATR and returns reset across source gaps."""
    left = exness.rename(columns={"timestamp_utc": "timestamp"})
    common = left.merge(bitstamp, on="timestamp", how="inner", suffixes=("_exness", "_bitstamp"))
    common = common.sort_values("timestamp").reset_index(drop=True)
    for field in ("open", "high", "low", "close"):
        common[f"{field}_difference_usd"] = common[f"{field}_exness"] - common[f"{field}_bitstamp"]
        common[f"{field}_difference_percent"] = (common[f"{field}_difference_usd"].abs() /
                                                   common[f"{field}_bitstamp"] * 100)
    # A trailing 14-bar true-range mean is a descriptive scale, not a strategy input.
    segment = common.timestamp.diff().ne(STEP).cumsum()
    previous_close = common.groupby(segment).close_exness.shift(1)
    tr = pd.concat([(common.high_exness - common.low_exness),
                    (common.high_exness - previous_close).abs(),
                    (common.low_exness - previous_close).abs()], axis=1).max(axis=1)
    common["exness_atr14_descriptor"] = tr.groupby(segment).transform(
        lambda s: s.rolling(14, min_periods=14).mean())
    for field in ("open", "high", "low", "close"):
        common[f"{field}_difference_atr"] = (common[f"{field}_difference_usd"].abs() /
                                               common.exness_atr14_descriptor)
    ex_only = len(exness) - len(common)
    bit_only = len(bitstamp) - len(common)
    adjacent = common.timestamp.diff().eq(STEP)
    ex_ret = common.close_exness.pct_change().where(adjacent)
    bit_ret = common.close_bitstamp.pct_change().where(adjacent)
    stats = {"common_candles": len(common), "exness_only_timestamps": ex_only,
             "bitstamp_only_timestamps": bit_only,
             "close_correlation": (common.close_exness.corr(common.close_bitstamp)
                                   if len(common) >= 2 else None),
             "return_correlation": (ex_ret.corr(bit_ret)
                                    if (ex_ret.notna() & bit_ret.notna()).sum() >= 2 else None),
             "median_absolute_close_difference_usd": common.close_difference_usd.abs().median(),
             "median_relative_close_difference_percent": common.close_difference_percent.median(),
             "absolute_difference_summary": {}}
    for field in ("open", "high", "low", "close"):
        diff = common[f"{field}_difference_usd"].abs()
        stats["absolute_difference_summary"][field] = {
            "median_usd": diff.median(), "mean_usd": diff.mean(),
            "p90_usd": diff.quantile(.90), "p95_usd": diff.quantile(.95),
            "maximum_usd": diff.max(),
            "median_percent": common[f"{field}_difference_percent"].median(),
            "median_atr": common[f"{field}_difference_atr"].median()}
    return common, stats


def build_data_audit(raw_path: Path = RAW, output_dir: Path = REPORT,
                     processed_path: Path = PROCESSED) -> dict:
    bars, audit = parse_mt5_m15(raw_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    bars.to_csv(processed_path, index=False)
    gaps = missing_gaps(bars.rename(columns={"timestamp_utc": "timestamp"}))
    pd.DataFrame([{"gap_start_utc": g.start, "gap_end_utc": g.end,
                   "missing_intervals": g.missing_candles} for g in gaps],
                 columns=["gap_start_utc", "gap_end_utc", "missing_intervals"]).to_csv(
                     output_dir.parent / "m15_data_gaps.csv", index=False)
    tick, tick_details = validate_tick_overlap(bars, processed_path.parent)
    tick_details.to_csv(output_dir / "tick_bar_validation.csv", index=False)
    spreads = spread_history(bars)
    spreads.to_csv(output_dir / "spread_history.csv", index=False)
    summary = {**audit, "tick_validation": tick,
               "spread_overall": spreads.loc[spreads.group_type == "overall"].iloc[0].to_dict()}
    (output_dir / "data_audit.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    lines = ["# Exness BTCUSDm MT5 Bid M15 data audit", "",
             f"Source: `{raw_path.name}`; SHA-256 `{audit['source_sha256']}`. Raw source unchanged.",
             "", f"{audit['raw_rows']:,} rows, {audit['first_timestamp_utc']} to {audit['last_timestamp_utc']}; "
             f"{audit['expected_intervals']:,} expected, {audit['missing_intervals']} missing across "
             f"{audit['gap_count']} gaps (largest {audit['largest_gap']}).",
             f"Duplicate full rows {audit['duplicate_full_rows']}; duplicate timestamps "
             f"{audit['duplicate_timestamps']}; invalid OHLC {audit['invalid_ohlc_rows']}; "
             f"off-grid timestamps {audit['off_grid_timestamps']}.",
             "", f"Tick cross-check: {tick['overlapping_candles']} overlapping M15 bars; "
             f"{tick['exact_ohlc_matches']} exact Bid OHLC matches, {tick['ohlc_mismatches']} mismatches; "
             f"{tick['spread_min_matches']} spread-minimum matches, "
             f"{tick['spread_min_mismatches']} mismatches.",
             "", "**MT5 bar SPREAD is a historical bar-level minimum spread descriptor, not the spread guaranteed at an execution tick.** `spread_price = spread_points × 0.01` for this 2-digit symbol. Bar spread may be used only as an optimistic lower-bound cost descriptor; tick-exact execution requires historical Bid/Ask quotes at the relevant times.",
             "", "No M15 candle was interpolated or forward-filled. Timestamps are Exness server UTC+0; the original CSV has no embedded offset.", ""]
    annual = spreads.loc[spreads.group_type == "year"]
    lines += ["## Historical minimum-spread changes", "",
              "| Year | Candles | Median $/BTC | Mean $/BTC | P95 $/BTC | Max $/BTC |",
              "|---|---:|---:|---:|---:|---:|"]
    for row in annual.itertuples(index=False):
        lines.append(f"| {row.group} | {row.candles:,} | {row.median:.2f} | "
                     f"{row.mean:.2f} | {row.p95:.2f} | {row.maximum:.2f} |")
    overlap_spread = tick_details.bar_spread_price
    lines += ["", f"The {len(overlap_spread)} tick-sample overlap bars have median "
              f"minimum spread ${overlap_spread.median():.2f}/BTC. "
              "The annual medians differ substantially, so the recent $10 tick-sample observation is not extended to earlier years.", ""]
    (output_dir / "data_audit.md").write_text("\n".join(lines))
    return summary


if __name__ == "__main__":
    print(json.dumps(build_data_audit(), indent=2, default=str))

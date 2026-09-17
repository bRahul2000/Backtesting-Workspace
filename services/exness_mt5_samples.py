"""Reconstruct separate MT5 BTCUSDm quote samples in broker-server wall time.

This research data path never supplies prices to the audited strategy engine.
The MT5 clock offset is unknown, so all timestamps here are explicitly server
time, and quote state is reset at each file and missing 15-minute interval.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from brokers.exness_standard_btcusdm import PROFILE, historical_spread_price
from services.exness_ticks import PROCESSED_DIR, RAW_DIR, REPORT_DIR, TickImportError, inspect_tick_source


TIMEZONE_STATUS = "EXNESS_MT5_SERVER_TIME_UNVERIFIED"
STEP = timedelta(minutes=15)
TICK_COLUMNS = ["sample_id", "source_row", "timestamp_raw", "timestamp_server",
                "bid_raw", "ask_raw", "bid", "ask", "bid_carried", "ask_carried",
                "update_type", "spread_price", "spread_pct", "spread_bps"]
BAR_COLUMNS = ["sample_id", "timestamp_server", "open", "high", "low", "close",
               "tick_count", "spread_median", "spread_mean", "spread_max"]


def _writer(path: Path, columns: list[str]):
    handle = path.open("w", newline="")
    writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    return handle, writer


def _clock(date_raw: str, time_raw: str) -> datetime:
    if not date_raw or not time_raw:
        raise ValueError("missing MT5 date or time")
    stamp = datetime.fromisoformat(f"{date_raw.replace('.', '-')}T{time_raw}")
    if stamp.tzinfo is not None:
        raise ValueError("expected offset-free MT5 broker-server timestamp")
    return stamp


def _quote(raw: str) -> float | None:
    if raw == "":
        return None
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("quote must be finite and positive")
    return value


def _bucket(stamp: datetime) -> datetime:
    return stamp.replace(minute=stamp.minute // 15 * 15, second=0, microsecond=0)


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        raise TickImportError("Sample contains no complete reconstructed Bid/Ask quotes.")
    ordered = sorted(values)

    def quantile(p: float) -> float:
        rank = (len(ordered) - 1) * p
        low, high = math.floor(rank), math.ceil(rank)
        return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)

    return {"minimum": ordered[0], "median": quantile(.5),
            "mean": statistics.fmean(ordered), "p75": quantile(.75),
            "p90": quantile(.90), "p95": quantile(.95),
            "p99": quantile(.99), "maximum": ordered[-1]}


@dataclass
class _Bar:
    sample_id: str
    bucket: datetime
    bid: list[float]
    ask: list[float]
    spreads: list[float]

    def add(self, bid: float, ask: float, spread: float) -> None:
        for prices, value in ((self.bid, bid), (self.ask, ask)):
            prices[1] = max(prices[1], value)
            prices[2] = min(prices[2], value)
            prices[3] = value
        self.spreads.append(spread)

    def write(self, bid_writer, ask_writer) -> None:
        common = {"sample_id": self.sample_id,
                  "timestamp_server": self.bucket.isoformat(),
                  "tick_count": len(self.spreads),
                  "spread_median": statistics.median(self.spreads),
                  "spread_mean": statistics.fmean(self.spreads),
                  "spread_max": max(self.spreads)}
        for writer, prices in ((bid_writer, self.bid), (ask_writer, self.ask)):
            writer.writerow({**common, **dict(zip(("open", "high", "low", "close"), prices))})


def process_sample(path: Path, sample_id: str, output_dir: Path) -> tuple[dict, list[float], dict[int, list[float]], list[dict]]:
    """Preserve raw order and carry only the last observed side within a segment."""
    path = Path(path)
    schema = inspect_tick_source(path)
    if len(schema) != 1 or schema[0].member is not None:
        raise TickImportError("MT5 sample processing expects one raw CSV per sample.")
    expected = ("<DATE>", "<TIME>", "<BID>", "<ASK>", "<LAST>", "<VOLUME>", "<FLAGS>")
    if schema[0].columns != expected:
        raise TickImportError(f"Unexpected MT5 columns in {path.name}: {schema[0].columns}")
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows = ticks = bid_only = ask_only = both = malformed = full_duplicates = duplicate_timestamps = 0
    bars = missing = 0
    first = last = previous = previous_bucket = current_bucket = None
    bid_state = ask_state = None
    bar = None
    spreads: list[float] = []
    bps: list[float] = []
    by_hour: dict[int, list[float]] = {}
    gaps: list[dict] = []
    seen_rows: set[tuple[str, ...]] = set()
    seen_times: set[datetime] = set()
    tick_handle, tick_writer = _writer(output_dir / f"btcusdm_{sample_id}_ticks_server_time.csv", TICK_COLUMNS)
    bid_handle, bid_writer = _writer(output_dir / f"btcusdm_{sample_id}_bid_15m_server_time.csv", BAR_COLUMNS)
    ask_handle, ask_writer = _writer(output_dir / f"btcusdm_{sample_id}_ask_15m_server_time.csv", BAR_COLUMNS)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter=schema[0].delimiter)
            for source_row, row in enumerate(reader, start=2):
                rows += 1
                if None in row or any(value is None for value in row.values()):
                    malformed += 1
                    continue
                date_raw, time_raw = row["<DATE>"], row["<TIME>"]
                bid_raw, ask_raw = row["<BID>"], row["<ASK>"]
                try:
                    stamp = _clock(date_raw, time_raw)
                except ValueError:
                    malformed += 1
                    continue
                if previous is not None and stamp < previous:
                    raise TickImportError(f"Out-of-order MT5 timestamp in {path.name} at row {source_row}.")
                previous = stamp
                first = stamp if first is None else first
                last = stamp
                if stamp in seen_times:
                    duplicate_timestamps += 1
                else:
                    seen_times.add(stamp)
                raw_tuple = tuple(row[column] for column in expected)
                if raw_tuple in seen_rows:
                    full_duplicates += 1
                    continue
                seen_rows.add(raw_tuple)

                next_bucket = _bucket(stamp)
                if previous_bucket is not None and next_bucket - previous_bucket > STEP:
                    count = int((next_bucket - previous_bucket) / STEP) - 1
                    missing += count
                    gaps.append({"sample_id": sample_id,
                                 "gap_start_server": (previous_bucket + STEP).isoformat(),
                                 "gap_end_server": (next_bucket - STEP).isoformat(),
                                 "missing_15m_intervals": count})
                    bid_state = ask_state = None
                previous_bucket = next_bucket
                if bid_raw and ask_raw:
                    both += 1
                    update_type = "both"
                elif bid_raw:
                    bid_only += 1
                    update_type = "bid_only"
                elif ask_raw:
                    ask_only += 1
                    update_type = "ask_only"
                else:
                    malformed += 1
                    continue
                try:
                    next_bid = _quote(bid_raw) if bid_raw else bid_state
                    next_ask = _quote(ask_raw) if ask_raw else ask_state
                except ValueError:
                    malformed += 1
                    continue
                bid_state, ask_state = next_bid, next_ask
                if bid_state is None or ask_state is None:
                    continue  # State is unknown until both sides have appeared in this segment.
                if ask_state < bid_state:
                    malformed += 1
                    continue
                spread = historical_spread_price(bid=bid_state, ask=ask_state)
                pct = spread / bid_state * 100
                spread_bps = spread / bid_state * 10_000
                tick_writer.writerow({"sample_id": sample_id, "source_row": source_row,
                                      "timestamp_raw": f"{date_raw} {time_raw}",
                                      "timestamp_server": stamp.isoformat(),
                                      "bid_raw": bid_raw, "ask_raw": ask_raw,
                                      "bid": bid_state, "ask": ask_state,
                                      "bid_carried": not bool(bid_raw),
                                      "ask_carried": not bool(ask_raw),
                                      "update_type": update_type,
                                      "spread_price": spread, "spread_pct": pct,
                                      "spread_bps": spread_bps})
                ticks += 1
                spreads.append(spread)
                bps.append(spread_bps)
                by_hour.setdefault(stamp.hour, []).append(spread)
                if bar is None or next_bucket != current_bucket:
                    if bar is not None:
                        bar.write(bid_writer, ask_writer)
                        bars += 1
                    bar = _Bar(sample_id, next_bucket,
                               [bid_state] * 4, [ask_state] * 4, [spread])
                    current_bucket = next_bucket
                else:
                    bar.add(bid_state, ask_state, spread)
        if bar is not None:
            bar.write(bid_writer, ask_writer)
            bars += 1
    finally:
        tick_handle.close()
        bid_handle.close()
        ask_handle.close()
    if first is None:
        raise TickImportError(f"No parseable ticks in {path.name}.")
    spread_stats = _distribution(spreads)
    day_type = "weekend" if first.weekday() >= 5 else "weekday"
    return ({"sample_id": sample_id, "filename": path.name, "sha256": digest,
             "sample_date": first.date().isoformat(), "day_type": day_type,
             "raw_rows": rows, "first_timestamp_server": first.isoformat(),
             "last_timestamp_server": last.isoformat(),
             "bid_only_updates": bid_only, "ask_only_updates": ask_only,
             "both_side_updates": both, "duplicate_full_rows": full_duplicates,
             "duplicate_timestamps": duplicate_timestamps, "malformed_rows": malformed,
             "tick_count": ticks, "bid_15m_bars": bars, "ask_15m_bars": bars,
             "missing_15m_intervals": missing, "median_spread_bps": statistics.median(bps),
             **{f"spread_{name}": value for name, value in spread_stats.items()}},
            spreads, by_hour, gaps)


def process_mt5_samples(paths: list[Path], *, processed_dir: Path = PROCESSED_DIR,
                        report_dir: Path = REPORT_DIR) -> dict:
    """Process each CSV independently and publish one combined descriptive audit."""
    if not paths:
        raise TickImportError("No MT5 BTCUSDm CSV samples were provided.")
    paths = sorted(map(Path, paths))
    processed_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict] = []
    all_spreads: list[float] = []
    all_bps: list[float] = []
    hourly: dict[int, list[float]] = {}
    gaps: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="mt5-samples-", dir=processed_dir) as temp_name:
        temp = Path(temp_name)
        for number, path in enumerate(paths, start=1):
            sample, spreads, sample_hourly, sample_gaps = process_sample(path, f"s{number:02d}", temp)
            samples.append(sample)
            all_spreads.extend(spreads)
            all_bps.extend(_read_bps(temp / f"btcusdm_s{number:02d}_ticks_server_time.csv"))
            for hour, values in sample_hourly.items():
                hourly.setdefault(hour, []).extend(values)
            gaps.extend(sample_gaps)
        combined = _distribution(all_spreads)
        summary = {"status": "mt5_samples_reconstructed",
                   "timezone_status": TIMEZONE_STATUS,
                   "broker": PROFILE.broker, "account_type": PROFILE.account_type,
                   "symbol": PROFILE.mt5_symbol, "commission_per_side_usd": 0,
                   "spread_source": "Historical reconstructed Bid/Ask quote states",
                   "sample_count": len(samples), "samples": samples,
                   "total_raw_rows": sum(s["raw_rows"] for s in samples),
                   "total_ticks": sum(s["tick_count"] for s in samples),
                   "total_15m_intervals": sum(s["bid_15m_bars"] for s in samples),
                   "total_observed_hours": sum(s["bid_15m_bars"] for s in samples) / 4,
                   "total_missing_15m_intervals": sum(s["missing_15m_intervals"] for s in samples),
                   "bid_only_updates": sum(s["bid_only_updates"] for s in samples),
                   "ask_only_updates": sum(s["ask_only_updates"] for s in samples),
                   "both_side_updates": sum(s["both_side_updates"] for s in samples),
                   "duplicate_full_rows": sum(s["duplicate_full_rows"] for s in samples),
                   "duplicate_timestamps": sum(s["duplicate_timestamps"] for s in samples),
                   "malformed_rows": sum(s["malformed_rows"] for s in samples),
                   "median_spread_bps": statistics.median(all_bps),
                   "combined_spread": combined,
                   "processed_at_utc": datetime.now(timezone.utc).isoformat()}
        reports = temp / "reports"
        reports.mkdir()
        _write_reports(reports, summary, hourly, gaps)
        for path in temp.glob("btcusdm_*_server_time.csv"):
            os.replace(path, processed_dir / path.name)
        for path in reports.iterdir():
            os.replace(path, report_dir / path.name)
    return summary


def _read_bps(path: Path) -> list[float]:
    with path.open(newline="") as handle:
        return [float(row["spread_bps"]) for row in csv.DictReader(handle)]


def _write_reports(folder: Path, summary: dict, hourly: dict[int, list[float]],
                   gaps: list[dict]) -> None:
    (folder / "multi_sample_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    samples = summary["samples"]
    with (folder / "sample_coverage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(samples[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(samples)
    with (folder / "spread_distribution.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["metric", "value", "unit"])
        for name, value in summary["combined_spread"].items():
            writer.writerow([f"{name}_spread_price", value, "USD/BTC"])
        writer.writerow(["median_spread_bps", summary["median_spread_bps"], "bps"])
    with (folder / "spread_by_hour.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["server_hour", "tick_count", "minimum_spread_price",
                         "median_spread_price", "mean_spread_price", "p95_spread_price",
                         "maximum_spread_price"])
        for hour, values in sorted(hourly.items()):
            stats = _distribution(values)
            writer.writerow([hour, len(values), stats["minimum"], stats["median"],
                             stats["mean"], stats["p95"], stats["maximum"]])
    with (folder / "sample_data_gaps.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle,
                                fieldnames=["sample_id", "gap_start_server", "gap_end_server",
                                            "missing_15m_intervals"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(gaps)
    spread = summary["combined_spread"]
    lines = ["# Exness BTCUSDm multi-sample quote reconstruction", "",
             f"Timezone status: **{TIMEZONE_STATUS}**. Timestamps, weekdays, and hours are MT5 server wall time; no UTC conversion was made.",
             "", "Each CSV was reconstructed independently in original row order. Bid-only and Ask-only updates carry the last known opposite side within the same file and continuous 15-minute sequence. No quote is carried across files, missing 15-minute intervals, or before that side first appears.",
             "", f"Samples: {summary['sample_count']}; raw rows: {summary['total_raw_rows']:,}; reconstructed complete ticks: {summary['total_ticks']:,}; 15-minute bars: {summary['total_15m_intervals']:,}; observed bar-hours: {summary['total_observed_hours']:g}.",
             f"Partial updates: Bid-only {summary['bid_only_updates']:,}; Ask-only {summary['ask_only_updates']:,}; both {summary['both_side_updates']:,}. Duplicate full rows {summary['duplicate_full_rows']:,}; duplicate timestamps {summary['duplicate_timestamps']:,}; malformed rows {summary['malformed_rows']:,}.",
             "", f"Combined spread USD/BTC: min {spread['minimum']:.6f}, median {spread['median']:.6f}, mean {spread['mean']:.6f}, P75 {spread['p75']:.6f}, P90 {spread['p90']:.6f}, P95 {spread['p95']:.6f}, P99 {spread['p99']:.6f}, max {spread['maximum']:.6f}; median {summary['median_spread_bps']:.6f} bps.",
             "", "| Sample | Date | Type | Raw rows | Ticks | Bars | Missing bars | Bid-only | Ask-only | Both | Full duplicates | Duplicate timestamps | Malformed | Median spread | P95 spread | Max spread | Median bps |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for sample in samples:
        lines.append(f"| {sample['sample_id']} | {sample['sample_date']} | {sample['day_type']} | "
                     f"{sample['raw_rows']:,} | {sample['tick_count']:,} | {sample['bid_15m_bars']:,} | "
                     f"{sample['missing_15m_intervals']:,} | {sample['bid_only_updates']:,} | "
                     f"{sample['ask_only_updates']:,} | {sample['both_side_updates']:,} | "
                     f"{sample['duplicate_full_rows']:,} | {sample['duplicate_timestamps']:,} | "
                     f"{sample['malformed_rows']:,} | {sample['spread_median']:.4f} | "
                     f"{sample['spread_p95']:.4f} | {sample['spread_maximum']:.4f} | "
                     f"{sample['median_spread_bps']:.4f} |")
    lines.extend(["", "Commission: $0. Spread source: reconstructed historical Bid/Ask quote states. The observed live screenshot spread was approximately $10/BTC. No fixed spread is activated in the generic engine.", ""])
    (folder / "tick_import_summary.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path,
                        help="Raw MT5 BTCUSDm CSV files; defaults to all BTCUSDm*.csv in data/exness/raw.")
    args = parser.parse_args()
    paths = args.files or sorted(RAW_DIR.glob("BTCUSDm*.csv"))
    result = process_mt5_samples(paths)
    print(json.dumps({key: value for key, value in result.items() if key != "samples"}, indent=2))


if __name__ == "__main__":
    main()

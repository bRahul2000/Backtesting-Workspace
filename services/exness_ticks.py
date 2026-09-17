"""Inspect and normalize user-supplied Exness BTCUSDm Bid/Ask tick files.

The importer requires explicit source column names and a timezone for naive
timestamps. It never changes the source, invents ticks, or touches Bitstamp.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sqlite3
import statistics
import tempfile
import zipfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterator

import numpy as np
import pandas as pd

from brokers.exness_standard_btcusdm import PROFILE


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data/exness/raw"
PROCESSED_DIR = ROOT / "data/exness/processed"
REPORT_DIR = ROOT / "reports/broker/exness"
STEP_NS = 15 * 60 * 1_000_000_000
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class TickImportError(ValueError):
    """Raw tick data cannot be imported without an explicit correction."""


@dataclass(frozen=True)
class TickColumns:
    timestamp: str
    bid: str
    ask: str
    time: str | None = None


@dataclass(frozen=True)
class SourceSchema:
    file: str
    member: str | None
    columns: tuple[str, ...]
    delimiter: str
    sample: tuple[dict[str, str], ...]


@contextmanager
def _source_stream(path: Path, member: str | None) -> Iterator[BinaryIO]:
    if member is None:
        with path.open("rb") as handle:
            yield handle
    else:
        with zipfile.ZipFile(path) as archive, archive.open(member) as handle:
            yield handle


def _members(path: Path) -> list[str | None]:
    if not path.is_file():
        raise TickImportError(f"Source file does not exist: {path}")
    if path.suffix.lower() == ".csv":
        return [None]
    if path.suffix.lower() != ".zip":
        raise TickImportError("Exness tick source must be CSV or ZIP.")
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info.filename for info in archive.infolist()
                       if not info.is_dir() and info.filename.lower().endswith(".csv")]
    except zipfile.BadZipFile as exc:
        raise TickImportError(f"Invalid ZIP file: {path.name}") from exc
    if not members:
        raise TickImportError("ZIP contains no CSV tick files.")
    return members


def inspect_tick_source(path: Path) -> list[SourceSchema]:
    """Show actual headers and sample rows before column mapping is chosen."""
    path = Path(path)
    schemas = []
    for member in _members(path):
        with _source_stream(path, member) as binary:
            sample_bytes = binary.read(65_536)
        try:
            sample_text = sample_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise TickImportError("CSV is not UTF-8; convert a copy before import.") from exc
        try:
            dialect = csv.Sniffer().sniff(sample_text, delimiters=",;\t|")
        except csv.Error as exc:
            raise TickImportError("Could not identify CSV delimiter; inspect the raw file.") from exc
        reader = csv.DictReader(io.StringIO(sample_text), delimiter=dialect.delimiter)
        columns = tuple(reader.fieldnames or ())
        if not columns or len(set(columns)) != len(columns):
            raise TickImportError("CSV needs a unique nonempty header row.")
        examples = tuple(dict(row) for _, row in zip(range(3), reader))
        schemas.append(SourceSchema(str(path), member, columns, dialect.delimiter, examples))
    return schemas


def _parse_timestamps(values: pd.Series, *, source_timezone: str | None,
                      timestamp_unit: str | None,
                      server_time_unverified: bool = False) -> pd.Series:
    text = values.astype("string").str.strip()
    if text.isna().any() or text.eq("").any():
        raise TickImportError("Tick timestamp is blank.")
    numeric = bool(text.str.fullmatch(r"[+-]?\d+(?:\.\d+)?").all())
    if server_time_unverified and (source_timezone is not None or timestamp_unit is not None):
        raise TickImportError("Unverified server-time mode cannot also claim a timezone or epoch unit.")
    if numeric:
        if server_time_unverified:
            raise TickImportError("Numeric timestamps cannot be treated as unverified server wall time.")
        if timestamp_unit not in ("s", "ms", "us", "ns"):
            raise TickImportError("Numeric timestamps require explicit --timestamp-unit s/ms/us/ns.")
        parsed = pd.to_datetime(pd.to_numeric(text, errors="coerce"), unit=timestamp_unit,
                                utc=True, errors="coerce")
    else:
        if timestamp_unit is not None:
            raise TickImportError("Timestamp unit applies only to numeric timestamps.")
        try:
            parsed = pd.to_datetime(text, errors="coerce", format="mixed")
        except (TypeError, ValueError) as exc:
            raise TickImportError("Timestamp format could not be parsed.") from exc
        if isinstance(parsed.dtype, pd.DatetimeTZDtype):
            if server_time_unverified:
                raise TickImportError("Offset-aware timestamps do not need unverified server-time mode.")
            parsed = parsed.dt.tz_convert("UTC")
        elif pd.api.types.is_datetime64_any_dtype(parsed):
            if server_time_unverified:
                parsed = parsed.astype("datetime64[ns]")
            elif source_timezone is None:
                raise TickImportError("Naive timestamps require an explicit source timezone.")
            else:
                try:
                    parsed = parsed.dt.tz_localize(source_timezone, ambiguous="raise",
                                                   nonexistent="raise").dt.tz_convert("UTC")
                except (TypeError, ValueError, KeyError) as exc:
                    raise TickImportError("Source timezone is invalid or has ambiguous local times.") from exc
        else:
            raise TickImportError("Mixed timezone formats need a normalized source file.")
    if parsed.isna().any():
        raise TickImportError("One or more tick timestamps could not be parsed.")
    return parsed


def normalize_tick_chunk(chunk: pd.DataFrame, columns: TickColumns, *,
                         source_timezone: str | None = None,
                         timestamp_unit: str | None = None,
                         server_time_unverified: bool = False) -> pd.DataFrame:
    mapped = [columns.timestamp, columns.bid, columns.ask]
    if columns.time is not None:
        mapped.append(columns.time)
    if len(set(mapped)) != len(mapped):
        raise TickImportError("Timestamp/date, optional time, Bid, and Ask must map to distinct columns.")
    missing = [name for name in mapped
               if name not in chunk.columns]
    if missing:
        raise TickImportError("Mapped tick column(s) absent: " + ", ".join(missing))
    stamp_values = (chunk[columns.timestamp].astype("string").str.strip() + " " +
                    chunk[columns.time].astype("string").str.strip()
                    if columns.time is not None else chunk[columns.timestamp])
    timestamps = _parse_timestamps(stamp_values,
                                   source_timezone=source_timezone,
                                   timestamp_unit=timestamp_unit,
                                   server_time_unverified=server_time_unverified)
    bid = pd.to_numeric(chunk[columns.bid], errors="coerce")
    ask = pd.to_numeric(chunk[columns.ask], errors="coerce")
    if (bid.isna().any() or ask.isna().any() or not np.isfinite(bid).all()
            or not np.isfinite(ask).all() or (bid <= 0).any()
            or (ask <= 0).any() or (ask < bid).any()):
        raise TickImportError("Malformed Bid/Ask row: require finite bid > 0 and ask >= bid.")
    spread = ask - bid
    # Pandas may infer microsecond resolution from CSV strings. Force ns before
    # converting to integer SQLite keys and 15-minute UTC bucket boundaries.
    time_column = "timestamp_server" if server_time_unverified else "timestamp_utc"
    timestamps = timestamps.astype("datetime64[ns]" if server_time_unverified
                                   else "datetime64[ns, UTC]")
    result = pd.DataFrame({time_column: timestamps,
                           "bid": bid.astype(float), "ask": ask.astype(float)})
    result["spread_price"] = spread.astype(float)
    result["spread_pct"] = result.spread_price / result.bid * 100
    result["spread_bps"] = result.spread_price / result.bid * 10_000
    return result


def _insert_chunks(connection: sqlite3.Connection, paths: list[Path],
                   columns: TickColumns, source_timezone: str | None,
                   timestamp_unit: str | None, chunk_rows: int,
                   server_time_unverified: bool,
                   skip_incomplete_quotes: bool) -> tuple[int, int, int, int, int, list[dict]]:
    input_rows = 0
    invalid_quotes = 0
    sources = []
    sql = ("INSERT OR IGNORE INTO ticks "
           "(timestamp_ns,bid,ask,spread_price,spread_pct,spread_bps,utc_hour,utc_weekday,bucket_ns) "
           "VALUES (?,?,?,?,?,?,?,?,?)")
    for path in paths:
        hasher = hashlib.sha256()
        with path.open("rb") as raw:
            for block in iter(lambda: raw.read(1024 * 1024), b""):
                hasher.update(block)
        digest = hasher.hexdigest()
        for schema in inspect_tick_source(path):
            if any(name not in schema.columns for name in
                   (columns.timestamp, columns.bid, columns.ask, *([columns.time] if columns.time else []))):
                raise TickImportError(f"Mapped columns do not match {path.name}/{schema.member or ''}.")
            member_rows = 0
            with _source_stream(path, schema.member) as binary:
                try:
                    chunks = pd.read_csv(binary, sep=schema.delimiter, chunksize=chunk_rows,
                                         encoding="utf-8-sig", dtype=str)
                    for chunk in chunks:
                        stamp_values = (chunk[columns.timestamp].astype("string").str.strip() + " " +
                                        chunk[columns.time].astype("string").str.strip()
                                        if columns.time is not None else chunk[columns.timestamp])
                        raw_timestamps = _parse_timestamps(
                            stamp_values, source_timezone=source_timezone,
                            timestamp_unit=timestamp_unit,
                            server_time_unverified=server_time_unverified)
                        raw_ns = raw_timestamps.astype("datetime64[ns]" if server_time_unverified
                                                       else "datetime64[ns, UTC]").astype("int64")
                        fingerprints = (hashlib.sha256(json.dumps(
                            [None if pd.isna(value) else value for value in row],
                            separators=(",", ":"), ensure_ascii=False).encode()).digest()
                            for row in chunk.itertuples(index=False, name=None))
                        connection.executemany(
                            "INSERT OR IGNORE INTO raw_events(timestamp_ns,full_row_hash) VALUES (?,?)",
                            zip(raw_ns.astype(int), fingerprints))
                        incomplete = (chunk[columns.bid].isna() |
                                      chunk[columns.ask].isna() |
                                      chunk[columns.bid].astype("string").str.strip().eq("") |
                                      chunk[columns.ask].astype("string").str.strip().eq(""))
                        count_incomplete = int(incomplete.sum())
                        if count_incomplete and not skip_incomplete_quotes:
                            raise TickImportError(
                                f"{count_incomplete} rows have incomplete Bid/Ask quotes; "
                                "explicitly enable skipping incomplete quotes to retain only complete pairs.")
                        invalid_quotes += count_incomplete
                        normalized = normalize_tick_chunk(
                            chunk.loc[~incomplete], columns, source_timezone=source_timezone,
                            timestamp_unit=timestamp_unit,
                            server_time_unverified=server_time_unverified)
                        time = normalized.timestamp_server if server_time_unverified else normalized.timestamp_utc
                        ns = time.astype("int64")
                        values = zip(
                            ns.astype(int), normalized.bid, normalized.ask,
                            normalized.spread_price, normalized.spread_pct,
                            normalized.spread_bps, time.dt.hour.astype(int),
                            time.dt.weekday.astype(int), (ns // STEP_NS * STEP_NS).astype(int),
                        )
                        connection.executemany(sql, values)
                        member_rows += len(chunk)
                        input_rows += len(chunk)
                except (pd.errors.ParserError, UnicodeDecodeError) as exc:
                    raise TickImportError(f"Malformed CSV in {path.name}/{schema.member or ''}.") from exc
            sources.append({"file": path.name, "member": schema.member,
                            "sha256": digest, "input_rows": member_rows,
                            "columns": asdict(columns), "source_timezone": source_timezone,
                            "timestamp_unit": timestamp_unit,
                            "server_time_unverified": server_time_unverified})
    unique = int(connection.execute("SELECT COUNT(*) FROM ticks").fetchone()[0])
    full_unique, raw_unique_times = connection.execute(
        "SELECT COUNT(*),COUNT(DISTINCT timestamp_ns) FROM raw_events").fetchone()
    return (input_rows, input_rows - invalid_quotes - unique,
            input_rows - full_unique, input_rows - raw_unique_times,
            invalid_quotes, sources)


def _percentile(connection: sqlite3.Connection, column: str, percentile: float,
                *, where: str = "", parameters: tuple = ()) -> float:
    count = connection.execute(f"SELECT COUNT(*) FROM ticks {where}", parameters).fetchone()[0]
    if not count:
        return math.nan
    rank = (count - 1) * percentile
    lower, upper = math.floor(rank), math.ceil(rank)
    query = f"SELECT {column} FROM ticks {where} ORDER BY {column} LIMIT 1 OFFSET ?"
    first = connection.execute(query, (*parameters, lower)).fetchone()[0]
    if lower == upper:
        return float(first)
    second = connection.execute(query, (*parameters, upper)).fetchone()[0]
    return float(first + (second - first) * (rank - lower))


def _clock_stamp(ns: int, server_time_unverified: bool) -> str:
    return pd.Timestamp(ns, unit="ns").isoformat() if server_time_unverified else pd.Timestamp(
        ns, unit="ns", tz="UTC").isoformat()


def _stats(connection: sqlite3.Connection, server_time_unverified: bool) -> dict:
    count, first_ns, last_ns, minimum, average, maximum = connection.execute(
        "SELECT COUNT(*),MIN(timestamp_ns),MAX(timestamp_ns),"
        "MIN(spread_price),AVG(spread_price),MAX(spread_price) FROM ticks").fetchone()
    if not count:
        raise TickImportError("Source contains no valid ticks.")
    suffix = "server" if server_time_unverified else "utc"
    values = {"tick_count": count,
              f"first_tick_{suffix}": _clock_stamp(first_ns, server_time_unverified),
              f"last_tick_{suffix}": _clock_stamp(last_ns, server_time_unverified),
              "minimum_spread_price": minimum, "mean_spread_price": average,
              "maximum_spread_price": maximum}
    for name, fraction in (("median", .5), ("p75", .75), ("p90", .9),
                           ("p95", .95), ("p99", .99)):
        values[f"{name}_spread_price"] = _percentile(connection, "spread_price", fraction)
    values["median_spread_pct"] = _percentile(connection, "spread_pct", .5)
    values["median_spread_bps"] = _percentile(connection, "spread_bps", .5)
    values["time_weighted_spread"] = None
    values["time_weighted_spread_note"] = (
        "Not calculated: quote validity between irregular ticks and across tick gaps is unverified.")
    return values


def _group_spreads(connection: sqlite3.Connection, group: str, count: int) -> list[dict]:
    rows = []
    for value in range(count):
        where = f"WHERE {group}=?"
        n, minimum, average, maximum = connection.execute(
            f"SELECT COUNT(*),MIN(spread_price),AVG(spread_price),MAX(spread_price) "
            f"FROM ticks {where}", (value,)).fetchone()
        if not n:
            continue
        rows.append({group: value, "tick_count": n, "minimum_spread_price": minimum,
                     "median_spread_price": _percentile(connection, "spread_price", .5,
                                                         where=where, parameters=(value,)),
                     "mean_spread_price": average,
                     "p95_spread_price": _percentile(connection, "spread_price", .95,
                                                      where=where, parameters=(value,)),
                     "maximum_spread_price": maximum})
    return rows


def _write_sorted_ticks_and_bars(connection: sqlite3.Connection, folder: Path,
                                 server_time_unverified: bool) -> tuple[int, list[dict]]:
    suffix = "_server_time" if server_time_unverified else ""
    ticks_path = folder / f"btcusdm_ticks{suffix}.csv"
    bid_path = folder / f"btcusdm_bid_15m{suffix}.csv"
    ask_path = folder / f"btcusdm_ask_15m{suffix}.csv"
    stamp_label = "timestamp_server" if server_time_unverified else "timestamp_utc"
    header = [stamp_label, "bid", "ask", "spread_price", "spread_pct", "spread_bps"]
    bar_header = [stamp_label, "open", "high", "low", "close", "tick_count",
                  "spread_open", "spread_median", "spread_mean", "spread_max"]
    gaps = []
    count = 0
    previous_bucket = None
    current = None

    def flush(bid_writer, ask_writer):
        nonlocal count, current, previous_bucket
        if current is None:
            return
        stamp = _clock_stamp(current["bucket"], server_time_unverified)
        spread = current["spreads"]
        descriptors = [len(spread), spread[0], statistics.median(spread),
                       statistics.fmean(spread), max(spread)]
        bid_writer.writerow([stamp, *current["bid"], *descriptors])
        ask_writer.writerow([stamp, *current["ask"], *descriptors])
        count += 1
        previous_bucket = current["bucket"]

    with (ticks_path.open("w", newline="") as tick_file,
          bid_path.open("w", newline="") as bid_file,
          ask_path.open("w", newline="") as ask_file):
        tick_writer, bid_writer, ask_writer = (
            csv.writer(tick_file, lineterminator="\n"),
            csv.writer(bid_file, lineterminator="\n"),
            csv.writer(ask_file, lineterminator="\n"))
        tick_writer.writerow(header)
        bid_writer.writerow(bar_header)
        ask_writer.writerow(bar_header)
        cursor = connection.execute(
            "SELECT timestamp_ns,bid,ask,spread_price,spread_pct,spread_bps,bucket_ns "
            "FROM ticks ORDER BY timestamp_ns,seq")
        for ns, bid, ask, spread_price, spread_pct, spread_bps, bucket in cursor:
            stamp = _clock_stamp(ns, server_time_unverified)
            tick_writer.writerow([stamp, bid, ask, spread_price, spread_pct, spread_bps])
            if current is None or bucket != current["bucket"]:
                flush(bid_writer, ask_writer)
                if previous_bucket is not None and bucket - previous_bucket > STEP_NS:
                    missing = (bucket - previous_bucket) // STEP_NS - 1
                    gap_suffix = "server" if server_time_unverified else "utc"
                    gaps.append({
                        f"gap_start_{gap_suffix}": _clock_stamp(previous_bucket + STEP_NS, server_time_unverified),
                        f"gap_end_{gap_suffix}": _clock_stamp(bucket - STEP_NS, server_time_unverified),
                        "missing_15m_intervals": int(missing),
                    })
                current = {"bucket": bucket, "bid": [bid, bid, bid, bid],
                           "ask": [ask, ask, ask, ask], "spreads": [spread_price]}
            else:
                for side, value in (("bid", bid), ("ask", ask)):
                    ohlc = current[side]
                    ohlc[1] = max(ohlc[1], value)
                    ohlc[2] = min(ohlc[2], value)
                    ohlc[3] = value
                current["spreads"].append(spread_price)
        flush(bid_writer, ask_writer)
    return count, gaps


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _write_reports(summary: dict, connection: sqlite3.Connection,
                   report_folder: Path, gaps: list[dict],
                   server_time_unverified: bool) -> None:
    report_folder.mkdir(parents=True, exist_ok=True)
    spread_rows = [{"metric": key, "value": summary[key], "unit": unit}
                   for key, unit in (("minimum_spread_price", "USD/BTC"),
                                     ("median_spread_price", "USD/BTC"),
                                     ("mean_spread_price", "USD/BTC"),
                                     ("p75_spread_price", "USD/BTC"),
                                     ("p90_spread_price", "USD/BTC"),
                                     ("p95_spread_price", "USD/BTC"),
                                     ("p99_spread_price", "USD/BTC"),
                                     ("maximum_spread_price", "USD/BTC"),
                                     ("median_spread_pct", "%"),
                                     ("median_spread_bps", "bps"))]
    _write_csv(report_folder / "spread_distribution.csv", spread_rows,
               ["metric", "value", "unit"])
    hourly = _group_spreads(connection, "utc_hour", 24)
    weekdays = _group_spreads(connection, "utc_weekday", 7)
    hour_label = "server_hour" if server_time_unverified else "utc_hour"
    weekday_label = "server_weekday" if server_time_unverified else "utc_weekday"
    _write_csv(report_folder / ("spread_by_server_hour.csv" if server_time_unverified else "spread_by_hour.csv"),
               [{hour_label: row["utc_hour"], **{k: v for k, v in row.items() if k != "utc_hour"}}
                for row in hourly],
               [hour_label, "tick_count", "minimum_spread_price", "median_spread_price",
                "mean_spread_price", "p95_spread_price", "maximum_spread_price"])
    _write_csv(report_folder / ("spread_by_server_weekday.csv" if server_time_unverified else "spread_by_weekday.csv"),
               [{weekday_label: row["utc_weekday"],
                 "weekday_name": WEEKDAYS[row["utc_weekday"]],
                 **{k: v for k, v in row.items() if k != "utc_weekday"}}
                for row in weekdays],
               [weekday_label, "weekday_name", "tick_count", "minimum_spread_price",
                "median_spread_price", "mean_spread_price", "p95_spread_price",
                "maximum_spread_price"])
    gap_suffix = "server" if server_time_unverified else "utc"
    _write_csv(report_folder / ("data_gaps_server_time.csv" if server_time_unverified else "data_gaps.csv"),
               gaps, [f"gap_start_{gap_suffix}", f"gap_end_{gap_suffix}",
                      "missing_15m_intervals"])
    p99 = summary["p99_spread_price"]
    extreme_column = "bucket_server" if server_time_unverified else "bucket_utc"
    extreme = [dict(**{extreme_column: _clock_stamp(bucket, server_time_unverified)},
                    extreme_ticks=ticks, maximum_spread_price=maximum)
               for bucket, ticks, maximum in connection.execute(
                   "SELECT bucket_ns,COUNT(*),MAX(spread_price) FROM ticks "
                   "WHERE spread_price>? GROUP BY bucket_ns ORDER BY bucket_ns", (p99,))]
    _write_csv(report_folder / ("extreme_spread_periods_server_time.csv" if server_time_unverified
                                else "extreme_spread_periods.csv"), extreme,
               [extreme_column, "extreme_ticks", "maximum_spread_price"])
    (report_folder / "tick_import_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    source_names = ", ".join(item["file"] + (f"/{item['member']}" if item["member"] else "")
                             for item in summary["sources"])
    clock_suffix = "server" if server_time_unverified else "utc"
    clock_name = "Unverified MT5 broker-server time" if server_time_unverified else "UTC"
    (report_folder / "tick_import_summary.md").write_text(
        "# Exness BTCUSDm tick import\n\n"
        f"Sources: {source_names}\n\n"
        f"Raw rows: {summary['input_rows']:,}; unique ticks: {summary['tick_count']:,}; "
        f"invalid Bid/Ask rows: {summary['invalid_bid_ask_rows']:,}; "
        f"duplicate full rows: {summary['duplicate_full_rows']:,}; "
        f"duplicate timestamps (including full-row duplicates): "
        f"{summary['duplicate_timestamps_raw']:,}; distinct quotes sharing a timestamp: "
        f"{summary['same_timestamp_distinct_quotes']:,}.\n\n"
        f"{clock_name} range: {summary[f'first_tick_{clock_suffix}']} to "
        f"{summary[f'last_tick_{clock_suffix}']}.\n\n"
        f"Median spread: ${summary['median_spread_price']:.4f}/BTC "
        f"({summary['median_spread_bps']:.3f} bps); mean ${summary['mean_spread_price']:.4f}; "
        f"P95 ${summary['p95_spread_price']:.4f}; maximum ${summary['maximum_spread_price']:.4f}.\n\n"
        f"15-minute Bid and Ask bars: {summary['bid_15m_candles']:,}; "
        f"missing intervals within range: {summary['missing_15m_intervals']:,}.\n\n"
        "Extreme spread periods above the imported P99 are retained; none were removed.\n\n" +
        ("UTC conversion, UTC-hour analysis, and canonical UTC bars are pending timezone verification.\n\n"
         if server_time_unverified else "") +
        f"Time-weighted spread: {summary['time_weighted_spread_note']}\n"
    )


def import_tick_sources(paths: list[Path], columns: TickColumns, *,
                        source_timezone: str | None = None,
                        timestamp_unit: str | None = None,
                        server_time_unverified: bool = False,
                        skip_incomplete_quotes: bool = False,
                        processed_dir: Path = PROCESSED_DIR,
                        report_dir: Path = REPORT_DIR,
                        chunk_rows: int = 100_000) -> dict:
    """Atomically replace broker-only processed outputs after full validation."""
    if not paths:
        raise TickImportError("Choose at least one raw tick file.")
    paths = [Path(path) for path in paths]
    processed_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="exness-import-", dir=processed_dir) as temp_name:
        temp = Path(temp_name)
        connection = sqlite3.connect(temp / "ticks.sqlite")
        try:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute(
                "CREATE TABLE ticks (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "timestamp_ns INTEGER NOT NULL,bid REAL NOT NULL,ask REAL NOT NULL,"
                "spread_price REAL NOT NULL,spread_pct REAL NOT NULL,"
                "spread_bps REAL NOT NULL,utc_hour INTEGER NOT NULL,"
                "utc_weekday INTEGER NOT NULL,bucket_ns INTEGER NOT NULL,"
                "UNIQUE(timestamp_ns,bid,ask))")
            connection.execute(
                "CREATE TABLE raw_events (timestamp_ns INTEGER NOT NULL, "
                "full_row_hash BLOB NOT NULL UNIQUE)")
            input_rows, duplicates, full_duplicates, duplicate_timestamps, invalid_quotes, sources = _insert_chunks(
                connection, paths, columns, source_timezone, timestamp_unit,
                chunk_rows, server_time_unverified, skip_incomplete_quotes)
            connection.commit()
            connection.execute("CREATE INDEX ticks_time ON ticks(timestamp_ns,seq)")
            connection.execute("CREATE INDEX ticks_spread ON ticks(spread_price)")
            connection.execute("CREATE INDEX ticks_spread_pct ON ticks(spread_pct)")
            connection.execute("CREATE INDEX ticks_hour_spread ON ticks(utc_hour,spread_price)")
            connection.execute("CREATE INDEX ticks_weekday_spread ON ticks(utc_weekday,spread_price)")
            summary = _stats(connection, server_time_unverified)
            distinct_valid_timestamps = connection.execute(
                "SELECT COUNT(DISTINCT timestamp_ns) FROM ticks").fetchone()[0]
            candle_count, gaps = _write_sorted_ticks_and_bars(
                connection, temp, server_time_unverified)
            summary.update({"status": ("imported_server_time_unverified" if server_time_unverified
                                       else "imported"),
                            "timezone_status": ("UNVERIFIED MT5 BROKER-SERVER TIME" if server_time_unverified
                                                else "UTC NORMALIZED"),
                            "broker": PROFILE.broker,
                            "account_type": PROFILE.account_type,
                            "symbol": PROFILE.mt5_symbol,
                            "source_file": ", ".join(path.name for path in paths),
                            "sources": sources, "input_rows": input_rows,
                            "duplicates_removed": duplicates,
                            "duplicate_full_rows": full_duplicates,
                            "duplicate_timestamps_raw": duplicate_timestamps,
                            "same_timestamp_distinct_quotes": summary["tick_count"] - distinct_valid_timestamps,
                            "invalid_bid_ask_rows": invalid_quotes,
                            "bid_15m_candles": candle_count,
                            "ask_15m_candles": candle_count,
                            "missing_15m_intervals": sum(g["missing_15m_intervals"] for g in gaps),
                            "gap_count": len(gaps),
                            "imported_at_utc": datetime.now(timezone.utc).isoformat()})
            report_temp = temp / "reports"
            _write_reports(summary, connection, report_temp, gaps,
                           server_time_unverified)
        finally:
            connection.close()
        suffix = "_server_time" if server_time_unverified else ""
        for name in (f"btcusdm_ticks{suffix}.csv", f"btcusdm_bid_15m{suffix}.csv",
                     f"btcusdm_ask_15m{suffix}.csv"):
            os.replace(temp / name, processed_dir / name)
        for file in report_temp.iterdir():
            os.replace(file, report_dir / file.name)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("files", nargs="+", type=Path)
    ingest = sub.add_parser("import")
    ingest.add_argument("files", nargs="+", type=Path)
    for name in ("timestamp", "bid", "ask"):
        ingest.add_argument(f"--{name}-column", required=True)
    ingest.add_argument("--time-column", help="Optional separate time-of-day column to combine with date.")
    ingest.add_argument("--source-timezone")
    ingest.add_argument("--timestamp-unit", choices=["s", "ms", "us", "ns"])
    ingest.add_argument("--server-time-unverified", action="store_true",
                        help="Preserve naive MT5 wall time without claiming UTC; write provisional outputs.")
    ingest.add_argument("--skip-incomplete-quotes", action="store_true",
                        help="Explicitly exclude rows missing Bid or Ask; never forward-fill quotes.")
    args = parser.parse_args()
    if args.command == "inspect":
        for path in args.files:
            for schema in inspect_tick_source(path):
                print(json.dumps(asdict(schema), indent=2))
    else:
        result = import_tick_sources(args.files,
                                     TickColumns(args.timestamp_column, args.bid_column,
                                                 args.ask_column, args.time_column),
                                     source_timezone=args.source_timezone,
                                     timestamp_unit=args.timestamp_unit,
                                     server_time_unverified=args.server_time_unverified,
                                     skip_incomplete_quotes=args.skip_incomplete_quotes)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

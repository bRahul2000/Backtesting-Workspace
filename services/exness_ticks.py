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
                      timestamp_unit: str | None) -> pd.Series:
    text = values.astype("string").str.strip()
    if text.isna().any() or text.eq("").any():
        raise TickImportError("Tick timestamp is blank.")
    numeric = bool(text.str.fullmatch(r"[+-]?\d+(?:\.\d+)?").all())
    if numeric:
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
            parsed = parsed.dt.tz_convert("UTC")
        elif pd.api.types.is_datetime64_any_dtype(parsed):
            if source_timezone is None:
                raise TickImportError("Naive timestamps require an explicit source timezone.")
            try:
                parsed = parsed.dt.tz_localize(source_timezone, ambiguous="raise",
                                               nonexistent="raise").dt.tz_convert("UTC")
            except (TypeError, ValueError) as exc:
                raise TickImportError("Source timezone is invalid or has ambiguous local times.") from exc
        else:
            raise TickImportError("Mixed timezone formats need a normalized source file.")
    if parsed.isna().any():
        raise TickImportError("One or more tick timestamps could not be parsed.")
    return parsed


def normalize_tick_chunk(chunk: pd.DataFrame, columns: TickColumns, *,
                         source_timezone: str | None = None,
                         timestamp_unit: str | None = None) -> pd.DataFrame:
    if len({columns.timestamp, columns.bid, columns.ask}) != 3:
        raise TickImportError("Timestamp, Bid, and Ask must map to three distinct columns.")
    missing = [name for name in (columns.timestamp, columns.bid, columns.ask)
               if name not in chunk.columns]
    if missing:
        raise TickImportError("Mapped tick column(s) absent: " + ", ".join(missing))
    timestamps = _parse_timestamps(chunk[columns.timestamp],
                                   source_timezone=source_timezone,
                                   timestamp_unit=timestamp_unit)
    bid = pd.to_numeric(chunk[columns.bid], errors="coerce")
    ask = pd.to_numeric(chunk[columns.ask], errors="coerce")
    if (bid.isna().any() or ask.isna().any() or not np.isfinite(bid).all()
            or not np.isfinite(ask).all() or (bid <= 0).any()
            or (ask <= 0).any() or (ask < bid).any()):
        raise TickImportError("Malformed Bid/Ask row: require finite bid > 0 and ask >= bid.")
    spread = ask - bid
    # Pandas may infer microsecond resolution from CSV strings. Force ns before
    # converting to integer SQLite keys and 15-minute UTC bucket boundaries.
    timestamps = timestamps.astype("datetime64[ns, UTC]")
    result = pd.DataFrame({"timestamp_utc": timestamps,
                           "bid": bid.astype(float), "ask": ask.astype(float)})
    result["spread_price"] = spread.astype(float)
    result["spread_pct"] = result.spread_price / result.bid * 100
    result["spread_bps"] = result.spread_price / result.bid * 10_000
    return result


def _insert_chunks(connection: sqlite3.Connection, paths: list[Path],
                   columns: TickColumns, source_timezone: str | None,
                   timestamp_unit: str | None, chunk_rows: int) -> tuple[int, int, list[dict]]:
    input_rows = 0
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
                   (columns.timestamp, columns.bid, columns.ask)):
                raise TickImportError(f"Mapped columns do not match {path.name}/{schema.member or ''}.")
            member_rows = 0
            with _source_stream(path, schema.member) as binary:
                try:
                    chunks = pd.read_csv(binary, sep=schema.delimiter, chunksize=chunk_rows,
                                         encoding="utf-8-sig", dtype=str)
                    for chunk in chunks:
                        normalized = normalize_tick_chunk(
                            chunk, columns, source_timezone=source_timezone,
                            timestamp_unit=timestamp_unit)
                        time = normalized.timestamp_utc
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
                            "timestamp_unit": timestamp_unit})
    unique = int(connection.execute("SELECT COUNT(*) FROM ticks").fetchone()[0])
    return input_rows, input_rows - unique, sources


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


def _stats(connection: sqlite3.Connection) -> dict:
    count, first_ns, last_ns, minimum, average, maximum = connection.execute(
        "SELECT COUNT(*),MIN(timestamp_ns),MAX(timestamp_ns),"
        "MIN(spread_price),AVG(spread_price),MAX(spread_price) FROM ticks").fetchone()
    if not count:
        raise TickImportError("Source contains no valid ticks.")
    values = {"tick_count": count,
              "first_tick_utc": pd.Timestamp(first_ns, unit="ns", tz="UTC").isoformat(),
              "last_tick_utc": pd.Timestamp(last_ns, unit="ns", tz="UTC").isoformat(),
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


def _write_sorted_ticks_and_bars(connection: sqlite3.Connection, folder: Path) -> tuple[int, list[dict]]:
    ticks_path = folder / "btcusdm_ticks.csv"
    bid_path = folder / "btcusdm_bid_15m.csv"
    ask_path = folder / "btcusdm_ask_15m.csv"
    header = ["timestamp_utc", "bid", "ask", "spread_price", "spread_pct", "spread_bps"]
    bar_header = ["timestamp_utc", "open", "high", "low", "close", "tick_count",
                  "spread_open", "spread_median", "spread_mean", "spread_max"]
    gaps = []
    count = 0
    previous_bucket = None
    current = None

    def flush(bid_writer, ask_writer):
        nonlocal count, current, previous_bucket
        if current is None:
            return
        stamp = pd.Timestamp(current["bucket"], unit="ns", tz="UTC").isoformat()
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
        tick_writer, bid_writer, ask_writer = (csv.writer(tick_file), csv.writer(bid_file),
                                               csv.writer(ask_file))
        tick_writer.writerow(header)
        bid_writer.writerow(bar_header)
        ask_writer.writerow(bar_header)
        cursor = connection.execute(
            "SELECT timestamp_ns,bid,ask,spread_price,spread_pct,spread_bps,bucket_ns "
            "FROM ticks ORDER BY timestamp_ns,seq")
        for ns, bid, ask, spread_price, spread_pct, spread_bps, bucket in cursor:
            stamp = pd.Timestamp(ns, unit="ns", tz="UTC").isoformat()
            tick_writer.writerow([stamp, bid, ask, spread_price, spread_pct, spread_bps])
            if current is None or bucket != current["bucket"]:
                flush(bid_writer, ask_writer)
                if previous_bucket is not None and bucket - previous_bucket > STEP_NS:
                    missing = (bucket - previous_bucket) // STEP_NS - 1
                    gaps.append({
                        "gap_start_utc": pd.Timestamp(previous_bucket + STEP_NS, unit="ns", tz="UTC").isoformat(),
                        "gap_end_utc": pd.Timestamp(bucket - STEP_NS, unit="ns", tz="UTC").isoformat(),
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
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_reports(summary: dict, connection: sqlite3.Connection,
                   report_folder: Path, gaps: list[dict]) -> None:
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
    _write_csv(report_folder / "spread_by_hour.csv", hourly,
               ["utc_hour", "tick_count", "minimum_spread_price", "median_spread_price",
                "mean_spread_price", "p95_spread_price", "maximum_spread_price"])
    _write_csv(report_folder / "spread_by_weekday.csv",
               [{**row, "weekday_name": WEEKDAYS[row["utc_weekday"]]} for row in weekdays],
               ["utc_weekday", "weekday_name", "tick_count", "minimum_spread_price",
                "median_spread_price", "mean_spread_price", "p95_spread_price",
                "maximum_spread_price"])
    _write_csv(report_folder / "data_gaps.csv", gaps,
               ["gap_start_utc", "gap_end_utc", "missing_15m_intervals"])
    p99 = summary["p99_spread_price"]
    extreme = [dict(bucket_utc=pd.Timestamp(bucket, unit="ns", tz="UTC").isoformat(),
                    extreme_ticks=ticks, maximum_spread_price=maximum)
               for bucket, ticks, maximum in connection.execute(
                   "SELECT bucket_ns,COUNT(*),MAX(spread_price) FROM ticks "
                   "WHERE spread_price>? GROUP BY bucket_ns ORDER BY bucket_ns", (p99,))]
    _write_csv(report_folder / "extreme_spread_periods.csv", extreme,
               ["bucket_utc", "extreme_ticks", "maximum_spread_price"])
    (report_folder / "tick_import_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    source_names = ", ".join(item["file"] + (f"/{item['member']}" if item["member"] else "")
                             for item in summary["sources"])
    (report_folder / "tick_import_summary.md").write_text(
        "# Exness BTCUSDm tick import\n\n"
        f"Sources: {source_names}\n\n"
        f"Unique ticks: {summary['tick_count']:,}; exact duplicates removed: {summary['duplicates_removed']:,}.\n\n"
        f"UTC range: {summary['first_tick_utc']} to {summary['last_tick_utc']}.\n\n"
        f"Median spread: ${summary['median_spread_price']:.4f}/BTC "
        f"({summary['median_spread_bps']:.3f} bps); mean ${summary['mean_spread_price']:.4f}; "
        f"P95 ${summary['p95_spread_price']:.4f}; maximum ${summary['maximum_spread_price']:.4f}.\n\n"
        f"15-minute Bid and Ask bars: {summary['bid_15m_candles']:,}; "
        f"missing intervals within range: {summary['missing_15m_intervals']:,}.\n\n"
        "Extreme spread periods above the imported P99 are retained in `extreme_spread_periods.csv`.\n\n"
        f"Time-weighted spread: {summary['time_weighted_spread_note']}\n"
    )


def import_tick_sources(paths: list[Path], columns: TickColumns, *,
                        source_timezone: str | None = None,
                        timestamp_unit: str | None = None,
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
            input_rows, duplicates, sources = _insert_chunks(
                connection, paths, columns, source_timezone, timestamp_unit, chunk_rows)
            connection.commit()
            connection.execute("CREATE INDEX ticks_time ON ticks(timestamp_ns,seq)")
            connection.execute("CREATE INDEX ticks_spread ON ticks(spread_price)")
            connection.execute("CREATE INDEX ticks_spread_pct ON ticks(spread_pct)")
            connection.execute("CREATE INDEX ticks_hour_spread ON ticks(utc_hour,spread_price)")
            connection.execute("CREATE INDEX ticks_weekday_spread ON ticks(utc_weekday,spread_price)")
            summary = _stats(connection)
            candle_count, gaps = _write_sorted_ticks_and_bars(connection, temp)
            summary.update({"status": "imported", "broker": PROFILE.broker,
                            "account_type": PROFILE.account_type,
                            "symbol": PROFILE.mt5_symbol,
                            "source_file": ", ".join(path.name for path in paths),
                            "sources": sources, "input_rows": input_rows,
                            "duplicates_removed": duplicates,
                            "bid_15m_candles": candle_count,
                            "ask_15m_candles": candle_count,
                            "missing_15m_intervals": sum(g["missing_15m_intervals"] for g in gaps),
                            "gap_count": len(gaps),
                            "imported_at_utc": datetime.now(timezone.utc).isoformat()})
            report_temp = temp / "reports"
            _write_reports(summary, connection, report_temp, gaps)
        finally:
            connection.close()
        for name in ("btcusdm_ticks.csv", "btcusdm_bid_15m.csv", "btcusdm_ask_15m.csv"):
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
    ingest.add_argument("--source-timezone")
    ingest.add_argument("--timestamp-unit", choices=["s", "ms", "us", "ns"])
    args = parser.parse_args()
    if args.command == "inspect":
        for path in args.files:
            for schema in inspect_tick_source(path):
                print(json.dumps(asdict(schema), indent=2))
    else:
        result = import_tick_sources(args.files,
                                     TickColumns(args.timestamp_column, args.bid_column,
                                                 args.ask_column),
                                     source_timezone=args.source_timezone,
                                     timestamp_unit=args.timestamp_unit)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

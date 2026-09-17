"""Conservatively aggregate a documented Bitstamp one-minute archive to M15."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from services.bitstamp import latest_complete_candle_open
from services.history import CANONICAL_DATA_FILE
from utils.data_validation import load_ohlcv_csv, merge_ohlcv, save_ohlcv_csv, validate_ohlcv


ARCHIVE_URLS = (
    "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/historical/btcusd_bitstamp_1min_2012-2025.csv.gz",
    "https://raw.githubusercontent.com/ff137/bitstamp-btcusd-minute-data/main/data/updates/btcusd_bitstamp_1min_latest.csv",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _complete_bins(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    groups = rows.groupby(rows.timestamp.dt.floor("15min"), sort=True)
    result = groups.agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"),
        minutes=("timestamp", "size"), first=("timestamp", "first"),
        last=("timestamp", "last"),
    )
    valid = ((result["minutes"] == 15) & (result["first"] == result.index) &
             (result["last"] == result.index + pd.Timedelta(minutes=14)) &
             (result.volume > 0))
    result = result.loc[valid, ["open", "high", "low", "close", "volume"]]
    result.index.name = "timestamp"
    return result.reset_index()


def aggregate_archive(paths: list[Path], start: pd.Timestamp,
                      end: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Keep only complete 15-minute groups of valid, unique source minutes."""
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    parts = []
    carry = pd.DataFrame()
    source_rows = invalid_minutes = duplicate_minutes = 0
    for path in paths:
        for block in pd.read_csv(path, chunksize=250_000):
            block["timestamp"] = pd.to_datetime(block["timestamp"], unit="s", utc=True,
                                                 errors="coerce")
            block = block[block.timestamp.between(start, end + pd.Timedelta(minutes=14))]
            if block.empty:
                continue
            source_rows += len(block)
            numeric = block[["open", "high", "low", "close", "volume"]]
            valid = (block.timestamp.notna() &
                     np.isfinite(numeric).all(axis=1) &
                     (numeric[["open", "high", "low", "close"]] > 0).all(axis=1) &
                     (numeric.volume >= 0) &
                     (numeric.high >= numeric[["open", "close", "low"]].max(axis=1)) &
                     (numeric.low <= numeric[["open", "close", "high"]].min(axis=1)))
            invalid_minutes += int((~valid).sum())
            block = block.loc[valid]
            combined = pd.concat([carry, block], ignore_index=True)
            combined = combined.sort_values("timestamp", kind="stable")
            duplicate_minutes += int(combined.timestamp.duplicated().sum())
            combined = combined.drop_duplicates("timestamp", keep="last")
            final_bucket = combined.timestamp.iloc[-1].floor("15min")
            bucket = combined.timestamp.dt.floor("15min")
            ready = combined.loc[bucket < final_bucket]
            carry = combined.loc[bucket == final_bucket]
            if not ready.empty:
                parts.append(_complete_bins(ready))
    if not carry.empty:
        parts.append(_complete_bins(carry))
    aggregated = pd.concat(parts, ignore_index=True) if parts else _complete_bins(carry.iloc[0:0])
    aggregated = aggregated[aggregated.timestamp.between(start, end)].reset_index(drop=True)
    return aggregated, {
        "source_minutes_in_range": source_rows,
        "invalid_source_minutes": invalid_minutes,
        "duplicate_source_minutes_removed": duplicate_minutes,
        "complete_positive_volume_15m_candles": len(aggregated),
    }


def import_archive(historical: Path, updates: Path, *,
                   start: pd.Timestamp = pd.Timestamp("2021-01-01", tz="UTC"),
                   end: pd.Timestamp | None = None,
                   canonical: Path = CANONICAL_DATA_FILE,
                   provenance_path: Path | None = None,
                   dry_run: bool = False) -> dict:
    end = min(end if end is not None else latest_complete_candle_open(),
              latest_complete_candle_open())
    aggregated, details = aggregate_archive([historical, updates], start, end)
    existing = load_ohlcv_csv(canonical) if canonical.exists() else pd.DataFrame()
    overlap = aggregated.merge(existing, on="timestamp", suffixes=("_archive", "_saved"))
    api_overlap = overlap[overlap.timestamp >= pd.Timestamp("2025-01-07", tz="UTC")]
    mismatch_counts = {}
    for column in ("open", "high", "low", "close"):
        different = ~np.isclose(overlap[f"{column}_archive"],
                                overlap[f"{column}_saved"], rtol=0, atol=1e-8)
        mismatch_counts[column] = int(different.sum())
        if different[overlap.timestamp >= pd.Timestamp("2025-01-07", tz="UTC")].any():
            raise ValueError(f"API-derived archive disagrees with saved {column} values.")
    mismatch_counts["volume"] = int((~np.isclose(overlap.volume_archive,
                                                 overlap.volume_saved,
                                                 rtol=0, atol=1e-6)).sum())
    if not np.allclose(api_overlap.volume_archive, api_overlap.volume_saved,
                       rtol=0, atol=1e-6):
        raise ValueError("API-derived archive volume disagrees with saved candles.")
    combined = merge_ohlcv(aggregated, existing)  # Saved canonical rows win on overlap.
    quality = validate_ohlcv(combined)
    if quality.invalid_ohlcv_rows:
        raise ValueError("Derived archive contains invalid OHLCV rows.")
    record = {
        "source": "ff137/bitstamp-btcusd-minute-data public archive",
        "source_urls": ARCHIVE_URLS,
        "source_license_note": "Historical bulk is Kaggle-derived CC BY-SA 4.0; recent updates are Bitstamp API-derived CC BY 4.0.",
        "historical_sha256": _sha256(historical),
        "updates_sha256": _sha256(updates),
        "aggregation": "Only 15 unique valid one-minute rows with positive total volume; no empty or incomplete bins synthesized.",
        "overlap_checked": len(overlap),
        "api_derived_overlap_checked": len(api_overlap),
        "api_derived_overlap_ohlcv_match": True,
        "older_bulk_overlap_mismatch_counts": mismatch_counts,
        "overlap_resolution": "Saved canonical candles take precedence over archive rows.",
        **details,
        "saved_15m_candles": len(combined),
        "saved_first": str(quality.first_candle),
        "saved_last": str(quality.last_candle),
        "saved_missing_candles": quality.missing_candles,
        "dry_run": dry_run,
    }
    if not dry_run:
        save_ohlcv_csv(combined, canonical)
        destination = provenance_path or canonical.parent / "btcusd_15m_provenance.json"
        destination.write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical", type=Path)
    parser.add_argument("updates", type=Path)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(import_archive(args.historical, args.updates,
                                    start=pd.Timestamp(args.start, tz="UTC"),
                                    dry_run=args.dry_run), indent=2))

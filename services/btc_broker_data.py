"""Phase R1 — broker-native Exness BTCUSDm dataset ingestion and validation.

Generalizes the Gold Phase 2A pipeline (services/gold_data.py plus the
data/exness/gold/phase2a manifest) to BTCUSDm. All heavy lifting reuses the
generic validators in utils/data_validation.py and the fingerprint helpers in
core/fingerprints.py; nothing here duplicates that machinery.

Integrity rules enforced by this module:

* Raw exports are never rewritten. Reading is read-only; canonicalization is
  written to a separate processed/ directory.
* Nothing is repaired silently. Invalid rows are reported and, where a
  dataset cannot be trusted, ingestion raises rather than patching.
* A manifest can only be built when the real broker spec, M15 and H1 exports
  all exist. Missing inputs produce a blocked status, never inferred values.
* Leverage, commission and margin stay UNVERIFIED regardless of what the MT5
  capture happens to contain: a zero capture is not a true zero.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

from core.fingerprints import sha256_file, stable_fingerprint
from utils.data_validation import continuous_segments, invalid_ohlcv_mask, missing_gaps

ROOT = Path(__file__).resolve().parents[1]
PHASE_R1 = ROOT / "data" / "exness" / "btc" / "phase_r1"
RAW_DIR = PHASE_R1 / "raw"
PROCESSED_DIR = PHASE_R1 / "processed"
MANIFEST_PATH = PHASE_R1 / "manifest.json"

PROFILE_ID = "EXNESS-BTCUSD-v1"
SYMBOL = "BTCUSDm"
INSTRUMENT = "BTCUSD"
TIMEFRAME_MINUTES = {"M15": 15, "H1": 60}

#: Expected filenames produced by mt5/Export_BTCUSD_Spec.mq5 and
#: mt5/Export_BTCUSD_History.mq5.
SPEC_FILE = "btcusd_mt5_spec.json"
M15_FILE = f"btcusd_{SYMBOL}_M15.csv"
H1_FILE = f"btcusd_{SYMBOL}_H1.csv"

#: Five real BTCUSDm tick samples already in the repository. They are referenced
#: as external replay assets, never merged into the candle datasets.
TICK_SAMPLE_DIR = ROOT / "data" / "exness" / "processed"

#: MT5 terminal "Save as CSV" bar dump (tab separated).
TERMINAL_COLUMNS = ("<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>",
                    "<TICKVOL>", "<VOL>", "<SPREAD>")
#: mt5/Export_BTCUSD_History.mq5 output (comma separated).
EXPORTER_COLUMNS = ("timestamp", "open", "high", "low", "close",
                    "tick_volume", "spread", "real_volume")

CANONICAL_COLUMNS = ["timestamp_utc", "open", "high", "low", "close",
                     "tick_volume", "real_volume", "spread_points", "spread_price"]


class BrokerDataError(ValueError):
    """Raised when a broker export cannot be trusted. Never caught silently."""


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------


def read_broker_ohlcv(path: str | Path, *, point: float) -> pd.DataFrame:
    """Read either supported BTCUSDm export layout into the canonical frame.

    Exness server wall time is UTC+0, so server timestamps are labelled UTC
    without shifting them. Rows are never sorted or repaired here; ordering
    problems are surfaced by ``validate_candles``.
    """
    path = Path(path)
    if point <= 0:
        raise BrokerDataError("point size must be positive.")
    head = path.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    if not head:
        raise BrokerDataError(f"{path.name} is empty.")
    if head[0].startswith("<DATE>"):
        raw = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
        if tuple(raw.columns) != TERMINAL_COLUMNS:
            raise BrokerDataError(f"Unexpected MT5 terminal schema: {tuple(raw.columns)}")
        stamps = pd.to_datetime(raw["<DATE>"] + " " + raw["<TIME>"],
                                format="%Y.%m.%d %H:%M:%S", utc=True, errors="coerce")
        numbers = raw[list(TERMINAL_COLUMNS[2:])].apply(pd.to_numeric, errors="coerce")
        frame = pd.DataFrame({
            "timestamp_utc": stamps, "open": numbers["<OPEN>"], "high": numbers["<HIGH>"],
            "low": numbers["<LOW>"], "close": numbers["<CLOSE>"],
            "tick_volume": numbers["<TICKVOL>"], "real_volume": numbers["<VOL>"],
            "spread_points": numbers["<SPREAD>"]})
        layout = "MT5_TERMINAL_CSV_DUMP"
    else:
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
        missing = [name for name in EXPORTER_COLUMNS if name not in raw.columns]
        if missing:
            raise BrokerDataError(f"{path.name} is missing columns: {missing}")
        stamps = pd.to_datetime(raw["timestamp"], format="%Y.%m.%d %H:%M:%S",
                                utc=True, errors="coerce")
        numeric = ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]
        numbers = raw[numeric].apply(pd.to_numeric, errors="coerce")
        frame = pd.DataFrame({
            "timestamp_utc": stamps, "open": numbers["open"], "high": numbers["high"],
            "low": numbers["low"], "close": numbers["close"],
            "tick_volume": numbers["tick_volume"], "real_volume": numbers["real_volume"],
            "spread_points": numbers["spread"]})
        layout = "MT5_EXPORTER_CSV"
    frame["spread_price"] = frame.spread_points * point
    frame.attrs["layout"] = layout
    frame.attrs["source_file"] = path.name
    frame.attrs["source_sha256"] = sha256_file(path)
    return frame[CANONICAL_COLUMNS]


# ---------------------------------------------------------------------------
# R1.5 validation
# ---------------------------------------------------------------------------


def validate_candles(frame: pd.DataFrame, *, timeframe: str) -> dict[str, Any]:
    """Every R1.5 check. Reports problems; never repairs the source."""
    if timeframe not in TIMEFRAME_MINUTES:
        raise BrokerDataError("timeframe must be M15 or H1")
    step_minutes = TIMEFRAME_MINUTES[timeframe]
    stamps = frame.timestamp_utc
    check = frame.rename(columns={"timestamp_utc": "timestamp", "tick_volume": "volume"})

    numeric_columns = ["open", "high", "low", "close", "tick_volume",
                       "real_volume", "spread_points"]
    non_numeric = int(frame[numeric_columns].isna().any(axis=1).sum())
    invalid_ohlc = int(invalid_ohlcv_mask(check).sum())
    off_grid = int((stamps.isna()
                    | (stamps.dt.minute % step_minutes != 0)
                    | (stamps.dt.second != 0)).sum())

    report = {
        "timeframe": timeframe,
        "rows": int(len(frame)),
        "first_timestamp_utc": None if stamps.empty else stamps.iloc[0].isoformat(),
        "last_timestamp_utc": None if stamps.empty else stamps.iloc[-1].isoformat(),
        "timestamps_monotonic_increasing": bool(stamps.is_monotonic_increasing),
        "unparsable_timestamps": int(stamps.isna().sum()),
        "duplicate_timestamps": int(stamps.duplicated().sum()),
        "duplicate_full_rows": int(frame.duplicated().sum()),
        "invalid_ohlc_rows": invalid_ohlc,
        "non_numeric_rows": non_numeric,
        "off_grid_timestamps": off_grid,
        "negative_spread_rows": int((frame.spread_points < 0).sum()),
        "zero_spread_rows": int((frame.spread_points == 0).sum()),
        "negative_tick_volume_rows": int((frame.tick_volume < 0).sum()),
        "zero_tick_volume_rows": int((frame.tick_volume == 0).sum()),
        "negative_real_volume_rows": int((frame.real_volume < 0).sum()),
        "timezone_basis": "Exness trade-server wall time treated as UTC+0",
    }
    report["segments"] = segment_report(frame, timeframe=timeframe)
    report["passed"] = bool(
        report["timestamps_monotonic_increasing"]
        and report["unparsable_timestamps"] == 0
        and report["duplicate_timestamps"] == 0
        and report["invalid_ohlc_rows"] == 0
        and report["non_numeric_rows"] == 0
        and report["off_grid_timestamps"] == 0
        and report["negative_spread_rows"] == 0
        and report["negative_tick_volume_rows"] == 0
        and report["negative_real_volume_rows"] == 0
    )
    return report


def segment_report(frame: pd.DataFrame, *, timeframe: str) -> dict[str, Any]:
    """Continuity structure: segment count, sizes and the gap distribution."""
    step_minutes = TIMEFRAME_MINUTES[timeframe]
    check = frame.rename(columns={"timestamp_utc": "timestamp"})
    segments = continuous_segments(check, step_seconds=step_minutes * 60)
    gaps = missing_gaps(check, step_seconds=step_minutes * 60)
    lengths = sorted(segment.candles for segment in segments)
    missing = [gap.missing_candles for gap in gaps]
    buckets = {"1": 0, "2-4": 0, "5-16": 0, "17-96": 0, "97+": 0}
    for count in missing:
        if count == 1:
            buckets["1"] += 1
        elif count <= 4:
            buckets["2-4"] += 1
        elif count <= 16:
            buckets["5-16"] += 1
        elif count <= 96:
            buckets["17-96"] += 1
        else:
            buckets["97+"] += 1
    return {
        "continuous_segments": len(segments),
        "largest_segment_candles": max(lengths, default=0),
        "median_segment_candles": float(median(lengths)) if lengths else 0.0,
        "smallest_segment_candles": min(lengths, default=0),
        "gap_count": len(gaps),
        "missing_candles": int(sum(missing)),
        "largest_gap_candles": max(missing, default=0),
        "gap_size_distribution": buckets,
    }


# ---------------------------------------------------------------------------
# R1.6 M15 <-> H1 reconciliation
# ---------------------------------------------------------------------------


def reconcile_m15_h1(m15: pd.DataFrame, h1: pd.DataFrame, *,
                     tolerance: float = 1e-9) -> dict[str, Any]:
    """Aggregate every complete four-bar M15 group and compare to broker H1.

    Only groups with all four M15 bars present are compared; an incomplete
    group is reported separately rather than being compared against a partial
    aggregate. Both feeds carry the same server-time basis, so the H1 bar
    stamped ``HH:00`` is compared with the M15 bars stamped ``HH:00..HH:45``.
    """
    left = m15.copy()
    left["hour"] = left.timestamp_utc.dt.floor("h")
    grouped = left.groupby("hour")
    aggregated = grouped.agg(
        bars=("timestamp_utc", "size"),
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
    ).reset_index()

    complete = aggregated.loc[aggregated.bars == 4].copy()
    incomplete = int((aggregated.bars != 4).sum())
    merged = complete.merge(h1, left_on="hour", right_on="timestamp_utc",
                            how="inner", suffixes=("_m15", "_h1"))

    mismatches = []
    for row in merged.itertuples(index=False):
        deltas = {field: abs(getattr(row, f"{field}_m15") - getattr(row, f"{field}_h1"))
                  for field in ("open", "high", "low", "close")}
        worst = max(deltas.values())
        if worst > tolerance:
            mismatches.append({"hour_utc": row.hour.isoformat(),
                               "max_absolute_difference": float(worst),
                               **{f"{k}_difference": float(v) for k, v in deltas.items()}})
    magnitudes = [item["max_absolute_difference"] for item in mismatches]
    return {
        "h1_bars": int(len(h1)),
        "m15_hour_groups": int(len(aggregated)),
        "complete_m15_groups": int(len(complete)),
        "incomplete_m15_groups_not_checkable": incomplete,
        "groups_compared": int(len(merged)),
        "h1_bars_without_a_complete_m15_group": int(len(h1) - len(merged)),
        "matches": int(len(merged) - len(mismatches)),
        "mismatches": len(mismatches),
        "mismatch_magnitude": {
            "max": float(max(magnitudes)) if magnitudes else 0.0,
            "median": float(median(magnitudes)) if magnitudes else 0.0,
        },
        "mismatch_timestamps": [item["hour_utc"] for item in mismatches[:50]],
        "mismatch_details": mismatches[:50],
        "mismatch_details_truncated": len(mismatches) > 50,
        "tolerance": tolerance,
        "aggregation": "open=first M15 open, high=max M15 high, low=min M15 low, close=last M15 close",
    }


# ---------------------------------------------------------------------------
# R1.7 spread analysis
# ---------------------------------------------------------------------------


def _distribution(series: pd.Series) -> dict[str, float]:
    clean = series.dropna()
    if clean.empty:
        return {}
    return {"min": float(clean.min()), "p25": float(clean.quantile(.25)),
            "median": float(clean.median()), "mean": float(clean.mean()),
            "p75": float(clean.quantile(.75)), "p90": float(clean.quantile(.90)),
            "p95": float(clean.quantile(.95)), "p99": float(clean.quantile(.99)),
            "max": float(clean.max())}


def spread_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "spread_points": _distribution(frame.spread_points),
        "spread_price": _distribution(frame.spread_price),
        "unique_spread_points": int(frame.spread_points.nunique()),
        "formula": "spread_price = spread_points * point",
        "semantics": ("MT5 bar spread is a bar-level spread descriptor, not the spread "
                      "guaranteed at an execution tick."),
    }


# ---------------------------------------------------------------------------
# R1.8 external tick-sample replay assets
# ---------------------------------------------------------------------------


def tick_sample_assets(directory: Path = TICK_SAMPLE_DIR) -> list[dict[str, Any]]:
    """Fingerprint and summarize the five real tick samples, without merging them."""
    assets = []
    for path in sorted(directory.glob("btcusdm_s*_ticks_server_time.csv")):
        sample_id = path.name.split("_")[1]
        stamps = pd.read_csv(path, usecols=["timestamp_server"]).timestamp_server
        parsed = pd.to_datetime(stamps, format="mixed", utc=True)
        assets.append({
            "sample_id": sample_id, "file": path.name,
            "sha256": sha256_file(path), "ticks": int(len(parsed)),
            "first_timestamp_utc": parsed.iloc[0].isoformat(),
            "last_timestamp_utc": parsed.iloc[-1].isoformat(),
        })
    return assets


# ---------------------------------------------------------------------------
# specification
# ---------------------------------------------------------------------------


def load_btc_spec(path: str | Path) -> dict[str, Any]:
    """Load the MT5 BTCUSDm specification snapshot, refusing anything unsafe."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if any(key in payload for key in ("password", "login", "account_password")):
        raise BrokerDataError("Credential fields are not allowed in broker snapshots.")
    symbol = payload.get("symbol")
    name = symbol.get("name") if isinstance(symbol, dict) else symbol
    if name not in {"BTCUSD", "BTCUSDm"}:
        raise BrokerDataError("Snapshot symbol must be BTCUSD or BTCUSDm.")
    point = float((payload.get("symbol") or {}).get("point") or 0.0)
    if point <= 0:
        raise BrokerDataError("Specification must carry a positive point size.")
    payload["profile_id"] = PROFILE_ID
    # Never let a captured zero masquerade as a verified economic assumption.
    payload["unverified"] = {
        **(payload.get("unverified") or {}),
        "leverage_status": "UNVERIFIED",
        "commission_status": "UNVERIFIED",
        "margin_status": "UNVERIFIED",
    }
    return payload


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PhaseR1Inputs:
    spec: Path
    m15: Path
    h1: Path

    @property
    def missing(self) -> list[str]:
        return [label for label, path in (("spec", self.spec), ("M15", self.m15), ("H1", self.h1))
                if not path.exists()]

    @property
    def ready(self) -> bool:
        return not self.missing


def phase_r1_inputs(raw_dir: Path = RAW_DIR) -> PhaseR1Inputs:
    return PhaseR1Inputs(spec=raw_dir / SPEC_FILE, m15=raw_dir / M15_FILE, h1=raw_dir / H1_FILE)


def phase_r1_status(raw_dir: Path = RAW_DIR) -> dict[str, Any]:
    """What exists and what is still required. Never infers a missing export."""
    inputs = phase_r1_inputs(raw_dir)
    return {
        "raw_directory": str(raw_dir),
        "required_files": {"spec": SPEC_FILE, "M15": M15_FILE, "H1": H1_FILE},
        "present": {label: path.exists() for label, path in
                    (("spec", inputs.spec), ("M15", inputs.m15), ("H1", inputs.h1))},
        "missing": inputs.missing,
        "ready": inputs.ready,
        "gate": ("READY" if inputs.ready else
                 "BLOCKED — a real MT5 export is required; no value may be inferred."),
    }


# ---------------------------------------------------------------------------
# R1.4 + R1.8 manifest
# ---------------------------------------------------------------------------


def build_phase_r1(raw_dir: Path = RAW_DIR, processed_dir: Path = PROCESSED_DIR,
                   manifest_path: Path = MANIFEST_PATH) -> dict[str, Any]:
    """Ingest, validate, reconcile, fingerprint and write the Phase R1 manifest.

    Refuses to run unless the real spec, M15 and H1 exports all exist: a partial
    Phase R1 result would be indistinguishable from an inferred one.
    """
    inputs = phase_r1_inputs(raw_dir)
    if not inputs.ready:
        raise BrokerDataError(
            f"Phase R1 requires real MT5 exports; missing: {', '.join(inputs.missing)}. "
            "Run mt5/Export_BTCUSD_Spec.mq5 and mt5/Export_BTCUSD_History.mq5 first.")

    spec = load_btc_spec(inputs.spec)
    point = float(spec["symbol"]["point"])
    digits = int(spec["symbol"]["digits"])

    m15 = read_broker_ohlcv(inputs.m15, point=point)
    h1 = read_broker_ohlcv(inputs.h1, point=point)
    m15_validation = validate_candles(m15, timeframe="M15")
    h1_validation = validate_candles(h1, timeframe="H1")
    for label, report in (("M15", m15_validation), ("H1", h1_validation)):
        if not report["passed"]:
            raise BrokerDataError(f"{label} export failed validation: {report}")

    processed_dir.mkdir(parents=True, exist_ok=True)
    m15_out = processed_dir / f"btcusdm_M15.csv"
    h1_out = processed_dir / f"btcusdm_H1.csv"
    m15.to_csv(m15_out, index=False)
    h1.to_csv(h1_out, index=False)

    manifest = {
        "schema_version": "1.0",
        "phase": "R1 — Exness BTCUSDm broker-native dataset",
        "profile_id": PROFILE_ID,
        "instrument": INSTRUMENT,
        "symbol": SYMBOL,
        "broker": (spec.get("broker") or {}).get("company"),
        "server": (spec.get("broker") or {}).get("server"),
        "source_timezone": "Exness trade-server wall time treated as UTC+0",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "specification": {
            "digits": digits, "point": point,
            "tick_size": (spec.get("contract") or {}).get("tick_size"),
            "tick_value": (spec.get("contract") or {}).get("tick_value"),
            "contract_size": (spec.get("contract") or {}).get("contract_size"),
            "minimum_volume": (spec.get("volume") or {}).get("minimum"),
            "maximum_volume": (spec.get("volume") or {}).get("maximum"),
            "volume_step": (spec.get("volume") or {}).get("step"),
            "currency_profit": (spec.get("symbol") or {}).get("currency_profit"),
            "currency_margin": (spec.get("symbol") or {}).get("currency_margin"),
            "trade_mode": (spec.get("trading") or {}).get("trade_mode_name"),
            "filling_modes": (spec.get("trading") or {}).get("filling_modes"),
            "current_spread_points": (spec.get("quote") or {}).get("spread_points"),
            "leverage_status": "UNVERIFIED",
            "commission_status": "UNVERIFIED",
            "margin_status": "UNVERIFIED; a zero capture does not imply zero true margin",
        },
        "datasets": {
            "M15": {**m15_validation, "spread": spread_statistics(m15)},
            "H1": {**h1_validation, "spread": spread_statistics(h1)},
        },
        "alignment": reconcile_m15_h1(m15, h1),
        "external_replay_assets": {
            "description": ("Five real BTCUSDm tick samples, referenced for execution replay. "
                            "They are never merged into the candle datasets."),
            "samples": tick_sample_assets(),
        },
        "fingerprints": {
            "raw_spec_sha256": sha256_file(inputs.spec),
            "raw_m15_sha256": sha256_file(inputs.m15),
            "raw_h1_sha256": sha256_file(inputs.h1),
            "processed_m15_sha256": sha256_file(m15_out),
            "processed_h1_sha256": sha256_file(h1_out),
            "instrument_profile_sha256": sha256_file(ROOT / "instruments" / "btcusd.py"),
            "broker_profile_sha256": sha256_file(ROOT / "brokers" / "exness_standard_btcusdm.py"),
        },
        "raw_files_preserved": True,
    }
    manifest["fingerprints"]["manifest_sha256"] = stable_fingerprint(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
                             encoding="utf-8")
    return manifest


if __name__ == "__main__":
    status = phase_r1_status()
    print(json.dumps(status, indent=2))
    if status["ready"]:
        print(json.dumps(build_phase_r1(), indent=2, default=str))

"""Immutable manifest for the frozen standalone Setup A research candidate."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import time
from enum import Enum
from pathlib import Path

from research.exness_setup_a_validation import SETTINGS
from strategies.btc_v2_setup_a import SETUP_ID, SetupAParameters


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/setup_a/v1_candidate"
FROZEN_FILE = REPORT / "frozen_strategy.json"
SOURCE_COMMIT = "f4a62662368b01519bf32e1345bdff8493cff342"
SOURCE_TAG = "btc-setup-a-long-history-v1.0"
SOURCE_FILES = (
    "reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine",
    "strategies/btc_v2_setup_a.py",
    "strategies/confirmed_h1.py",
    "strategies/pine_indicators.py",
    "strategies/btc_v2_setup_b.py",  # Shared, audited Pine risk state.
    "engine/backtester.py",
    "engine/execution.py",
)


def _plain(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, time):
        return value.isoformat(timespec="minutes")
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def canonical_bytes(document: dict) -> bytes:
    """Stable UTF-8 encoding, excluding only the self-referential hash field."""
    content = {key: value for key, value in document.items() if key != "freeze_hash_sha256"}
    return json.dumps(content, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def freeze_hash(document: dict) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def expected_manifest() -> dict:
    params = _plain(asdict(SetupAParameters()))
    settings = _plain(asdict(SETTINGS))
    checksums = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                 for path in SOURCE_FILES}
    document = {
        "strategy_name": "BTC Setup A V1 Research Candidate",
        "candidate_version": "1.0",
        "pine_strategy_title": "BTC Pullback + Trend Breakout 3R — V2.2.0",
        "pine_version": "2.2.0",
        "setup_id": SETUP_ID,
        "setup_a_enabled": True,
        "setup_b_enabled": False,
        "volatility_gate_enabled": False,
        "symbol_assumption": "BTCUSDm Exness Bid M15; Bitstamp BTC/USD is cross-feed evidence",
        "signal_timeframe": "15m UTC",
        "confirmed_trend_timeframe": "1h UTC",
        "position_model": "one filled position or pending entry at a time; no pyramiding",
        "target_model": "fixed 3R from actual fill to structural stop",
        "strategy_parameters": params,
        "audited_research_execution": settings,
        "source_commit": SOURCE_COMMIT,
        "source_tag": SOURCE_TAG,
        "source_files_sha256": checksums,
        "status": "RESEARCH FROZEN",
        "live_approved": False,
        "next_required_stage": "MT5 / Exness forward or demo execution validation",
    }
    document["freeze_hash_sha256"] = freeze_hash(document)
    return document


def validate_frozen(path: Path = FROZEN_FILE) -> dict:
    document = json.loads(path.read_text())
    if document.get("freeze_hash_sha256") != freeze_hash(document):
        raise ValueError("Setup A V1 freeze hash mismatch: manifest was changed.")
    if document != expected_manifest():
        raise ValueError("Setup A V1 manifest no longer matches frozen defaults or source files.")
    return document


def write_once(path: Path = FROZEN_FILE) -> dict:
    """Create a freeze or verify it; never silently overwrite a prior freeze."""
    if path.exists():
        return validate_frozen(path)
    document = expected_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(document, stream, sort_keys=True, indent=2, ensure_ascii=False)
        stream.write("\n")
    return document


if __name__ == "__main__":
    print(write_once()["freeze_hash_sha256"])

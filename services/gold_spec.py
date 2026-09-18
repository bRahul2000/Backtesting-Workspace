from __future__ import annotations

import json
from pathlib import Path


PROFILE_ID = "EXNESS-XAUUSD-v1"


def load_mt5_gold_snapshot(path: str | Path) -> dict:
    """Load and validate a non-secret MT5 XAUUSD specification snapshot."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("profile_id") != PROFILE_ID:
        raise ValueError(f"Expected profile_id {PROFILE_ID!r}.")
    if payload.get("symbol") not in {"XAUUSD", "XAUUSDm"}:
        raise ValueError("Snapshot symbol must be XAUUSD or XAUUSDm.")
    if any(key in payload for key in ("password", "login", "account_password")):
        raise ValueError("Credential fields are not allowed in broker snapshots.")
    return payload
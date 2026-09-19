from __future__ import annotations

import json
from pathlib import Path


PROFILE_ID = "EXNESS-XAUUSD-v1"


def load_mt5_gold_snapshot(path: str | Path) -> dict:
    """Load and validate a non-secret MT5 XAUUSD specification snapshot."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    symbol = payload.get("symbol", {})
    if isinstance(symbol, str):
        if symbol not in {"XAUUSD", "XAUUSDm"}:
            raise ValueError("Snapshot symbol must be XAUUSD or XAUUSDm.")
        if any(key in payload for key in ("password", "login", "account_password")):
            raise ValueError("Credential fields are not allowed in broker snapshots.")
        return payload
    if not isinstance(symbol, dict) or symbol.get("name") not in {"XAUUSD", "XAUUSDm"}:
        raise ValueError("Snapshot symbol must be XAUUSD or XAUUSDm.")
    if payload.get("broker", {}).get("company") != "Exness Technologies Ltd":
        raise ValueError("Snapshot broker company is not the expected Exness identity.")
    payload["profile_id"] = PROFILE_ID
    if any(key in payload for key in ("password", "login", "account_password")):
        raise ValueError("Credential fields are not allowed in broker snapshots.")
    return payload
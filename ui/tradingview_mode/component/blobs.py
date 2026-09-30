"""Send heavy payload arrays once, not on every rerun.

A Streamlit component receives its whole argument payload on every run, so before this module every click (a tab, an
indicator toggle, a live poll) re-sent every bar and every indicator/Pine series: 0.2-6 MB per event (measured,
beta/PRIVATE_BETA_LOG.md PB-002). Now each large array is stored once as a content-addressed JSON file in Streamlit's
media store and the payload carries a small marker instead:

    [..., a, b]   ->   {"$blob": "/media/<content hash>.json", "tail": [a, b]}
    other large value (a strategy catalog, a script source)   ->   {"$json": "/media/<content hash>.json"}

The frontend (frontend/src/blobs.js) fetches a URL once, keeps it by URL (= by content), and rebuilds the identical
value as ``fetched + tail`` before rendering - so rendering code sees exactly the payload Python validated. The last
TAIL items travel inline: in Live only the forming bar changes, so the stored base stays the same file and is not
fetched again every second.

Each array position is one media "slot" per session: storing a new version replaces the previous file, which
Streamlit then deletes, so memory stays bounded even across fragment-only reruns. Without a Streamlit runtime (tests,
bare mode) the payload is returned unchanged.
"""
from __future__ import annotations

import json

MIN_ITEMS = 64          # shorter arrays stay inline (their marker would not save anything)
MIN_BYTES = 16 * 1024   # ... and so do small ones (e.g. the log list), which change often and cost little
TAIL = 2                # items sent inline on every run (the live forming bar and the one before it)
COORD_PREFIX = "zf-blob"


def _media_add():
    try:
        from streamlit import runtime
        if not runtime.exists():
            return None
        manager = runtime.get_instance().media_file_mgr
    except Exception:  # noqa: BLE001 - no runtime (tests / bare mode): stay inline
        return None

    def add(data: bytes, coordinates: str) -> str:
        return manager.add(data, "application/json", coordinates)
    return add


def externalize(payload: dict, add=None, *, min_items: int = MIN_ITEMS, min_bytes: int = MIN_BYTES,
                tail: int = TAIL) -> dict:
    """Return a copy of payload where large values are stored as files:

    * a list of >= min_items items (>= min_bytes) -> {"$blob": url, "tail": [last items, inline]}
    * any other value still >= min_bytes after its own children were stored -> {"$json": url}

    Children go first, so a large static part (a strategy catalog, a Pine source) is stored on its own and stays the
    same file while a small changing neighbour (a live value) travels inline."""
    add = add if add is not None else _media_add()
    if add is None:
        return payload

    def dumps(value) -> bytes:
        return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")

    def walk(value, path: str):
        if isinstance(value, list) and len(value) >= min_items:
            base, rest = value[:len(value) - tail], value[len(value) - tail:]
            data = dumps(base)
            if len(data) >= min_bytes:
                return {"$blob": add(data, f"{COORD_PREFIX}{path}"),
                        "tail": [walk(item, f"{path}.t{index}") for index, item in enumerate(rest)]}
        if isinstance(value, dict):
            value = {key: walk(item, f"{path}.{key}") for key, item in value.items()}
        elif isinstance(value, list):
            value = [walk(item, f"{path}.{index}") for index, item in enumerate(value)]
        elif not isinstance(value, str):
            return value
        data = dumps(value)
        if len(data) >= min_bytes:
            return {"$json": add(data, f"{COORD_PREFIX}{path}")}
        return value

    return {key: (value if key in ("ack", "contract") else walk(value, f":{key}")) for key, value in payload.items()}


def hydrate(value, fetch):
    """Python twin of frontend/src/blobs.js (tests): rebuild the original payload from markers."""
    if isinstance(value, dict):
        if "$blob" in value and set(value) <= {"$blob", "tail"}:
            return hydrate(fetch(value["$blob"]), fetch) + [hydrate(item, fetch) for item in value.get("tail", [])]
        if set(value) == {"$json"}:
            return hydrate(fetch(value["$json"]), fetch)
        return {key: hydrate(item, fetch) for key, item in value.items()}
    if isinstance(value, list):
        return [hydrate(item, fetch) for item in value]
    return value

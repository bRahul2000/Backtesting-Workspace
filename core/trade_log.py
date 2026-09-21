"""Timestamp serialization for the trade log.

``UniversalBacktestResult.trade_log`` is a list of plain dicts: it is rendered
in the Trades tab, exported as CSV, persisted into the experiment ledger as
JSON, and read back by research code. Timestamps therefore have to survive a
round trip through JSON in a form a human can read.

They did not. ``_trade_row`` unwrapped any value exposing ``.value`` — intended
for Direction and the other enums — before its ``isinstance(value, pd.Timestamp)``
branch could run, and ``pd.Timestamp.value`` is epoch nanoseconds. Every trade
timestamp was written as an integer such as ``1701569700000000000`` and the
Timestamp branch was unreachable.

Records written before the fix are still in the ledger, so ``parse_timestamp``
accepts both forms. Nanoseconds are the only legacy encoding that ever existed
here, which is why an integer is read as nanoseconds and nothing else is guessed.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

#--- Everything this engine produces is UTC; the suffix is kept explicit so a
#--- reader never has to assume it.
UTC = "UTC"


def to_timestamp(value: Any) -> pd.Timestamp:
    """Read a trade-log timestamp in either encoding, as an aware UTC Timestamp.

    Accepts the ISO-8601 text written now, the epoch-nanosecond integers written
    before the fix, and the pd.Timestamp/datetime objects held in memory.
    """
    if value is None:
        raise ValueError("Trade-log timestamp is missing.")
    if isinstance(value, bool):
        raise TypeError(f"Not a timestamp: {value!r}")
    if isinstance(value, (pd.Timestamp, datetime)):
        stamp = pd.Timestamp(value)
    elif isinstance(value, (int, float)):
        stamp = pd.Timestamp(int(value), unit="ns")
    elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
        #--- A ledger round trip through json.dumps(default=str) turns a legacy
        #--- integer into a string of digits. Same encoding, same reading.
        stamp = pd.Timestamp(int(value.strip()), unit="ns")
    elif isinstance(value, str):
        stamp = pd.Timestamp(value)
    else:
        raise TypeError(f"Not a timestamp: {value!r}")
    return stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)


def serialize_timestamp(value: Any) -> Any:
    """Write a trade-log timestamp as stable, human-readable UTC ISO-8601 text.

    ``None`` passes through: several Trade timestamp fields are genuinely
    optional and an absent excursion time is not the same as a missing one.
    """
    if value is None:
        return None
    return to_timestamp(value).isoformat()


def timestamp_text(value: Any) -> Any:
    """Best-effort display text: never raises, so one odd row cannot blank a table."""
    try:
        return serialize_timestamp(value)
    except (TypeError, ValueError):
        return value


def timestamp_series(values: Any) -> pd.Series:
    """Parse a column of trade-log timestamps in either encoding.

    ``pd.to_datetime(..., utc=True)`` already reads both, so research code that
    goes through it needed no change; this exists for the display paths that
    handle one value at a time.
    """
    return pd.to_datetime(pd.Series(list(values)), utc=True)

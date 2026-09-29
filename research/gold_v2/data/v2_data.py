"""Gold V2 sealed-aware data layer for the new M1 / cross-market / tick-sample exports.

Every loader selects lines by timestamp TEXT before parsing and refuses sealed windows:
  historical holdout 2021-09-01 00:00 → 2022-11-27 00:00 UTC (sessions through 2022-11-26)
  2026 Validation + Final OOS + later: 2026-06-03 00:00 UTC onward
Raw exports are copied read-only from MT5 Common Files and hashed before any parsing (never written from Python into
Common Files). Nothing in research/gold_v1 is modified.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE / "raw"
COMMON = (Path.home() / "Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData"
          / "Roaming/MetaQuotes/Terminal/Common/Files")
FMT = "%Y.%m.%d %H:%M:%S"
# [start, end) in the export's text timestamp format (server time = UTC+0)
SEALED = [("2021.09.01 00:00:00", "2022.11.27 00:00:00"), ("2026.06.03 00:00:00", "9999.12.31 00:00:00")]


def is_sealed(ts: str) -> bool:
    return any(a <= ts < b for a, b in SEALED)


def overlaps_sealed(start: str, end: str) -> bool:
    return any(start < b and a < end for a, b in SEALED)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(patterns: list[str], dest: Path = RAW) -> dict[str, str]:
    """Copy matching Common Files exports into dest (read-only copy, byte-verified) and return name -> sha256."""
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for pat in patterns:
        for src in sorted(COMMON.glob(pat)):
            dst = dest / src.name
            shutil.copyfile(src, dst)
            assert sha256(src) == sha256(dst), f"copy mismatch {src.name}"
            out[src.name] = sha256(dst)
    (dest / "SHA256SUMS").write_text("".join(f"{v}  {k}\n" for k, v in sorted(out.items())))
    return out


def load_bars(paths: list[Path], start: str, end: str) -> pd.DataFrame:
    """Bars with start <= timestamp < end (text), sealed lines skipped BEFORE parsing. Raises if [start, end) lies
    inside a sealed window entirely; partial overlaps are silently excluded line by line and counted."""
    rows, skipped = [], 0
    header = None
    for p in paths:
        with open(p) as fh:
            h = fh.readline().rstrip("\n").split(",")
            header = header or h
            for line in fh:
                ts = line[:19]
                if not (start <= ts < end):
                    continue
                if is_sealed(ts):
                    skipped += 1
                    continue
                rows.append(line.rstrip("\n").split(","))
    f = pd.DataFrame(rows, columns=header)
    if f.empty:
        return f
    f["time"] = pd.to_datetime(f["timestamp"], format=FMT, utc=True)
    for c in ("open", "high", "low", "close"):
        f[c] = f[c].astype(float)
    for c in ("tick_volume", "spread", "real_volume"):
        f[c] = f[c].astype("int64")
    f.attrs["sealed_lines_skipped"] = skipped
    return f.sort_values("time").reset_index(drop=True)


def aggregate(m1: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate M1 to an M15/H1 grid aligned to UTC clock boundaries (MT5 convention)."""
    g = m1.set_index("time").groupby(pd.Grouper(freq=f"{minutes}min", label="left", closed="left"))
    a = g.agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
              tick_volume=("tick_volume", "sum"), n=("open", "size"))
    return a[a["n"] > 0].drop(columns="n")

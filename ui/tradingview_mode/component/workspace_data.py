"""Workspace (chart) history for TradingView Mode: fresher closed bars appended to a registered dataset WITHOUT touching
it.

RESEARCH / FROZEN DATASETS (``services.market_datasets``) stay byte-identical: they are validated evidence, committed
to git, and Gold V1 / Stage 2 research rests on them. WORKSPACE DATA lives only under ``data/workspace/`` (gitignored):
one append-only *extension* CSV per dataset holding the closed bars after the frozen file's last bar, plus a metadata
JSON recording where every appended bar came from. TradingView Mode's chart, Pine scripts and Exness
``request.security()`` read ``frozen file + extension``; research code, the audited Strategy Tester and every other
page keep reading the frozen file only.

Sources (read-only; MetaTrader's Common/Files folder, the folder the Live feed bridge already reads):

* ``mt5_export`` - a CopyRates history export (``xauusd_XAUUSDm_M15.csv`` + ``.metadata.json``) in broker server time.
  Usable only with a recorded server UTC offset and capture time. Only its tail is read.
* ``mt5_live_seed`` - the Live feed service's ``tv_live_<SYMBOL>_<TF>_seed.csv`` (last 500 bars). The server offset
  comes from the service's quote file; the file is rewritten when a bar opens, so its last row is still forming.

CLOSED-BAR POLICY: a bar is appended only if ``open + step <= capture time`` of its source (export: the recorded
capture time; seed: the file's write time). The forming bar is never stored as history.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path

import pandas as pd

from services.market_datasets import (EXNESS_BTCUSDM_H1, EXNESS_BTCUSDM_M15, EXNESS_BTCUSDM_M30,
                                      EXNESS_XAUUSDM_H1, EXNESS_XAUUSDM_M15, MarketDataset, ROOT)
from utils.data_validation import load_ohlcv_csv

from .live import common_files_dir

WORKSPACE_ENV = "TV_WORKSPACE_DATA"
DEFAULT_WORKSPACE_ROOT = ROOT / "data" / "workspace"
CURRENT, STALE, UNKNOWN = "CURRENT", "STALE", "UNKNOWN"
TAIL_CHUNK = 256 * 1024

# dataset key -> (export file, MT5 symbol, MT5 period)
MT5_SOURCES: dict[str, tuple[str, str, str]] = {
    EXNESS_XAUUSDM_M15: ("xauusd_XAUUSDm_M15.csv", "XAUUSDm", "M15"),
    EXNESS_XAUUSDM_H1: ("xauusd_XAUUSDm_H1.csv", "XAUUSDm", "H1"),
    EXNESS_BTCUSDM_M15: ("btcusd_BTCUSDm_M15.csv", "BTCUSDm", "M15"),
    EXNESS_BTCUSDM_M30: ("btcusd_BTCUSDm_M30.csv", "BTCUSDm", "M30"),
    EXNESS_BTCUSDM_H1: ("btcusd_BTCUSDm_H1.csv", "BTCUSDm", "H1"),
}


class RefreshError(RuntimeError):
    """A source or its bars failed validation; nothing was written."""


def workspace_root() -> Path:
    return Path(os.environ.get(WORKSPACE_ENV) or DEFAULT_WORKSPACE_ROOT)


def extension_path(entry: MarketDataset) -> Path:
    return workspace_root() / f"{entry.key}.csv"


def metadata_path(entry: MarketDataset) -> Path:
    return workspace_root() / f"{entry.key}.metadata.json"


def refreshable(entry: MarketDataset) -> bool:
    return entry.key in MT5_SOURCES


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def marker(entry: MarketDataset) -> tuple[float, float]:
    """Cache key part: changes when the frozen file or its workspace extension changes."""
    return _mtime(entry.path), _mtime(extension_path(entry))


def source_marker(entry: MarketDataset) -> tuple:
    """Modification times of the entry's MT5 source files (a few stat calls; no file is read)."""
    if not refreshable(entry):
        return ()
    name, symbol, period = MT5_SOURCES[entry.key]
    folder = common_files_dir()
    return tuple(_mtime(folder / f) for f in (name, f"{name}.metadata.json", f"tv_live_{symbol}_{period}_seed.csv",
                                             f"tv_live_{symbol}_quote.json"))


# ---- reading ------------------------------------------------------------------------------------------------------

def _extension(entry: MarketDataset) -> pd.DataFrame | None:
    path = extension_path(entry)
    return load_ohlcv_csv(path) if path.exists() else None


def load(entry: MarketDataset) -> pd.DataFrame:
    """Frozen dataset + its workspace extension (only bars after the frozen file's last bar; timestamps unique)."""
    base = load_ohlcv_csv(entry.path)
    extension = _extension(entry)
    if extension is None or extension.empty:
        return base
    if len(base):
        extension = extension[extension["timestamp"] > base["timestamp"].iloc[-1]]
    merged = pd.concat([base, extension], ignore_index=True)
    return merged.drop_duplicates("timestamp", keep="first").reset_index(drop=True)


def load_path(path: Path, datasets) -> pd.DataFrame:
    """``load`` for a registered dataset file (the TradingView Mode loaders pass paths); other files load as-is."""
    for entry in datasets:
        if Path(entry.path) == Path(path):
            return load(entry)
    return load_ohlcv_csv(Path(path))


def _read_meta(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _base_last(entry: MarketDataset) -> pd.Timestamp | None:
    tail = _tail_lines(entry.path, 1)
    if not tail:
        return None
    try:
        stamp = pd.Timestamp(tail[-1].split(",")[0])
    except ValueError:
        frame = load_ohlcv_csv(entry.path)
        return frame["timestamp"].iloc[-1] if len(frame) else None
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def last_local(entry: MarketDataset) -> pd.Timestamp | None:
    meta = _read_meta(metadata_path(entry)) if extension_path(entry).exists() else None
    base = _base_last(entry) if entry.exists else None
    if meta and meta.get("last_closed_bar_utc"):
        ext = pd.Timestamp(meta["last_closed_bar_utc"])
        return ext if base is None or ext > base else base
    return base


def _tail_lines(path: Path, count: int) -> list[str]:
    """The last ``count`` non-empty lines of a text file (reads backwards in chunks; never the whole file)."""
    try:
        size = path.stat().st_size
    except OSError:
        return []
    data = b""
    with open(path, "rb") as handle:
        position = size
        while position > 0 and data.count(b"\n") <= count + 1:
            step = min(TAIL_CHUNK, position)
            position -= step
            handle.seek(position)
            data = handle.read(step) + data
    lines = [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
    if position > 0:
        lines = lines[1:]                          # the first chunk line may be partial
    return lines[-count:]


def _lines_after(path: Path, after_server: str) -> tuple[str, list[str]]:
    """Header and the data lines whose server timestamp text sorts after ``after_server`` ("YYYY.MM.DD HH:MM:SS"),
    reading backwards from the end until an older line is found."""
    with open(path, "rb") as handle:
        header = handle.readline().decode("utf-8", "replace").strip()
    size = path.stat().st_size
    data = b""
    position = size
    with open(path, "rb") as handle:
        while position > 0:
            step = min(TAIL_CHUNK, position)
            position -= step
            handle.seek(position)
            data = handle.read(step) + data
            complete = data.decode("utf-8", "replace").splitlines()[1:]   # without a partial first line / the header
            if complete and complete[0][:19] <= after_server:
                break
    lines = [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
    lines = lines[1:]                              # partial line or header
    return header, [line for line in lines if line[:19] > after_server]


# ---- sources ------------------------------------------------------------------------------------------------------

@dataclass
class SourceBars:
    kind: str                     # mt5_export | mt5_live_seed
    path: Path
    captured_utc: pd.Timestamp | None
    bars: pd.DataFrame            # closed bars (UTC), canonical columns
    problem: str | None = None
    covers_from: pd.Timestamp | None = None   # the source's first bar: it holds every bar from here to last_closed

    def last_closed(self) -> pd.Timestamp | None:
        return self.bars["timestamp"].iloc[-1] if len(self.bars) else None


def _export_bars(entry: MarketDataset, after: pd.Timestamp | None) -> SourceBars | None:
    name, symbol, period = MT5_SOURCES[entry.key]
    path = common_files_dir() / name
    if not path.exists():
        return None
    meta = _read_meta(Path(f"{path}.metadata.json")) or {}
    offset = meta.get("server_utc_offset_seconds_at_capture", meta.get("server_utc_offset_seconds"))
    capture = meta.get("capture_server_time")
    if not isinstance(offset, int) or not capture or meta.get("symbol") not in (None, symbol) \
            or meta.get("timeframe") not in (None, period):
        return SourceBars("mt5_export", path, None, _empty(), "the export's metadata does not record its symbol, "
                          "period, server UTC offset and capture time")
    delta = pd.Timedelta(seconds=offset)
    captured = pd.Timestamp(datetime.strptime(capture, "%Y.%m.%d %H:%M:%S"), tz="UTC") - delta
    after_server = (after + delta).strftime("%Y.%m.%d %H:%M:%S") if after is not None else "0000"
    header, lines = _lines_after(path, after_server)
    columns = header.split(",")
    try:
        t, o, h, l, c = (columns.index(k) for k in ("timestamp", "open", "high", "low", "close"))
    except ValueError:
        return SourceBars("mt5_export", path, captured, _empty(), f"unexpected export header {header!r}")
    v = columns.index("tick_volume") if "tick_volume" in columns else None
    rows = []
    for line in lines:
        parts = line.split(",")
        try:
            stamp = pd.Timestamp(datetime.strptime(parts[t], "%Y.%m.%d %H:%M:%S"), tz="UTC") - delta
            rows.append([stamp, float(parts[o]), float(parts[h]), float(parts[l]), float(parts[c]),
                         float(parts[v]) if v is not None else 0.0])
        except (ValueError, IndexError):
            raise RefreshError(f"{path.name}: unreadable row {line!r}") from None
    frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"]) if rows else _empty()
    bars = _closed(frame, entry.step_seconds, captured)
    first = None
    with open(path, "rb") as handle:
        handle.readline()
        head = handle.readline().decode("utf-8", "replace").split(",")[0]
    try:
        first = pd.Timestamp(datetime.strptime(head, "%Y.%m.%d %H:%M:%S"), tz="UTC") - delta
    except ValueError:
        pass
    return SourceBars("mt5_export", path, captured, bars, covers_from=first)


def _seed_bars(entry: MarketDataset, after: pd.Timestamp | None) -> SourceBars | None:
    _, symbol, period = MT5_SOURCES[entry.key]
    folder = common_files_dir()
    path = folder / f"tv_live_{symbol}_{period}_seed.csv"
    if not path.exists():
        return None
    quote = _read_meta(folder / f"tv_live_{symbol}_quote.json") or {}
    if quote.get("symbol") != symbol or not isinstance(quote.get("server_time"), int) \
            or not isinstance(quote.get("gmt_time"), int):
        return SourceBars("mt5_live_seed", path, None, _empty(), "no Live feed quote file records the server UTC offset")
    offset = round((quote["server_time"] - quote["gmt_time"]) / 60) * 60
    written = pd.Timestamp(_mtime(path), unit="s", tz="UTC").floor("s")
    frame = pd.read_csv(path)
    if not {"time", "open", "high", "low", "close"} <= set(frame.columns):
        return SourceBars("mt5_live_seed", path, written, _empty(), "unexpected seed columns")
    stamps = pd.to_datetime(frame["time"] - offset, unit="s", utc=True)
    bars = pd.DataFrame({"timestamp": stamps, "open": frame["open"].astype(float), "high": frame["high"].astype(float),
                         "low": frame["low"].astype(float), "close": frame["close"].astype(float),
                         "volume": frame.get("tick_volume", pd.Series(0, index=frame.index)).astype(float)})
    first = bars["timestamp"].iloc[0] if len(bars) else None
    bars = bars.iloc[:-1] if len(bars) else bars          # rewritten at a bar open: the last row is forming
    bars = _closed(bars, entry.step_seconds, written)
    if after is not None:
        bars = bars[bars["timestamp"] > after]
    return SourceBars("mt5_live_seed", path, written, bars.reset_index(drop=True), covers_from=first)


def _empty() -> pd.DataFrame:
    return pd.DataFrame({"timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
                         **{k: pd.Series([], dtype=float) for k in ("open", "high", "low", "close", "volume")}})


def _closed(bars: pd.DataFrame, step: int, captured: pd.Timestamp) -> pd.DataFrame:
    if bars.empty:
        return bars.reset_index(drop=True)
    keep = bars["timestamp"] + pd.Timedelta(seconds=step) <= captured
    return bars[keep].reset_index(drop=True)


def coverage_gaps(local: pd.Timestamp | None, usable: list[SourceBars], step: int) -> list[tuple]:
    """Spans after the last local bar that no source covers: (last covered bar, next source's first bar). Bars
    strictly between them exist in no local MT5 file (the chart shows a hole; it may also be a market closure)."""
    spans = sorted((s.covers_from, s.last_closed()) for s in usable if s.covers_from is not None and s.last_closed() is not None)
    if local is None or not spans:
        return []
    gaps, cursor = [], local
    for first, last in spans:
        if first > cursor + pd.Timedelta(seconds=step):
            gaps.append((cursor, first))
        cursor = max(cursor, last)
    return gaps


def _recorded_gaps(entry: MarketDataset) -> list[tuple]:
    meta = _read_meta(metadata_path(entry)) if extension_path(entry).exists() else None
    return [(pd.Timestamp(g["after"]), pd.Timestamp(g["before"])) for g in (meta or {}).get("coverage_gaps", [])]


def sources(entry: MarketDataset, after: pd.Timestamp | None) -> list[SourceBars]:
    if not refreshable(entry):
        return []
    return [s for s in (_export_bars(entry, after), _seed_bars(entry, after)) if s is not None]


# ---- freshness ------------------------------------------------------------------------------------------------------

def _iso(ts) -> str | None:
    return None if ts is None else pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")


def freshness(entry: MarketDataset) -> dict:
    """Last local bar vs the latest CLOSED bar a known local source has. CURRENT only when no known source is newer;
    UNKNOWN when there is no readable source (the snapshot is then never presented as current)."""
    local = last_local(entry) if entry.exists else None
    info = {"dataset_key": entry.key, "last_local": _iso(local), "latest_available": None, "status": UNKNOWN,
            "refreshable": refreshable(entry), "source": None, "source_captured": None, "problems": [],
            "coverage_gaps": [],
            "workspace_extended": extension_path(entry).exists()}
    try:
        found = sources(entry, local)
    except (OSError, RefreshError) as exc:
        info["problems"].append(str(exc))
        return info
    usable = [s for s in found if s.problem is None]
    info["problems"] = [f"{s.path.name}: {s.problem}" for s in found if s.problem]
    info["coverage_gaps"] = [[_iso(a), _iso(b)] for a, b in _recorded_gaps(entry)]
    info["problems"] += [f"no local MT5 source has the bars between {g[0]} and {g[1]} UTC (re-export the history in "
                         "MT5, then Refresh)" for g in info["coverage_gaps"]]
    if not usable:
        return info
    # sources only return closed bars after the local last bar: none means nothing newer is known, and the capture
    # time says how recent that knowledge is
    offered = [s for s in usable if s.last_closed() is not None]
    newest = max(offered, key=lambda s: s.last_closed()) if offered else max(usable, key=lambda s: s.captured_utc)
    latest = newest.last_closed()
    info["source"] = newest.kind
    info["source_captured"] = _iso(max(s.captured_utc for s in usable))
    if latest is not None and (local is None or latest > local):
        info["latest_available"], info["status"] = _iso(latest), STALE
    else:
        info["latest_available"], info["status"] = _iso(local), CURRENT
    return info


# ---- refresh --------------------------------------------------------------------------------------------------------

def _validate(bars: pd.DataFrame, step: int, grid_phase: int | None, name: str) -> None:
    values = bars[["open", "high", "low", "close"]].to_numpy(dtype=float)
    for row, (o, h, l, c) in zip(bars["timestamp"], values):
        if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
            raise RefreshError(f"{name}: bar {row} has a non-positive or non-finite price")
        if h < max(o, c, l) or l > min(o, c, h):
            raise RefreshError(f"{name}: bar {row} has an inconsistent high/low")
    epoch = pd.Timestamp(0, tz="UTC")
    seconds = (bars["timestamp"] - epoch) // pd.Timedelta(seconds=1) if len(bars) else pd.Series([], dtype="int64")
    if grid_phase is not None and len(bars) and ((seconds - grid_phase) % step != 0).any():
        bad = bars["timestamp"][((seconds - grid_phase) % step != 0).to_numpy()].iloc[0]
        raise RefreshError(f"{name}: bar {bad} is not on the dataset's {step // 60}-minute grid")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _guard(path: Path) -> None:
    root = workspace_root().resolve()
    target = path.resolve()
    if root not in target.parents:
        raise RefreshError(f"refusing to write outside the workspace data folder: {target}")
    if "research" in target.relative_to(root).parts:
        raise RefreshError("refusing to write research data")


def refresh(entry: MarketDataset, *, now: datetime | None = None) -> dict:
    """Append every closed bar the MT5 sources have after the last local bar. Existing rows are never rewritten;
    the frozen dataset file is never opened for writing."""
    if not refreshable(entry):
        raise RefreshError(f"{entry.label} has no local MT5 source to refresh from.")
    if not entry.exists:
        raise RefreshError(f"{entry.label}: the registered dataset file is missing.")
    local = last_local(entry)
    recorded = _recorded_gaps(entry)
    earliest = min([local] + [a for a, _ in recorded]) if local is not None else None
    found = sources(entry, earliest)
    problems = [f"{s.path.name}: {s.problem}" for s in found if s.problem]
    usable = [s for s in found if s.problem is None]
    if not usable:
        raise RefreshError("no readable MT5 source" + (f" ({'; '.join(problems)})" if problems else
                                                        f" in {common_files_dir()}"))
    # union of the sources; the history export wins where both have a bar
    frames = [s.bars.assign(_rank=i) for i, s in enumerate(usable)]
    offered = pd.concat(frames, ignore_index=True).sort_values(["timestamp", "_rank"])
    offered = offered.drop_duplicates("timestamp", keep="first").drop(columns="_rank").reset_index(drop=True)
    after = offered[offered["timestamp"] > local].reset_index(drop=True) if local is not None else offered
    # a recorded coverage gap is filled once ONE source covers it completely (e.g. after a new MT5 history export)
    fills, remaining = [], []
    for a, b in recorded:
        if any(s.covers_from is not None and s.last_closed() is not None and s.covers_from <= a and s.last_closed() >= b
               for s in usable):
            fills.append(offered[(offered["timestamp"] > a) & (offered["timestamp"] < b)])
        else:
            remaining.append((a, b))
    gaps = remaining + coverage_gaps(local, usable, entry.step_seconds)
    filled = pd.concat(fills, ignore_index=True) if fills else offered.iloc[:0]
    new = pd.concat([filled, after], ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    base_last = _base_last(entry)
    phase = int(base_last.timestamp()) % entry.step_seconds if base_last is not None else 0
    _validate(new, entry.step_seconds, phase, entry.key)
    refreshed = pd.Timestamp(now or datetime.now(timezone.utc)).tz_convert("UTC")
    gap_text = [{"after": a.isoformat(), "before": b.isoformat()} for a, b in gaps]
    summary = {"dataset_key": entry.key, "appended": int(len(after)), "filled": int(len(filled)),
               "previous_last": _iso(local),
               "first_appended": _iso(after["timestamp"].iloc[0]) if len(after) else None,
               "last_closed": _iso(after["timestamp"].iloc[-1]) if len(after) else _iso(local), "problems": problems,
               "coverage_gaps": [(_iso(a), _iso(b)) for a, b in gaps]}
    if new.empty and gaps == recorded:
        return summary
    path, meta_path = extension_path(entry), metadata_path(entry)
    _guard(path)
    _guard(meta_path)
    existing = _extension(entry)
    combined = pd.concat([existing, new], ignore_index=True) if existing is not None else new
    combined = combined.sort_values("timestamp").reset_index(drop=True)
    if combined["timestamp"].duplicated().any():
        raise RefreshError("appending would create duplicate timestamps")
    if combined.empty:
        return summary
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    out = combined[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(temporary, index=False)
    os.replace(temporary, path)
    previous = _read_meta(meta_path) or {}
    history = previous.get("refreshes", [])
    history.append({"refreshed_at_utc": refreshed.isoformat(), "appended": int(len(after)), "filled": int(len(filled)),
                    "first_appended_utc": after["timestamp"].iloc[0].isoformat() if len(after) else None,
                    "last_closed_bar_utc": combined["timestamp"].iloc[-1].isoformat(),
                    "sources": [{"kind": s.kind, "file": s.path.name, "captured_utc": s.captured_utc.isoformat(),
                                 "covers_from_utc": s.covers_from.isoformat() if s.covers_from is not None else None,
                                 "closed_bars_offered": int(len(s.bars)),
                                 "last_closed_utc": s.last_closed().isoformat() if s.last_closed() is not None else None}
                                for s in usable]})
    meta = {"dataset_key": entry.key, "role": "WORKSPACE chart history (not research data)",
            "frozen_dataset": str(entry.path.relative_to(ROOT)) if ROOT in entry.path.parents else str(entry.path),
            "frozen_last_bar_utc": base_last.isoformat() if base_last is not None else None,
            "step_seconds": entry.step_seconds, "rows": int(len(combined)),
            "first_bar_utc": combined["timestamp"].iloc[0].isoformat(),
            "last_closed_bar_utc": combined["timestamp"].iloc[-1].isoformat(),
            "closed_bar_policy": "open + step <= source capture time; the forming bar is never stored",
            # bars strictly between after/before exist in no local MT5 source (a hole on the chart)
            "coverage_gaps": gap_text,
            "extension_sha256": _sha256(path), "refreshes": history}
    temporary_meta = meta_path.with_suffix(".json.tmp")
    temporary_meta.write_text(json.dumps(meta, indent=1) + "\n")
    os.replace(temporary_meta, meta_path)
    return summary
    path, meta_path = extension_path(entry), metadata_path(entry)
    _guard(path)
    _guard(meta_path)
    existing = _extension(entry)
    combined = pd.concat([existing, new], ignore_index=True) if existing is not None else new
    if combined["timestamp"].duplicated().any() or not combined["timestamp"].is_monotonic_increasing:
        raise RefreshError("appending would create duplicate or unordered timestamps")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".csv.tmp")
    out = combined[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(temporary, index=False)
    os.replace(temporary, path)
    previous = _read_meta(meta_path) or {}
    history = previous.get("refreshes", [])
    history.append({"refreshed_at_utc": refreshed.isoformat(), "appended": int(len(new)),
                    "first_appended_utc": new["timestamp"].iloc[0].isoformat(),
                    "last_closed_bar_utc": new["timestamp"].iloc[-1].isoformat(),
                    "sources": [{"kind": s.kind, "file": s.path.name, "captured_utc": s.captured_utc.isoformat(),
                                 "closed_bars_offered": int(len(s.bars)),
                                 "last_closed_utc": s.last_closed().isoformat() if s.last_closed() is not None else None}
                                for s in usable]})
    meta = {"dataset_key": entry.key, "role": "WORKSPACE chart history (not research data)",
            "frozen_dataset": str(entry.path.relative_to(ROOT)) if ROOT in entry.path.parents else str(entry.path),
            "frozen_last_bar_utc": base_last.isoformat() if base_last is not None else None,
            "step_seconds": entry.step_seconds, "rows": int(len(combined)),
            "first_bar_utc": combined["timestamp"].iloc[0].isoformat(),
            "last_closed_bar_utc": combined["timestamp"].iloc[-1].isoformat(),
            "closed_bar_policy": "open + step <= source capture time; the forming bar is never stored",
            "extension_sha256": _sha256(path), "refreshes": history}
    temporary_meta = meta_path.with_suffix(".json.tmp")
    temporary_meta.write_text(json.dumps(meta, indent=1) + "\n")
    os.replace(temporary_meta, meta_path)
    return summary

"""request.security() data providers (P2.1) - the only place that knows files and Binance.

Locked data policy (see pine/parity/SECURITY_SEMANTICS.md):

* **Exness** (and the legacy Bitstamp dataset, same rules): the exact native dataset when one exists
  (M15, M30, H1); otherwise aggregated from the finest dataset of the same symbol (M15), on the broker's
  server-time boundaries read from the dataset's MT5 metadata (a dataset without a recorded offset is not
  aggregated). Weekly / monthly Exness bars are blocked until the broker's week/month boundary is verified.
  Never Binance.
* **Binance**: native public USD-M klines for every interval Binance serves; other intraday intervals are
  aggregated from the largest native Binance interval that divides them. Never Exness. Public market data
  only - no key, no signed, account or order endpoint.
* A request for another family's symbol is refused (cross-family).
* **Knowable mode** (Replay, Live): only bars closed by ``until_ms`` are returned; the Pine security manager
  builds the forming requested bar from the chart bars revealed / received so far.
* Every answer carries provenance: family, provider, symbol, timeframe, native or aggregated (and from what),
  data identity and fingerprint.
"""
from __future__ import annotations

from dataclasses import dataclass
import glob
import hashlib
import json
import math
import threading
import time as _time
from pathlib import Path

import numpy as np

from services.market_datasets import MarketDataset, all_datasets
from utils.data_validation import load_ohlcv_csv

from ..pine.security import (BarGrid, Bars, LIMIT, Requested, SecurityDataError, Timeframe, _aggregate,
                             parse_timeframe)
from . import binance

FAMILY_LABELS = {"exness": "Exness MT5", "binance": "Binance Futures", "bitstamp": "Bitstamp"}
_BROKER_FAMILY = {"Exness Technologies Ltd": "exness", "Bitstamp (public exchange API)": "bitstamp"}
BINANCE_SYMBOLS = tuple(binance.CONTRACTS)
#: Binance kline interval per requested timeframe (seconds -> interval); weeks and months by unit.
BINANCE_NATIVE = {60: "1m", 180: "3m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h", 7200: "2h", 14400: "4h",
                  21600: "6h", 28800: "8h", 43200: "12h", 86400: "1d"}
BINANCE_FETCH_BARS = 3000          # requested bars fetched per Binance context (<= the engine's 10,000 limit)
BINANCE_REFRESH_S = 5.0            # at most one refresh of a (symbol, interval) per 5 seconds


def family_of_dataset(entry: MarketDataset) -> str:
    return _BROKER_FAMILY.get(entry.broker, entry.broker.split(" ")[0].lower())


def _split(symbol: str) -> tuple[str | None, str]:
    text = str(symbol).strip()
    if ":" in text:
        prefix, name = text.split(":", 1)
        return prefix.strip().lower(), name.strip()
    return None, text


def _family_symbols() -> dict[str, dict[str, str]]:
    """family -> {normalised symbol: canonical symbol}."""
    table: dict[str, dict[str, str]] = {"binance": {s.upper(): s for s in BINANCE_SYMBOLS}}
    for entry in all_datasets():
        family = family_of_dataset(entry)
        names = table.setdefault(family, {})
        names[entry.symbol.upper()] = entry.symbol
        names[entry.symbol.replace("/", "").upper()] = entry.symbol
    return table


def resolve_symbol(chart_family: str, symbol: str) -> str:
    """Canonical symbol of ``chart_family`` or SecurityDataError (cross-family / unknown)."""
    prefix, name = _split(symbol)
    table = _family_symbols()
    key = name.upper().removesuffix(".P")
    if prefix is not None and prefix != chart_family:
        if prefix in table:
            raise _cross(symbol, prefix, chart_family)
        raise SecurityDataError(f"symbol `{symbol}` is not available from the {FAMILY_LABELS.get(chart_family, chart_family)} "
                                "source.", "unknown_symbol")
    if key in table.get(chart_family, {}):
        return table[chart_family][key]
    for family, names in table.items():
        if family != chart_family and key in names:
            raise _cross(symbol, family, chart_family)
    raise SecurityDataError(f"symbol `{symbol}` is not available from the {FAMILY_LABELS.get(chart_family, chart_family)} "
                            "source.", "unknown_symbol")


def _cross(symbol: str, family: str, chart_family: str) -> SecurityDataError:
    return SecurityDataError(
        f"symbol `{symbol}` belongs to {FAMILY_LABELS.get(family, family)}, but this chart's source is "
        f"{FAMILY_LABELS.get(chart_family, chart_family)}. Requests across data sources are not allowed.", "cross_family")


def _frame_bars(frame, seconds: int) -> Bars:
    stamps = frame["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ms]").astype(np.int64)
    volume = frame["volume"].to_numpy(dtype=float) if "volume" in frame else np.zeros(len(frame))
    return Bars(stamps, stamps + seconds * 1000, frame["open"].to_numpy(dtype=float), frame["high"].to_numpy(dtype=float),
                frame["low"].to_numpy(dtype=float), frame["close"].to_numpy(dtype=float), volume)


def _rows_to_bars(rows: list[tuple]) -> Bars:
    if not rows:
        return Bars.empty()
    columns = list(zip(*rows))
    return Bars(np.array(columns[0], dtype=np.int64), np.array(columns[1], dtype=np.int64),
                *(np.array(c, dtype=float) for c in columns[2:]))


def _cut(bars: Bars, *, knowable: bool, until_ms: int | None, chart_end_ms: int | None) -> Bars:
    if knowable:
        if until_ms is None:
            raise SecurityDataError("knowable mode needs a cut-off time.", "future")
        return bars.upto_close(until_ms)
    if chart_end_ms is not None:                      # historical: nothing opening after the chart's last bar
        return bars.head(int(np.searchsorted(bars.time, chart_end_ms, side="right")))
    return bars


# ---- datasets (Exness, Bitstamp) ----------------------------------------------------------------------------------

@dataclass
class _Loaded:
    bars: Bars
    fingerprint: str | None
    mtime: float


class DatasetProvider:
    """Requested data from this terminal's registered datasets of one family (Exness or Bitstamp)."""

    _lock = threading.Lock()
    _cache: dict[tuple, _Loaded] = {}                 # (path, mtime, seconds) -> loaded bars (immutable)

    def __init__(self, family: str):
        self.family = family
        self.label = FAMILY_LABELS.get(family, family)

    def datasets(self, symbol: str) -> list[MarketDataset]:
        return sorted((d for d in all_datasets() if family_of_dataset(d) == self.family and d.symbol == symbol),
                      key=lambda d: d.step_seconds)

    def check_symbol(self, symbol: str) -> str:
        return resolve_symbol(self.family, symbol)

    def request(self, symbol, timeframe: Timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms,
                chart_end_ms) -> Requested:
        canonical = self.check_symbol(symbol)
        entries = self.datasets(canonical)
        if not entries:
            raise SecurityDataError(f"no {self.label} dataset exists for `{canonical}`.", "missing_source")
        bars, provenance, grid = self._series(canonical, entries, timeframe)
        tickerid = f"{self.family.upper()}:{canonical}"
        same = _split(parent_tickerid)[1].upper() == canonical.upper()
        base = None
        if knowable and not same:
            parent_tf = parse_timeframe(str(parent_seconds // 60)) if parent_seconds < 86_400 else parse_timeframe("D")
            base_bars, _, _ = self._series(canonical, entries, parent_tf)
            base = base_bars.upto_close(until_ms)
        bars = _cut(bars, knowable=knowable, until_ms=until_ms, chart_end_ms=chart_end_ms)
        return Requested(bars, grid, canonical, tickerid, provenance, mintick=0.01, currency="USD",
                         kind="cfd" if self.family == "exness" else "crypto", same_as_parent=same, base=base)

    def _series(self, symbol: str, entries: list[MarketDataset], timeframe: Timeframe) -> tuple[Bars, dict, BarGrid]:
        native = next((d for d in entries if timeframe.intraday and d.step_seconds == timeframe.seconds), None)
        if native is not None:
            loaded = self._load(native)
            offset = self._offset(native) or 0
            return loaded.bars, self._provenance(symbol, timeframe, native, None, loaded), BarGrid(timeframe, offset * 1000)
        if timeframe.unit in ("W", "M"):
            raise SecurityDataError(
                f"{LIMIT}: {'weekly' if timeframe.unit == 'W' else 'monthly'} {self.label} bars are not supported yet "
                "(the broker's week/month boundary is not verified).")
        base = entries[0]                               # the finest approved authoritative dataset (e.g. M15)
        minutes = timeframe.seconds // 60
        base_minutes = base.step_seconds // 60
        if timeframe.seconds < base.step_seconds or minutes % base_minutes:
            raise SecurityDataError(
                f"no {self.label} source for `{symbol}` at {timeframe.text}: the finest dataset is "
                f"{base.timeframe}, and {timeframe.text} is not a multiple of it.", "missing_source")
        if timeframe.intraday and 1440 % minutes:
            raise SecurityDataError(f"{LIMIT}: {timeframe.text}-minute bars do not divide the trading day; their "
                                    f"{self.label} boundaries are undefined.")
        offset = self._offset(base)
        if offset is None:
            raise SecurityDataError(
                f"{base.key} does not record its server time offset, so {timeframe.text} bars cannot be aggregated on "
                "the broker's boundaries.", "missing_source")
        grid = BarGrid(timeframe, offset * 1000)
        loaded = self._load(base)
        key = (str(base.path), loaded.mtime, "agg", timeframe.text, offset)
        with self._lock:
            cached = self._cache.get(key)
        if cached is None:
            cached = _Loaded(_rows_to_bars(_aggregate(loaded.bars, 0, loaded.bars.size, grid)), loaded.fingerprint,
                             loaded.mtime)
            with self._lock:
                self._cache[key] = cached
        return cached.bars, self._provenance(symbol, timeframe, base, base, loaded), grid

    def _load(self, entry: MarketDataset) -> _Loaded:
        mtime = entry.path.stat().st_mtime
        key = (str(entry.path), mtime, entry.step_seconds)
        with self._lock:
            loaded = self._cache.get(key)
        if loaded is None:
            loaded = _Loaded(_frame_bars(load_ohlcv_csv(entry.path), entry.step_seconds), _fingerprint(entry.path),
                             mtime)
            with self._lock:
                self._cache[key] = loaded
        return loaded

    @staticmethod
    def _offset(entry: MarketDataset) -> int | None:
        """The broker server's UTC offset (seconds) recorded with the dataset, or None when not recorded."""
        if family_of_dataset(entry) == "bitstamp":
            return 0                                   # exchange API timestamps are UTC
        candidates = [Path(f"{entry.path}.metadata.json")]
        raw = entry.path.parent.parent / "raw"
        tf = {900: "M15", 1800: "M30", 3600: "H1"}.get(entry.step_seconds, "")
        candidates += [Path(p) for p in sorted(glob.glob(str(raw / f"*_{entry.symbol}_{tf}.csv.metadata.json")))]
        for path in candidates:
            try:
                meta = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            for field in ("server_utc_offset_seconds", "server_utc_offset_seconds_at_capture"):
                if isinstance(meta.get(field), int):
                    return meta[field]
        return None

    def _provenance(self, symbol, timeframe, entry, base, loaded) -> dict:
        return {"provider_family": self.family, "provider": self.label, "native": base is None,
                "aggregation_base": None if base is None else base.timeframe,
                "data_identity": f"{entry.key} · {_display_path(entry.path)}",
                "fingerprint": loaded.fingerprint}


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _fingerprint(path: Path) -> str:
    """The dataset's recorded sha256 (processed metadata) or the file's own sha256."""
    meta = Path(f"{path}.metadata.json")
    try:
        recorded = json.loads(meta.read_text()).get("dataset_sha256")
        if recorded:
            return f"sha256:{recorded}"
    except (OSError, ValueError):
        pass
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


# ---- Binance ------------------------------------------------------------------------------------------------------

class BinanceProvider:
    """Requested data from Binance USD-M public klines (read-only)."""

    family = "binance"
    label = FAMILY_LABELS["binance"]

    def __init__(self, rest=None, clock=_time.time):
        self._rest = rest
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], tuple[Bars, float]] = {}

    @property
    def rest(self):
        if self._rest is None:
            self._rest = binance.BinanceRest()
        return self._rest

    def check_symbol(self, symbol: str) -> str:
        return resolve_symbol("binance", symbol)

    def request(self, symbol, timeframe: Timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms,
                chart_end_ms) -> Requested:
        canonical = self.check_symbol(symbol)
        grid = BarGrid(timeframe)                       # Binance klines: UTC, weeks from Monday, calendar months
        interval = self._native(timeframe)
        if interval is not None:
            bars = self._klines(canonical, interval, _interval_ms(timeframe), until_ms, BINANCE_FETCH_BARS)
            provenance = self._provenance(canonical, interval, None, bars)
        else:
            base_seconds = self._aggregation_base(timeframe)
            base_interval = BINANCE_NATIVE[base_seconds]
            ratio = timeframe.seconds // base_seconds
            base = self._klines(canonical, base_interval, base_seconds * 1000, until_ms,
                                min(10_000, BINANCE_FETCH_BARS * ratio))
            bars = _rows_to_bars(_aggregate(base, 0, base.size, grid))
            if bars.size and bars.close_time[-1] > (until_ms or math.inf):
                bars = bars.upto_close(until_ms)       # an incomplete last bucket is not a completed bar
            provenance = self._provenance(canonical, None, base_interval, base)
        same = _split(parent_tickerid)[1].upper().removesuffix(".P") == canonical
        base_bars = None
        if knowable and not same:
            if parent_seconds not in BINANCE_NATIVE:
                raise SecurityDataError(f"{LIMIT}: another symbol cannot be requested from this chart timeframe.")
            base_bars = self._klines(canonical, BINANCE_NATIVE[parent_seconds], parent_seconds * 1000, until_ms,
                                     BINANCE_FETCH_BARS)
        bars = _cut(bars, knowable=knowable, until_ms=until_ms, chart_end_ms=chart_end_ms)
        return Requested(bars, grid, canonical, f"BINANCE:{canonical}", provenance, mintick=0.1, currency="USDT",
                         kind="crypto", same_as_parent=same, base=base_bars)

    @staticmethod
    def _native(timeframe: Timeframe) -> str | None:
        if timeframe.unit == "W":
            return "1w"
        if timeframe.unit == "M":
            return "1M"
        return BINANCE_NATIVE.get(timeframe.seconds)

    @staticmethod
    def _aggregation_base(timeframe: Timeframe) -> int:
        if not timeframe.intraday or 1440 % (timeframe.seconds // 60):
            raise SecurityDataError(f"{LIMIT}: the Binance timeframe {timeframe.text} is not supported (it is not a "
                                    "native interval and does not divide the day).")
        for seconds in sorted(BINANCE_NATIVE, reverse=True):
            if seconds < timeframe.seconds and timeframe.seconds % seconds == 0:
                return seconds
        raise SecurityDataError(f"{LIMIT}: no Binance interval divides {timeframe.text}.")

    def _klines(self, symbol: str, interval: str, interval_ms: int, until_ms: int | None, count: int) -> Bars:
        """Completed klines (close <= now, and <= until_ms when given), cached per (symbol, interval)."""
        now_ms = int(self._clock() * 1000)
        key = (symbol, interval)
        with self._lock:
            cached = self._cache.get(key)
        wanted_close = min(until_ms, now_ms) if until_ms is not None else now_ms
        stale = cached is None or (cached[0].size and cached[0].close_time[-1] + interval_ms <= wanted_close
                                   and now_ms / 1000 - cached[1] >= BINANCE_REFRESH_S)
        if stale:
            pages, fetched, end = [], 0, None
            while fetched < count and len(pages) < 8:          # page backwards, newest first
                want = min(1500, count - fetched)
                page = list(self.rest.klines(symbol, interval, want, end) or [])
                if not page:
                    break
                pages.insert(0, page)
                fetched += len(page)
                if len(page) < want:
                    break                                      # the start of Binance's history
                end = int(page[0][0]) - 1
            by_time: dict[int, tuple] = {}
            for page in pages:
                for row in page:
                    opened, closed = int(row[0]), int(row[6]) + 1  # Binance close time = next open - 1 ms
                    if closed <= now_ms:                       # completed klines only: the forming one is not received data
                        by_time[opened] = (opened, closed, float(row[1]), float(row[2]), float(row[3]), float(row[4]),
                                           float(row[5]))
            bars = _rows_to_bars([by_time[t] for t in sorted(by_time)][-count:])
            cached = (bars, now_ms / 1000)
            with self._lock:
                self._cache[key] = cached
        bars = cached[0]
        return bars.upto_close(until_ms) if until_ms is not None else bars

    def _provenance(self, symbol, interval, base_interval, bars: Bars) -> dict:
        digest = hashlib.sha256(np.ascontiguousarray(np.vstack([bars.time.astype(float), bars.open, bars.high, bars.low,
                                                                bars.close])).tobytes()).hexdigest()[:16]
        span = (f"{int(bars.time[0]) // 1000}..{int(bars.close_time[-1]) // 1000}" if bars.size else "empty")
        return {"provider_family": "binance", "provider": self.label, "native": interval is not None,
                "aggregation_base": base_interval,
                "data_identity": f"binance:fapi:klines:{symbol}:{interval or base_interval}:{span}",
                "fingerprint": f"sha256/16:{digest}"}


def _interval_ms(timeframe: Timeframe) -> int:
    return timeframe.seconds * 1000


def provider_for(family: str, *, binance_provider: BinanceProvider | None = None):
    """The provider for a chart's source family."""
    if family == "binance":
        return binance_provider or BinanceProvider()
    return DatasetProvider(family)

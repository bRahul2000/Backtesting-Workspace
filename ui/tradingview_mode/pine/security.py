"""request.security(): requested contexts executed by child runtimes (P2.1).

A ``request.security()`` call site owns one *context* per (call node, user-function path, symbol,
timeframe). The context holds a child ``Runtime`` running the call's **security slice** (the global
statements the expression depends on, computed by the analyzer) followed by the expression itself, over the
REQUESTED bars: its own OHLCV, time, bar_index, history, ``var`` state and ta.* call-site state. Main-chart
results are never resampled.

Mapping of requested bars onto chart bars (confirmed on real TradingView, fixture q4, 134,400 cells):

* ``lookahead_off``: the latest requested bar whose close time <= the chart bar's close time
  (1m chart, 5m request: ``PPPPC``);
* ``lookahead_on``: the requested bar containing the chart bar's open time (``CCCCC``);
* ``gaps_on``: the value only on the chart bar where a new requested bar is selected, na elsewhere
  (``nnnnC`` / ``Cnnnn``); ``gaps_off`` carries the value.

Modes:

* **historical** - the requested bars are the provider's bars; ``lookahead_on`` shows a requested bar's
  final value from its first chart bar, exactly like TradingView's historical bars (a future bias by design).
* **knowable** (Replay and Live) - for every chart bar only information knowable at that bar is used:
  requested bars whose close <= the chart bar's close (or its open, while the chart bar is still forming)
  come from the provider; the requested bar still forming is aggregated from the chart-timeframe bars
  revealed / received so far. ``lookahead_on`` therefore shows the forming value, never a final future one,
  and an incremental run equals a fresh run on the same bars.

``request.security_lower_tf()`` (P2.2-A4, P22_LOWER_TF_RESEARCH.md) uses the same contexts over intrabars (a
timeframe lower than or equal to the chart's). Each chart bar gets **new arrays** of the values captured on the
intrabars it owns: those whose close time is in ``(chart open, chart close]`` (TradingView q7). Historical runs use
every provider intrabar; Replay only intrabars closed by the chart bar's close (knowable at the cursor); Live adds,
on the forming chart bar, the intrabars this terminal has received, the forming one last (TradingView R1).

Resource limits are this engine's (not TradingView's): see ``MAX_CONTEXTS_PER_SCRIPT`` etc.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
from typing import Any, Protocol

import numpy as np

from .errors import PineRuntimeError
from .values import NA, Color, PineArray, is_na

MAX_CONTEXTS_PER_SCRIPT = 16
MAX_CONTEXTS_PER_CHART = 32
MAX_BARS_PER_CONTEXT = 10_000
MAX_DEPTH = 2
LIMIT = "Current Pine engine limit"

_UTC = timezone.utc
_MINUTE, _DAY, _WEEK = 60_000, 86_400_000, 604_800_000
_EPOCH_MONDAY = 4 * _DAY          # 1970-01-05 is a Monday


class SecurityDataError(Exception):
    """A data-source refusal (unknown symbol, cross-family request, unsupported timeframe, missing source)."""

    def __init__(self, message: str, kind: str = "unsupported"):
        super().__init__(message)
        self.message, self.kind = message, kind


# ---- timeframes -------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Timeframe:
    """A canonical Pine timeframe: minutes, days, weeks or months."""

    text: str                 # canonical Pine string: "5", "60", "D", "W", "M"
    unit: str                 # "min" | "D" | "W" | "M"
    count: int

    @property
    def seconds(self) -> int:
        """Nominal duration (months count as 30 days, like timeframe.in_seconds)."""
        return self.count * {"min": 60, "D": 86_400, "W": 604_800, "M": 2_592_000}[self.unit]

    @property
    def intraday(self) -> bool:
        return self.unit == "min"


def parse_timeframe(text, chart_seconds: int | None = None) -> Timeframe:
    """Pine timeframe string -> Timeframe. ``""`` is the chart's timeframe. Raises SecurityDataError."""
    if text is None or is_na(text) or text == "":
        if chart_seconds is None:
            raise SecurityDataError("The chart timeframe is not known.")
        return _from_seconds(chart_seconds)
    raw = str(text).strip().upper()
    if raw.isdigit():
        minutes = int(raw)
        if minutes <= 0:
            raise SecurityDataError(f"Invalid timeframe {text!r}.")
        if minutes % 1440 == 0:
            return parse_timeframe(f"{minutes // 1440}D")
        if minutes > 1440:
            raise SecurityDataError(f"The timeframe {text!r} is longer than a day but not a whole number of days.")
        return Timeframe(str(minutes), "min", minutes)
    for unit in ("D", "W", "M"):
        if raw.endswith(unit) and (raw[:-1] == "" or raw[:-1].isdigit()):
            count = int(raw[:-1] or 1)
            if count != 1:
                raise SecurityDataError(f"{LIMIT}: the timeframe {text!r} is not supported yet (only 1{unit}).")
            return Timeframe(unit, unit, 1)
    if raw.endswith(("S", "T", "R")) and raw[:-1].isdigit():
        raise SecurityDataError(f"{LIMIT}: second, tick and range timeframes ({text!r}) are not supported.")
    raise SecurityDataError(f"Invalid timeframe {text!r}.")


def _from_seconds(seconds: int) -> Timeframe:
    if seconds % 2_592_000 == 0:
        return Timeframe("M", "M", 1)
    if seconds % 604_800 == 0:
        return Timeframe("W", "W", 1)
    if seconds % 86_400 == 0:
        return Timeframe("D", "D", 1)
    return Timeframe(str(seconds // 60), "min", seconds // 60)


@dataclass(frozen=True)
class BarGrid:
    """Requested-bar boundaries of a provider: ``offset_ms`` shifts intraday/daily bars (broker server time);
    weeks start on ``week_anchor_ms`` (e.g. Monday 00:00 UTC for Binance); months on the 1st."""

    timeframe: Timeframe
    offset_ms: int = 0
    week_anchor_ms: int = _EPOCH_MONDAY

    def bucket(self, t: int) -> tuple[int, int]:
        """(open, close) in epoch ms of the requested bar containing ``t``."""
        tf = self.timeframe
        if tf.unit == "min" or tf.unit == "D":
            size = tf.count * (_MINUTE if tf.unit == "min" else _DAY)
            start = (t - self.offset_ms) // size * size + self.offset_ms
            return start, start + size
        if tf.unit == "W":
            start = (t - self.week_anchor_ms) // _WEEK * _WEEK + self.week_anchor_ms
            return start, start + _WEEK
        d = datetime.fromtimestamp((t - self.offset_ms) / 1000, _UTC)
        start = datetime(d.year, d.month, 1, tzinfo=_UTC)
        end = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=_UTC)
        return int(start.timestamp() * 1000) + self.offset_ms, int(end.timestamp() * 1000) + self.offset_ms


# ---- what a provider returns --------------------------------------------------------------------------------------

@dataclass
class Bars:
    """Columnar OHLCV bars, ascending by open time (epoch ms)."""

    time: np.ndarray
    close_time: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    @property
    def size(self) -> int:
        return len(self.time)

    @classmethod
    def empty(cls) -> "Bars":
        z = np.zeros(0)
        return cls(np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64), z, z, z, z, z)

    def upto_close(self, until_ms: int) -> "Bars":
        n = int(np.searchsorted(self.close_time, until_ms, side="right"))
        return self.head(n)

    def head(self, n: int) -> "Bars":
        return Bars(self.time[:n], self.close_time[:n], self.open[:n], self.high[:n], self.low[:n], self.close[:n],
                    self.volume[:n])

    def tail(self, n: int) -> "Bars":
        return Bars(self.time[-n:], self.close_time[-n:], self.open[-n:], self.high[-n:], self.low[-n:],
                    self.close[-n:], self.volume[-n:]) if n < self.size else self


@dataclass
class Requested:
    """A provider's answer for one (symbol, timeframe)."""

    bars: Bars                  # completed requested bars (knowable mode: close <= the provider's cut-off)
    grid: BarGrid
    ticker: str
    tickerid: str
    provenance: dict            # family, provider, symbol, timeframe, native, aggregation_base, data_identity, fingerprint
    mintick: float = 0.01
    currency: str = "USD"
    kind: str = "crypto"
    same_as_parent: bool = True  # the requested symbol is the parent context's symbol
    base: Bars | None = None    # knowable mode, other symbol: its bars at the parent timeframe (for forming bars)


@dataclass
class ReceivedBars:
    """Live: bars of one symbol/timeframe this terminal has actually received (ascending, the forming one last)."""

    rows: list                  # (open_ms, close_ms, open, high, low, close, volume)
    forming: bool               # the last row is still forming


class SecurityProvider(Protocol):
    """Resolves and serves requested data. Implemented outside the Pine package (component/security_data.py).

    ``request(..., lower=True)`` is asked for lower-timeframe contexts (a provider may fetch more bars); a provider
    may also offer ``received(symbol, timeframe) -> ReceivedBars | None`` for Live lower-timeframe requests."""

    family: str

    def request(self, symbol: str, timeframe: Timeframe, *, parent_tickerid: str, parent_seconds: int,
                knowable: bool, until_ms: int | None, chart_end_ms: int | None) -> Requested: ...


# ---- the requested-bar store read by a child runtime ----------------------------------------------------------------

class _Store:
    """Growable columnar arrays; a child DataContext is a view of the first ``n`` rows (O(1))."""

    COLS = ("time", "close_time", "open", "high", "low", "close", "volume")

    def __init__(self, capacity: int = 256):
        self.n = 0
        self.arrays = {c: np.zeros(capacity, dtype=np.int64 if "time" in c else float) for c in self.COLS}

    def ensure(self, size: int) -> None:
        capacity = len(self.arrays["time"])
        if size > capacity:
            new = max(size, capacity * 2)
            for c in self.COLS:
                grown = np.zeros(new, dtype=self.arrays[c].dtype)
                grown[:capacity] = self.arrays[c]
                self.arrays[c] = grown

    def put(self, index: int, row: tuple) -> None:
        self.ensure(index + 1)
        for c, value in zip(self.COLS, row):
            self.arrays[c][index] = value

    def row(self, index: int) -> tuple:
        return tuple(self.arrays[c][index].item() for c in self.COLS)

    def view(self, c: str) -> np.ndarray:
        return self.arrays[c][:self.n]


def _row(bars: Bars, i: int) -> tuple:
    return (int(bars.time[i]), int(bars.close_time[i]), float(bars.open[i]), float(bars.high[i]), float(bars.low[i]),
            float(bars.close[i]), float(bars.volume[i]))


# ---- contexts ------------------------------------------------------------------------------------------------------

@dataclass
class Budget:
    """Context count shared by a script's whole tree of requested contexts."""

    limit: int = MAX_CONTEXTS_PER_SCRIPT
    used: int = 0


@dataclass
class Context:
    key: tuple
    call_line: int
    depth: int
    symbol: str
    requested: Requested
    timeframe: Timeframe
    runtime: Any                                   # child Runtime
    store: _Store = field(default_factory=_Store)
    n_provider: int = 0                            # store rows [0, n_provider) come from the provider
    tail: list = field(default_factory=list)       # store rows after them, aggregated from revealed/received bars
    tail_start: int = -1                           # base index the tail aggregation started from
    last_bucket_start: int = 0                     # base index of the first base bar of the last tail row
    forming: bool = False                          # the last store row is a forming (partial) bar
    max_source_time: int | None = None
    stale: bool = False                            # re-ask the provider on the next advance (new run)
    lower: bool = False                            # a request.security_lower_tf() context
    limit: int = MAX_BARS_PER_CONTEXT              # provider bars kept (lower: minus room for received bars)

    @property
    def size(self) -> int:
        return self.n_provider + len(self.tail)

    def provenance(self) -> dict:
        info = dict(self.requested.provenance)
        info.update(symbol=self.requested.tickerid, timeframe=self.timeframe.text, bar_count=self.store.n,
                    max_source_time=self.max_source_time, depth=self.depth, line=self.call_line, forming=self.forming,
                    aggregated_tail=len(self.tail))
        return info


class SecurityManager:
    """All requested contexts of one runtime (the main script, or a child for nested requests)."""

    def __init__(self, provider: SecurityProvider | None, depth: int = 0, budget: Budget | None = None):
        self.provider = provider
        self.depth = depth
        self.budget = budget or Budget()
        self.contexts: dict[tuple, Context] = {}

    # -- public ------------------------------------------------------------------------------------------------------
    def set_provider(self, provider: SecurityProvider | None) -> None:
        """A new run: the provider may know more (live) - contexts re-ask it on their next advance."""
        self.provider = provider
        for context in self.contexts.values():
            context.stale = True
            if context.runtime.security is not None:
                context.runtime.security.set_provider(provider)

    def all_contexts(self) -> list[Context]:
        out = []
        for context in self.contexts.values():
            out.append(context)
            if context.runtime.security is not None:
                out.extend(context.runtime.security.all_contexts())
        return out

    def value(self, rt, node, spec, args: dict):
        """The value of one request.security() / request.security_lower_tf() call on the parent's current bar."""
        label = "request.security_lower_tf()" if spec.lower else "request.security()"
        if self.provider is None:
            raise PineRuntimeError(f"{label} has no data source in this run.", node.line)
        if self.depth + 1 > MAX_DEPTH:
            raise PineRuntimeError(f"{LIMIT}: {label} can be nested at most {MAX_DEPTH} levels deep.", node.line)
        if not is_na(args.get("currency", NA)):
            raise PineRuntimeError(f"{label} with a `currency` conversion is not implemented yet.", node.line)
        data = rt.data
        try:
            timeframe = parse_timeframe(args["timeframe"], data.timeframe_seconds)
        except SecurityDataError as exc:
            raise PineRuntimeError(f"{label}: {exc.message}", node.line) from None
        chart = _from_seconds(data.timeframe_seconds).text
        if spec.lower and timeframe.seconds > data.timeframe_seconds:
            if args.get("ignore_invalid_timeframe") is True:
                return _na_like(spec)                        # an na array (TradingView R2), not an empty one
            raise PineRuntimeError(f"{label}: the timeframe {timeframe.text} is higher than the chart's ({chart}); "
                                   "only lower or equal timeframes can be requested.", node.line)
        if not spec.lower and timeframe.seconds < data.timeframe_seconds:
            raise PineRuntimeError(                          # wording frozen in the P2.1 terminal evidence
                f"request.security() for a lower timeframe ({timeframe.text}) than the chart ({chart}) is not "
                "implemented yet (request.security_lower_tf() comes later).", node.line)
        symbol = args["symbol"]
        symbol = data.tickerid if is_na(symbol) or symbol == "" else str(symbol)
        key = (node.id, rt.ctx_path, symbol, timeframe.text)
        context = self.contexts.get(key)
        try:
            if context is None:
                context = self._open(rt, node, spec, key, symbol, timeframe, args)
            if context.lower:
                self._advance_lower(rt, context)
            else:
                self._advance(rt, context)
        except SecurityDataError as exc:
            if exc.kind == "unknown_symbol" and args.get("ignore_invalid_symbol") is True:
                return _na_like(spec)
            raise PineRuntimeError(f"{label}: {exc.message}", node.line) from None
        if context.lower:
            return self._select_lower(rt, spec, context)
        return self._select(rt, node, spec, context, args)

    # -- context lifecycle ---------------------------------------------------------------------------------------------
    def _ask(self, rt, symbol: str, timeframe: Timeframe, lower: bool = False,
             limit: int = MAX_BARS_PER_CONTEXT) -> Requested:
        data = rt.data
        extra = {"lower": True} if lower else {}
        chart_end = int(data.time[-1]) if data.size else None
        if lower and chart_end is not None:          # intrabars of the last chart bar open after its open time
            chart_end = _bar_close(data, data.size - 1) - 1
        try:
            requested = self.provider.request(
                symbol, timeframe, parent_tickerid=data.tickerid, parent_seconds=data.timeframe_seconds,
                knowable=data.knowable, until_ms=data.knowable_until if data.knowable else None,
                chart_end_ms=chart_end, **extra)
        except SecurityDataError:
            raise
        except Exception as exc:                      # network / file problems: an explicit script error, never a crash
            raise SecurityDataError(f"the {getattr(self.provider, 'family', 'data')} data source is unavailable "
                                    f"({type(exc).__name__}: {exc}).", "unavailable") from None
        if requested.bars.size > limit:
            requested.bars = requested.bars.tail(limit)
        if data.knowable and data.knowable_until is not None and requested.bars.size \
                and int(requested.bars.close_time[-1]) > data.knowable_until:
            raise SecurityDataError("the data source returned bars after the knowable time (refused).", "future")
        return requested

    def _open(self, rt, node, spec, key, symbol, timeframe, args: dict) -> Context:
        if self.budget.used >= self.budget.limit:
            raise PineRuntimeError(f"{LIMIT}: at most {self.budget.limit} requested contexts per script.", node.line)
        limit = MAX_BARS_PER_CONTEXT
        if spec.lower:
            # engine limitation (TradingView: 100K-200K intrabars); room is kept for the received live intrabars
            limit -= rt.data.timeframe_seconds // timeframe.seconds + 2
            calc = args.get("calc_bars_count")
            if not is_na(calc) and calc is not None and int(calc) > 0:
                limit = min(limit, int(calc))
        requested = self._ask(rt, symbol, timeframe, spec.lower, limit)
        self.budget.used += 1
        context = Context(key, node.line, self.depth + 1, symbol, requested, timeframe,
                          self._child(rt, spec, requested, timeframe), lower=spec.lower, limit=limit)
        self.contexts[key] = context
        return context

    def _child(self, rt, spec, requested: Requested, timeframe: Timeframe):
        from .runtime import DataContext, Runtime          # local: runtime imports this module lazily

        data = rt.data
        empty_i, empty_f = np.zeros(0, dtype=np.int64), np.zeros(0)
        child_data = DataContext(time=empty_i, open=empty_f, high=empty_f, low=empty_f, close=empty_f, volume=empty_f,
                                 timeframe_seconds=timeframe.seconds, ticker=requested.ticker,
                                 tickerid=requested.tickerid, mintick=requested.mintick, currency=requested.currency,
                                 type=requested.kind, close_time=empty_i, knowable=data.knowable,
                                 knowable_until=data.knowable_until)
        return Runtime(rt.program, child_data, rt.input_values, body=spec.body, capture=True,
                       security=SecurityManager(self.provider, self.depth + 1, self.budget))

    def _refresh(self, rt, context: Context) -> None:
        if context.stale:
            context.stale = False
            fresh = self._ask(rt, context.symbol, context.timeframe, context.lower, context.limit)
            if not _same_prefix(context.requested.bars, fresh.bars, context.n_provider):
                self._reset(context, rt)
            context.requested = fresh

    def _advance(self, rt, context: Context) -> None:
        """Bring the requested bars (and the child runtime) to what the parent's current bar may see."""
        self._refresh(rt, context)
        data, bar = rt.data, rt.bar
        bars = context.requested.bars
        if not data.knowable:
            n_provider, tail, forming = bars.size, [], False
            max_source = int(bars.close_time[-1]) if bars.size else None
        else:
            n_provider, tail, forming, max_source = self._knowable(rt, context, data, bar)
        self._apply(context, n_provider, tail, forming)
        context.max_source_time = max_source

    def _advance_lower(self, rt, context: Context) -> None:
        """Lower timeframe: historical = every provider intrabar; knowable (Replay/Live) = the intrabars closed by the
        chart bar's close, and on the forming Live bar the received ones after them (the forming intrabar last)."""
        self._refresh(rt, context)
        data, bar = rt.data, rt.bar
        bars = context.requested.bars
        n_provider, tail, forming = bars.size, [], False
        if data.knowable:
            confirmed = data.confirmed_until is None or bar < data.confirmed_until
            cutoff = _bar_close(data, bar) if confirmed else int(data.time[bar])
            n_provider = int(np.searchsorted(bars.close_time, cutoff, side="right"))
            if not confirmed:
                tail, forming = self._received(context, int(bars.close_time[n_provider - 1]) if n_provider else None)
        max_source = int(bars.close_time[n_provider - 1]) if n_provider else None
        if tail:
            last = tail[-1]
            max_source = max(max_source or 0, last[0] if forming else last[1])
        self._apply(context, n_provider, tail, forming)
        context.max_source_time = max_source

    def _received(self, context: Context, covered: int | None) -> tuple[list, bool]:
        """Received live intrabars after the provider's coverage (none without a received source)."""
        source = getattr(self.provider, "received", None)
        received = source(context.symbol, context.timeframe) if source is not None else None
        if received is None or not received.rows:
            return [], False
        rows = [tuple(row) for row in received.rows if covered is None or int(row[1]) > covered]
        return rows, bool(rows) and received.forming

    def _knowable(self, rt, context: Context, data, bar: int):
        t_open, t_close = int(data.time[bar]), _bar_close(data, bar)
        confirmed = data.confirmed_until is None or bar < data.confirmed_until
        cutoff = t_close if confirmed else t_open
        provider_bars, grid = context.requested.bars, context.requested.grid
        n_provider = int(np.searchsorted(provider_bars.close_time, cutoff, side="right"))
        coverage = int(provider_bars.close_time[n_provider - 1]) if n_provider else None
        if context.requested.same_as_parent:
            base = _parent_bars(data, bar, self._close_times(data))
        else:                                               # other symbol: its own bars at the parent timeframe
            base = context.requested.base or Bars.empty()
            base = base.head(int(np.searchsorted(base.time, t_open, side="right"))).upto_close(cutoff)
        start = int(np.searchsorted(base.time, coverage, side="left")) if coverage is not None else 0
        if n_provider != context.n_provider or start != context.tail_start or not context.tail:
            rows, from_index = _aggregate(base, start, base.size, grid), start
        else:                                               # only the last (forming) requested bar can change
            from_index = context.last_bucket_start
            rows = context.tail[:-1] + _aggregate(base, from_index, base.size, grid)
        tail, forming = [], False
        for row in rows:
            tail.append(row)
            if row[1] > cutoff:                             # not complete by the cut-off: the forming bar
                forming = True
                break
        context.tail_start = start
        if tail:
            last_open = tail[-1][0]
            context.last_bucket_start = int(np.searchsorted(base.time, last_open, side="left"))
        max_source = coverage
        if tail:
            last_base = base.size - 1
            used = int(base.close_time[last_base]) if confirmed else int(base.time[last_base])
            max_source = max(max_source or 0, min(used, cutoff) if confirmed else used)
        return n_provider, tail, forming, max_source

    def _close_times(self, data) -> np.ndarray:
        """The parent's bar close times, computed once per data object (not once per bar)."""
        if data.close_time is not None and len(data.close_time) == data.size:
            return data.close_time
        cached = getattr(self, "_closes", None)
        if cached is None or cached[0] is not data.time or len(cached[1]) != data.size:
            self._closes = (data.time, data.time + data.timeframe_seconds * 1000)
        return self._closes[1]

    def _apply(self, context: Context, n_provider: int, tail: list, forming: bool) -> None:
        """Make the store = provider[:n_provider] + tail and re-run the child from the first changed bar."""
        old_n, old_tail = context.n_provider, context.tail
        old_size = old_n + len(old_tail)
        if n_provider != old_n:
            first = min(old_n, n_provider)
        else:
            first = n_provider
            while first - n_provider < min(len(old_tail), len(tail)) and old_tail[first - n_provider] == tail[first - n_provider]:
                first += 1
        size = n_provider + len(tail)
        if first == old_size == size and forming == context.forming:
            return
        if first < old_size - 1:                            # an older requested bar changed: start over
            self._reset(context)
            first, old_size = 0, 0
        store, bars = context.store, context.requested.bars
        store.ensure(size)
        for index in range(first, size):
            store.put(index, _row(bars, index) if index < n_provider else tail[index - n_provider])
        store.n = size
        context.n_provider, context.tail, context.forming = n_provider, list(tail), forming
        child = context.runtime
        data = child.data
        data.time, data.close_time = store.view("time"), store.view("close_time")
        data.open, data.high, data.low = store.view("open"), store.view("high"), store.view("low")
        data.close, data.volume = store.view("close"), store.view("volume")
        data.confirmed_until = size - 1 if forming else None
        if first <= child.last_bar:
            child.rollback(first)
            child.last_bar = first - 1
        child.run()

    def _reset(self, context: Context, rt=None) -> None:
        from .runtime import Runtime

        old = context.runtime
        context.runtime = Runtime(old.program, old.data, old.input_values, body=old.body, capture=True,
                                  security=SecurityManager(self.provider, context.depth, self.budget))
        context.store, context.n_provider, context.tail = _Store(), 0, []
        context.tail_start, context.last_bucket_start, context.forming = -1, 0, False

    # -- lower-timeframe mapping (TradingView q7: intrabars belong to the chart bar in which they close) ----------------
    def _select_lower(self, rt, spec, context: Context):
        data, bar, store = rt.data, rt.bar, context.store
        values: list = []
        if store.n:
            closes = store.view("close_time")
            first = bisect_right(closes, int(data.time[bar]))            # first intrabar closing after the chart open
            last = bisect_right(closes, _bar_close(data, bar))           # past the last closing by the chart close
            results = context.runtime.results.values
            values = results[first:min(last, len(results))]
        if spec.tuple_size:
            columns = list(zip(*values)) if values else [()] * spec.tuple_size
            return tuple(_intrabar_array(column, spec.elements[k] if k < len(spec.elements) else None)
                         for k, column in enumerate(columns))
        return _intrabar_array(values, spec.elements[0] if spec.elements else None)

    # -- mapping (TradingView q4 semantics) ---------------------------------------------------------------------------
    def _select(self, rt, node, spec, context: Context, args: dict):
        from .runtime import MISSING

        data, bar, store = rt.data, rt.bar, context.store
        index = None
        if store.n:
            if args.get("lookahead") == "lookahead_on":        # the requested bar containing the chart bar's open
                index = bisect_right(store.view("time"), int(data.time[bar])) - 1
            else:                                            # the latest requested bar closed by the chart bar's close
                index = bisect_right(store.view("close_time"), _bar_close(data, bar)) - 1
            index = index if index >= 0 else None
        opened = None if index is None else int(store.arrays["time"][index])
        selection = rt.buffer(("__security_selection__", node.id, rt.ctx_path))
        previous = selection.before(bar)
        selection.set(bar, opened)
        if index is None:
            return _na_like(spec)
        if args.get("gaps") == "gaps_on" and previous is not MISSING and previous == opened:
            return _na_like(spec)
        results = context.runtime.results.values
        return results[index] if index < len(results) else _na_like(spec)


def _same_prefix(old: Bars, new: Bars, n: int) -> bool:
    if n == 0:
        return True
    if new.size < n or old.size < n:
        return False
    return all(np.array_equal(getattr(old, c)[:n], getattr(new, c)[:n], equal_nan=True)
               for c in ("time", "close_time", "open", "high", "low", "close", "volume"))


def _intrabar_array(values, element: str | None) -> PineArray:
    """A new execution-local array of intrabar values (A1: snapshots and history are the runtime's)."""
    from .builtins.arrays import coerce_element

    if element is None:                                  # type unknown at analysis time: from the values
        sample = next((v for v in values if not is_na(v)), None)
        element = ("bool" if isinstance(sample, bool) else "int" if isinstance(sample, int) else
                   "string" if isinstance(sample, str) else "color" if isinstance(sample, Color) else "float")
    return PineArray([coerce_element(v, element, "request.security_lower_tf") for v in values], element)


def _na_like(spec):
    return tuple(NA for _ in range(spec.tuple_size)) if spec.tuple_size else NA


def _bar_close(data, bar: int) -> int:
    if data.close_time is not None and len(data.close_time) > bar:
        return int(data.close_time[bar])
    return int(data.time[bar]) + data.timeframe_seconds * 1000


def _parent_bars(data, bar: int, close_times: np.ndarray) -> Bars:
    n = bar + 1
    return Bars(data.time[:n], close_times[:n], data.open[:n], data.high[:n], data.low[:n], data.close[:n],
                data.volume[:n])


def _aggregate(base: Bars, start: int, stop: int, grid: BarGrid) -> list[tuple]:
    """Requested bars built from base bars [start, stop): every base bar inside a requested bar counts (MT5-style;
    session gaps do not drop a bar)."""
    rows, current = [], None
    for i in range(start, stop):
        o, h, l, c, v = (float(base.open[i]), float(base.high[i]), float(base.low[i]), float(base.close[i]),
                         float(base.volume[i]))
        if any(math.isnan(x) for x in (o, h, l, c)):
            continue
        opened, closed = grid.bucket(int(base.time[i]))
        if current is None or current[0] != opened:
            if current is not None:
                rows.append(tuple(current))
            current = [opened, closed, o, h, l, c, v]
        else:
            current[3], current[4] = max(current[3], h), min(current[4], l)
            current[5] = c
            current[6] += v
    if current is not None:
        rows.append(tuple(current))
    return rows


def security_literals(program) -> list[tuple[int, str | None, str | None]]:
    """(line, symbol literal or None, timeframe literal or None) of every request.security() call."""
    return [(spec.line, spec.symbol_literal, spec.timeframe_literal) for spec in program.security.values()]

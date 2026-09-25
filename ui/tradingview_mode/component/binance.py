"""Read-only Binance USDⓈ-M Futures market data for TradingView Mode Live.

Public market data only: no API key, no account endpoint, no order endpoint, no
user-data stream. Nothing here can trade.

Endpoints (audited against the live network, 2026-09-25):
  REST       https://fapi.binance.com/fapi/v1/{exchangeInfo,klines,time}
  klines     wss://fstream.binance.com/market/stream?streams=<sym>@kline_<tf>/<sym>@markPrice@1s
  top book   wss://fstream.binance.com/public/stream?streams=<sym>@depth5@500ms/...
Kline streams are served on ``/market`` only and book streams on ``/public``
only (the legacy ``/ws`` root accepts a kline subscription but never delivers
a message). XAUUSDT is a ``TRADIFI_PERPETUAL`` contract on the same USDⓈ-M
endpoints; BTCUSDT is ``PERPETUAL``.

Connection lifecycle:
* Binance closes a stream connection after 24 hours; every connection is
  recycled proactively before that (``MAX_CONNECTION_AGE_S``) and reactively
  on any close, with exponential backoff (never a busy loop).
* Server pings are answered with pongs by the ``websockets`` library itself.
  The client sends no keepalive pings; instead ``markPrice@1s`` makes the
  market socket speak every second, so silence means a dead socket: STALE
  after ``STALE_S`` and a forced reconnect after ``SILENCE_RECONNECT_S``.
* After every (re)connect the recent klines are fetched over REST and
  reconciled into the book, so a gap is filled and a candle that finalized
  while disconnected finalizes exactly once.

Ownership: connections live in a process-wide :class:`BinanceHub`, never in a
Streamlit rerun. A session holds a lease per stream; the same session asking
again gets the same stream (no duplicate subscription), switching releases the
old lease, and a stream nobody has touched for ``IDLE_TIMEOUT_S`` stops itself
(a closed browser tab cannot leak a socket or thread).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import math
import random
import threading
import time
from typing import Any, Callable

import pandas as pd

REST_BASE = "https://fapi.binance.com"
MARKET_WS = "wss://fstream.binance.com/market"
PUBLIC_WS = "wss://fstream.binance.com/public"

#: Contracts this terminal may stream, with the contract type Binance must report.
#: ``digits`` (tick-size decimals) is only the watchlist display default; a stream
#: uses the tick size exchangeInfo reports.
CONTRACTS: dict[str, dict[str, str]] = {
    "BTCUSDT": {"contract_type": "PERPETUAL", "label": "BTCUSDT Perpetual", "digits": 1},
    "XAUUSDT": {"contract_type": "TRADIFI_PERPETUAL", "label": "XAUUSDT Perpetual", "digits": 2},
}
#: Native Binance kline intervals used by Live mode.
INTERVALS: dict[str, int] = {"15m": 900, "30m": 1800, "1h": 3600}
SEED_BARS = 500
MAX_CONNECTION_AGE_S = 23 * 3600 + 30 * 60   # recycle 30 min before Binance's 24 h cut-off
STALE_S = 5.0                 # markPrice@1s arrives every second
SILENCE_RECONNECT_S = 20.0    # an open socket that stays silent this long is dead
KLINE_STALE_S = 60.0          # no kline update (no trades) for a minute: not LIVE
QUOTE_STALE_S = 10.0          # an older top-of-book is not shown
IDLE_TIMEOUT_S = 180.0        # > Chrome's 1/min timer throttling of hidden tabs
RECONCILE_MIN_INTERVAL_S = 5.0
BACKOFF_S = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
FATAL_RETRY_S = 60.0


class BinanceDataError(ValueError):
    """Data that cannot be trusted as sent (rejected, never drawn)."""


class BinanceNetworkError(OSError):
    """A transient network/HTTP failure (retried with backoff)."""


@dataclass(frozen=True)
class Endpoints:
    rest: str = REST_BASE
    market_ws: str = MARKET_WS
    public_ws: str = PUBLIC_WS


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    contract_type: str
    status: str
    tick_size: str
    digits: int
    underlying_type: str


@dataclass(frozen=True)
class Bar:
    time: int          # open time, epoch seconds UTC
    open: float
    high: float
    low: float
    close: float
    volume: float      # base-asset volume
    final: bool


@dataclass(frozen=True)
class KlineUpdate:
    bar: Bar
    event_ms: int


@dataclass(frozen=True)
class MarkPrice:
    mark: float
    index: float
    funding_rate: float
    next_funding_ms: int
    event_ms: int


@dataclass(frozen=True)
class TopOfBook:
    symbol: str
    bid: float
    bid_qty: float
    ask: float
    ask_qty: float
    event_ms: int
    update_id: int
    received_at: float = 0.0


# ---------------------------------------------------------------------------
# Parsing / validation (pure)
# ---------------------------------------------------------------------------

def _num(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise BinanceDataError(f"{name} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BinanceDataError(f"{name} must be a number.") from exc
    if not math.isfinite(number) or (positive and number <= 0) or number < 0:
        raise BinanceDataError(f"{name} must be finite and {'positive' if positive else 'non-negative'}.")
    return number


def _int(value: Any, name: str) -> int:
    if type(value) is not int or value < 0:
        raise BinanceDataError(f"{name} must be a non-negative integer.")
    return value


def tick_digits(tick_size: str) -> int:
    text = str(tick_size).rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def parse_contract(exchange_info: Any, symbol: str) -> ContractSpec:
    """The contract as Binance lists it; anything unexpected is refused."""
    if not isinstance(exchange_info, dict) or not isinstance(exchange_info.get("symbols"), list):
        raise BinanceDataError("exchangeInfo has no symbol list.")
    entry = next((item for item in exchange_info["symbols"] if isinstance(item, dict) and item.get("symbol") == symbol), None)
    if entry is None:
        raise BinanceDataError(f"{symbol} is not listed on Binance USDⓈ-M Futures.")
    expected = CONTRACTS[symbol]["contract_type"]
    if entry.get("contractType") != expected:
        raise BinanceDataError(f"{symbol} is a {entry.get('contractType')} contract, expected {expected}.")
    if entry.get("status") != "TRADING":
        raise BinanceDataError(f"{symbol} status is {entry.get('status')}, not TRADING.")
    price_filter = next((f for f in entry.get("filters", []) if f.get("filterType") == "PRICE_FILTER"), None)
    if not price_filter or _num(price_filter.get("tickSize"), "tickSize", positive=True) <= 0:
        raise BinanceDataError(f"{symbol} has no valid tick size.")
    return ContractSpec(symbol, entry["contractType"], entry["status"], str(price_filter["tickSize"]),
                        tick_digits(price_filter["tickSize"]), str(entry.get("underlyingType", "")))


def _make_bar(interval: str, open_ms: Any, close_ms: Any, o: Any, h: Any, l: Any, c: Any, v: Any, final: bool,
              where: str) -> Bar:
    seconds = INTERVALS[interval]
    open_ms, close_ms = _int(open_ms, f"{where} open time"), _int(close_ms, f"{where} close time")
    if open_ms % (seconds * 1000):
        raise BinanceDataError(f"{where}: open time not aligned to {interval}.")
    if close_ms != open_ms + seconds * 1000 - 1:
        raise BinanceDataError(f"{where}: close time does not match the {interval} interval.")
    o, h, l, c = (_num(x, f"{where} {n}", positive=True) for x, n in ((o, "open"), (h, "high"), (l, "low"), (c, "close")))
    if h < max(o, c) or l > min(o, c) or h < l:
        raise BinanceDataError(f"{where}: high/low inconsistent with open/close.")
    return Bar(open_ms // 1000, o, h, l, c, _num(v, f"{where} volume"), bool(final))


def parse_rest_klines(rows: Any, interval: str, server_ms: int) -> list[Bar]:
    """REST klines -> bars. A bar is final once its close time has passed on the server clock."""
    if not isinstance(rows, list):
        raise BinanceDataError("klines response must be a list.")
    bars: list[Bar] = []
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) < 7:
            raise BinanceDataError(f"kline row {index} is malformed.")
        bars.append(_make_bar(interval, row[0], row[6], *row[1:6], final=row[6] < server_ms, where=f"kline {index}"))
    times = [bar.time for bar in bars]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise BinanceDataError("klines must be strictly increasing without duplicates.")
    first_forming = next((i for i, bar in enumerate(bars) if not bar.final), len(bars))
    if any(bar.final for bar in bars[first_forming:]):
        raise BinanceDataError("a final kline follows a forming one.")
    return bars


def parse_kline_event(message: Any, symbol: str, interval: str) -> KlineUpdate:
    if not isinstance(message, dict) or message.get("e") != "kline" or not isinstance(message.get("k"), dict):
        raise BinanceDataError("not a kline event.")
    k = message["k"]
    if message.get("s") != symbol or k.get("s") != symbol:
        raise BinanceDataError(f"kline for {message.get('s')!r}, expected {symbol}.")
    if k.get("i") != interval:
        raise BinanceDataError(f"kline interval {k.get('i')!r}, expected {interval}.")
    if not isinstance(k.get("x"), bool):
        raise BinanceDataError("kline final flag must be a boolean.")
    bar = _make_bar(interval, k.get("t"), k.get("T"), k.get("o"), k.get("h"), k.get("l"), k.get("c"), k.get("v"),
                    k["x"], "kline event")
    event_ms = _int(message.get("E"), "event time")
    if event_ms < bar.time * 1000:
        raise BinanceDataError("kline event time precedes the bar open.")
    return KlineUpdate(bar, event_ms)


def parse_mark_event(message: Any, symbol: str) -> MarkPrice:
    if not isinstance(message, dict) or message.get("e") != "markPriceUpdate" or message.get("s") != symbol:
        raise BinanceDataError("not a mark price event for this symbol.")
    try:
        funding = float(message.get("r"))
    except (TypeError, ValueError) as exc:
        raise BinanceDataError("funding rate must be a number.") from exc
    if not math.isfinite(funding):
        raise BinanceDataError("funding rate must be finite.")
    return MarkPrice(_num(message.get("p"), "mark price", positive=True), _num(message.get("i"), "index price", positive=True),
                     funding, _int(message.get("T"), "next funding time"), _int(message.get("E"), "event time"))


def parse_depth_event(message: Any, symbols: tuple[str, ...]) -> TopOfBook:
    """Best bid/ask from a ``depth5@500ms`` snapshot (first level of each side)."""
    if not isinstance(message, dict) or message.get("e") != "depthUpdate" or message.get("s") not in symbols:
        raise BinanceDataError("not a depth event for a live symbol.")
    bids, asks = message.get("b"), message.get("a")
    if not (isinstance(bids, list) and bids and isinstance(asks, list) and asks
            and all(isinstance(level, list) and len(level) >= 2 for level in (bids[0], asks[0]))):
        raise BinanceDataError("depth event has no top of book.")
    bid, ask = _num(bids[0][0], "bid", positive=True), _num(asks[0][0], "ask", positive=True)
    if ask < bid:
        raise BinanceDataError("ask below bid.")
    return TopOfBook(message["s"], bid, _num(bids[0][1], "bid qty"), ask, _num(asks[0][1], "ask qty"),
                     _int(message.get("E"), "event time"), _int(message.get("u"), "update id"))


def unwrap(message: Any) -> Any:
    """Combined-stream envelope ``{"stream", "data"}`` -> data."""
    return message["data"] if isinstance(message, dict) and "stream" in message and "data" in message else message


# ---------------------------------------------------------------------------
# Kline book: forming candle, exactly-once finalization, duplicates, ordering
# ---------------------------------------------------------------------------

class KlineBook:
    """In-memory bars of one symbol/interval (never written anywhere).

    Not thread-safe on its own; :class:`KlineStream` guards it with a lock.
    """

    def __init__(self, symbol: str, interval: str, limit: int = SEED_BARS):
        self.symbol, self.interval, self.limit = symbol, interval, limit
        self.seconds = INTERVALS[interval]
        self.bars: list[Bar] = []
        self.last_event_ms = 0
        self.forming_asof_ms = 0      # a REST snapshot of the forming bar is as of this server time
        self.finalized = 0            # candles finalized (each bar time at most once)
        self.duplicates = 0
        self.superseded = 0           # queued messages older than the REST snapshot (benign, ignored)
        self.out_of_order = 0
        self.malformed = 0
        self.needs_reconcile = False

    # -- seeding / reconciliation ------------------------------------------------
    def seed(self, bars: list[Bar], asof_ms: int) -> None:
        self.bars = list(bars[-self.limit:])
        self.forming_asof_ms = asof_ms
        self.needs_reconcile = False

    def reconcile(self, bars: list[Bar], asof_ms: int) -> int:
        """Merge REST bars (authoritative for what they cover). Returns bars changed."""
        index = {bar.time: i for i, bar in enumerate(self.bars)}
        changed = 0
        merged = list(self.bars)
        for bar in bars:
            if bar.time in index:
                current = merged[index[bar.time]]
                if current == bar:
                    continue
                if current.final and not bar.final:
                    continue  # never un-finalize
                if bar.final and not current.final:
                    self.finalized += 1
                merged[index[bar.time]] = bar
            else:
                if bar.final:
                    self.finalized += 1
                merged.append(bar)
            changed += 1
        merged.sort(key=lambda item: item.time)
        self.bars = merged[-self.limit:]
        self.forming_asof_ms = max(self.forming_asof_ms, asof_ms)
        self.needs_reconcile = False
        return changed

    # -- live updates -----------------------------------------------------------
    def apply(self, update: KlineUpdate) -> str:
        """new | update | final | duplicate | superseded | out_of_order."""
        bar = update.bar
        if update.event_ms < self.last_event_ms:
            self.out_of_order += 1
            return "out_of_order"
        if not self.bars:
            self.bars.append(bar)
            self.last_event_ms = update.event_ms
            return "new"
        last = self.bars[-1]
        if bar.time > last.time:
            if bar.time != last.time + self.seconds or not last.final:
                # A gap, or the previous candle never received its final message:
                # accept the new candle and let REST fill/finalize the rest.
                self.needs_reconcile = True
            self.bars.append(bar)
            del self.bars[:-self.limit]
            self.last_event_ms = update.event_ms
            if bar.final:
                self.finalized += 1
            return "new"
        position = next((i for i in range(len(self.bars) - 1, -1, -1) if self.bars[i].time == bar.time), None)
        if position is None:
            self.out_of_order += 1
            return "out_of_order"
        current = self.bars[position]
        if current.final:
            if current == bar:
                self.duplicates += 1
                return "duplicate"
            self.out_of_order += 1       # a finalized candle never changes again
            return "out_of_order"
        if position != len(self.bars) - 1 and not bar.final:
            self.out_of_order += 1       # only a late *final* message may touch an older candle
            return "out_of_order"
        if position == len(self.bars) - 1 and update.event_ms < self.forming_asof_ms:
            self.superseded += 1         # older than the REST snapshot we already hold
            return "superseded"
        self.last_event_ms = update.event_ms
        if current == bar:
            self.duplicates += 1
            return "duplicate"
        self.bars[position] = bar
        if bar.final:
            self.finalized += 1
            return "final"
        return "update"

    def last_final_time(self) -> int | None:
        return next((bar.time for bar in reversed(self.bars) if bar.final), None)

    def frame(self) -> pd.DataFrame:
        if not self.bars:
            return pd.DataFrame({"timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
                                 **{c: pd.Series([], dtype=float) for c in ("open", "high", "low", "close", "volume")},
                                 "final": pd.Series([], dtype=bool)})
        return pd.DataFrame({
            "timestamp": pd.to_datetime([bar.time for bar in self.bars], unit="s", utc=True),
            "open": [bar.open for bar in self.bars], "high": [bar.high for bar in self.bars],
            "low": [bar.low for bar in self.bars], "close": [bar.close for bar in self.bars],
            "volume": [bar.volume for bar in self.bars], "final": [bar.final for bar in self.bars],
        })


# ---------------------------------------------------------------------------
# REST (public market data only)
# ---------------------------------------------------------------------------

class BinanceRest:
    """Public USDⓈ-M market-data REST. No key, no signed endpoint."""

    def __init__(self, base: str = REST_BASE, timeout: float = 10.0, session=None):
        import requests  # local: tests inject a fake REST object instead

        self.base, self.timeout = base.rstrip("/"), timeout
        self._session = session or requests.Session()
        self._requests = requests

    def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            response = self._session.get(f"{self.base}{path}", params=params, timeout=self.timeout)
        except self._requests.RequestException as exc:
            raise BinanceNetworkError(f"Binance REST unreachable ({type(exc).__name__}).") from exc
        if response.status_code in (418, 429) or response.status_code >= 500:
            raise BinanceNetworkError(f"Binance REST HTTP {response.status_code}.")
        if response.status_code != 200:
            raise BinanceDataError(f"Binance REST HTTP {response.status_code}: {response.text[:200]}")
        try:
            return response.json()
        except ValueError as exc:
            raise BinanceDataError("Binance REST returned invalid JSON.") from exc

    def server_time_ms(self) -> int:
        return _int((self._get("/fapi/v1/time") or {}).get("serverTime"), "serverTime")

    def contract(self, symbol: str) -> ContractSpec:
        return parse_contract(self._get("/fapi/v1/exchangeInfo"), symbol)

    def klines(self, symbol: str, interval: str, limit: int) -> Any:
        return self._get("/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": int(limit)})


# ---------------------------------------------------------------------------
# One WebSocket with reconnect, backoff, 24 h recycling and a silence watchdog
# ---------------------------------------------------------------------------

def _default_connect(url: str):
    from websockets.sync.client import connect

    # No client keepalive pings (see module docstring); server pings are ponged automatically.
    return connect(url, open_timeout=10, close_timeout=2, ping_interval=None, max_size=2 ** 22)


@dataclass
class ChannelStats:
    state: str = "idle"            # idle | connecting | open | reconnecting | error | stopped
    connections: int = 0           # successful opens
    recycles: int = 0              # proactive (pre-24 h) reconnects
    silent_reconnects: int = 0
    messages: int = 0
    bad_messages: int = 0
    opened_at: float | None = None
    last_message_at: float | None = None
    last_error: str | None = None
    next_retry_at: float | None = None
    urls: list[str] = field(default_factory=list)


class Channel:
    """Runs one WebSocket in the calling thread until ``should_stop()``."""

    def __init__(self, url: str, *, on_message: Callable[[Any], None], before_stream: Callable[[], None] | None = None,
                 connect: Callable[[str], Any] = _default_connect, clock: Callable[[], float] = time.time,
                 max_age_s: float = MAX_CONNECTION_AGE_S, silence_s: float = SILENCE_RECONNECT_S,
                 backoff: tuple[float, ...] = BACKOFF_S, wait: Callable[[float], bool] | None = None,
                 should_stop: Callable[[], bool] = lambda: False):
        self.url, self.on_message, self.before_stream = url, on_message, before_stream
        self.connect, self.clock, self.max_age_s, self.silence_s, self.backoff = connect, clock, max_age_s, silence_s, backoff
        self.should_stop = should_stop
        self.wait = wait or (lambda seconds: (time.sleep(seconds), False)[1])
        self.stats = ChannelStats()

    def run(self) -> None:
        attempt = 0
        while not self.should_stop():
            self.stats.state = "connecting"
            recycle = False
            try:
                with self.connect(self.url) as socket:
                    now = self.clock()
                    self.stats.opened_at = now
                    self.stats.last_message_at = now
                    self.stats.connections += 1
                    self.stats.urls.append(self.url)
                    self.stats.state = "open"
                    self.stats.last_error = None
                    if self.before_stream:
                        self.before_stream()  # REST seed/reconcile while messages queue on the socket
                    healthy = False
                    while not self.should_stop():
                        now = self.clock()
                        if now - self.stats.opened_at >= self.max_age_s:
                            self.stats.recycles += 1
                            recycle = True
                            break
                        if now - self.stats.last_message_at >= self.silence_s:
                            self.stats.silent_reconnects += 1
                            self.stats.last_error = f"no message for {now - self.stats.last_message_at:.0f}s"
                            break
                        try:
                            raw = socket.recv(timeout=0.5)
                        except TimeoutError:
                            continue
                        self.stats.last_message_at = self.clock()
                        self.stats.messages += 1
                        healthy = True
                        try:
                            self.on_message(unwrap(json.loads(raw)))
                        except (ValueError, KeyError, TypeError):
                            self.stats.bad_messages += 1
                    if healthy:
                        attempt = 0
            except BinanceDataError as exc:
                # Permanent-looking (unknown symbol, bad history): report and retry slowly.
                self.stats.state = "error"
                self.stats.last_error = str(exc)
                self._sleep(FATAL_RETRY_S)
                continue
            except Exception as exc:  # network, handshake, close frames, REST outage
                self.stats.last_error = f"{type(exc).__name__}: {exc}"[:200]
            if self.should_stop():
                break
            self.stats.state = "reconnecting"
            if recycle:
                self.stats.next_retry_at = self.clock()
                continue  # proactive recycle: reconnect at once
            delay = self.backoff[min(attempt, len(self.backoff) - 1)] * random.uniform(0.8, 1.2)
            attempt += 1
            self._sleep(delay)
        self.stats.state = "stopped"

    def _sleep(self, seconds: float) -> None:
        self.stats.next_retry_at = self.clock() + seconds
        self.wait(seconds)


# ---------------------------------------------------------------------------
# Streams (each runs its channel in one daemon thread)
# ---------------------------------------------------------------------------

class _Worker:
    def __init__(self, clock: Callable[[], float], idle_timeout_s: float):
        self.clock, self.idle_timeout_s = clock, idle_timeout_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_touched = clock()
        self.lock = threading.Lock()

    def touch(self) -> None:
        self.last_touched = self.clock()

    def _should_stop(self) -> bool:
        if not self._stop.is_set() and self.clock() - self.last_touched > self.idle_timeout_s:
            self._stop.set()  # nobody is watching: stop instead of leaking
        return self._stop.is_set()

    def _wait(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self._should_stop():
            self._stop.wait(min(0.5, max(0.0, deadline - time.monotonic())))
        return self._stop.is_set()

    def start(self, name: str, target: Callable[[], None]) -> None:
        self._thread = threading.Thread(target=target, name=name, daemon=True)
        self._thread.start()

    def stop(self, join_s: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(join_s)

    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()


class KlineStream(_Worker):
    """Klines + mark price for one contract/interval, seeded and reconciled over REST."""

    def __init__(self, symbol: str, interval: str, *, endpoints: Endpoints = Endpoints(), rest=None,
                 connect: Callable[[str], Any] = _default_connect, clock: Callable[[], float] = time.time,
                 max_age_s: float = MAX_CONNECTION_AGE_S, silence_s: float = SILENCE_RECONNECT_S,
                 idle_timeout_s: float = IDLE_TIMEOUT_S, backoff: tuple[float, ...] = BACKOFF_S):
        if symbol not in CONTRACTS or interval not in INTERVALS:
            raise ValueError(f"unsupported Binance live stream {symbol} {interval}")
        super().__init__(clock, idle_timeout_s)
        self.symbol, self.interval = symbol, interval
        self.rest = rest if rest is not None else BinanceRest(endpoints.rest)
        self.book = KlineBook(symbol, interval)
        self.spec: ContractSpec | None = None
        self.mark: MarkPrice | None = None
        self.last_kline_at: float | None = None
        self.last_reconcile_at = 0.0
        self.reconciles = 0
        self.fatal: str | None = None
        stream = f"{symbol.lower()}@kline_{interval}/{symbol.lower()}@markPrice@1s"
        self.channel = Channel(f"{endpoints.market_ws}/stream?streams={stream}", on_message=self._on_message,
                               before_stream=self._before_stream, connect=connect, clock=clock, max_age_s=max_age_s,
                               silence_s=silence_s, backoff=backoff, wait=self._wait, should_stop=self._should_stop)

    def start(self) -> "KlineStream":  # type: ignore[override]
        super().start(f"binance-{self.symbol}-{self.interval}", self.channel.run)
        return self

    # -- REST side ------------------------------------------------------------------
    def _before_stream(self) -> None:
        try:
            spec = self.spec or self.rest.contract(self.symbol)
        except BinanceDataError as exc:
            self.fatal = str(exc)
            raise
        self.spec, self.fatal = spec, None
        self._reconcile(full=not self.book.bars)

    def _reconcile(self, full: bool = False) -> None:
        server_ms = self.rest.server_time_ms()
        with self.lock:
            last = self.book.bars[-1].time if self.book.bars else None
        missing = SEED_BARS if full or last is None else int((server_ms / 1000 - last) // self.book.seconds) + 2
        rows = self.rest.klines(self.symbol, self.interval, min(SEED_BARS, max(2, missing)))
        bars = parse_rest_klines(rows, self.interval, server_ms)
        with self.lock:
            if full or last is None or missing >= SEED_BARS:
                self.book.seed(bars, server_ms)   # too far behind to stitch: reload the window
            else:
                self.book.reconcile(bars, server_ms)
            self.reconciles += 1
        self.last_reconcile_at = self.clock()

    # -- stream side --------------------------------------------------------------------
    def _on_message(self, message: Any) -> None:
        kind = message.get("e") if isinstance(message, dict) else None
        try:
            if kind == "kline":
                update = parse_kline_event(message, self.symbol, self.interval)
                with self.lock:
                    self.book.apply(update)
                    needs = self.book.needs_reconcile
                self.last_kline_at = self.clock()
                if needs and self.clock() - self.last_reconcile_at >= RECONCILE_MIN_INTERVAL_S:
                    try:
                        self._reconcile()
                    except (BinanceNetworkError, BinanceDataError):
                        self.last_reconcile_at = self.clock()  # retried on a later message
            elif kind == "markPriceUpdate":
                mark = parse_mark_event(message, self.symbol)
                with self.lock:
                    if self.mark is None or mark.event_ms >= self.mark.event_ms:
                        self.mark = mark
            else:
                raise BinanceDataError(f"unexpected event {kind!r}")
        except BinanceDataError:
            with self.lock:
                self.book.malformed += 1

    # -- view (called from Streamlit reruns) -------------------------------------------------
    def status(self, now: float) -> tuple[str, str]:
        stats = self.channel.stats
        if self.fatal:
            return "ERROR", f"Binance Futures refused {self.symbol}: {self.fatal}"
        retry = f" Retrying in {max(0.0, (stats.next_retry_at or now) - now):.0f}s." if stats.next_retry_at else ""
        if not self.book.bars:
            if stats.last_error and stats.state in ("reconnecting", "error"):
                return "DISCONNECTED", f"Cannot reach Binance Futures ({stats.last_error}).{retry}"
            return "CONNECTING", "Connecting to Binance Futures and loading recent candles…"
        if stats.state != "open":
            if stats.state == "connecting":
                return "CONNECTING", "Reconnecting to Binance Futures…"
            return "DISCONNECTED", f"Binance stream closed ({stats.last_error or 'reconnecting'}).{retry}"
        silent = now - (stats.last_message_at or now)
        if silent > STALE_S:
            return "STALE", (f"No Binance message for {silent:.0f}s although the socket is open; "
                             f"reconnecting after {SILENCE_RECONNECT_S:.0f}s.")
        kline_age = now - (self.last_kline_at or stats.opened_at or now)
        if kline_age > KLINE_STALE_S:
            return "STALE", f"No {self.symbol} kline update for {kline_age:.0f}s (no trades)."
        return "LIVE", "Receiving Binance Futures public market data."

    def snapshot(self, now: float) -> dict:
        with self.lock:
            frame = self.book.frame()
            last = self.book.bars[-1] if self.book.bars else None
            book = {"finalized": self.book.finalized, "duplicates": self.book.duplicates,
                    "superseded": self.book.superseded, "out_of_order": self.book.out_of_order,
                    "malformed": self.book.malformed}
            mark = self.mark
        status, reason = self.status(now)
        stats = self.channel.stats
        return {"frame": frame, "status": status, "reason": reason, "spec": self.spec, "mark": mark,
                "last_price": last.close if last else None,
                "forming_bar_time": last.time if last is not None and not last.final else None,
                "updated_at": stats.last_message_at, "book": book, "reconciles": self.reconciles,
                "connections": stats.connections, "recycles": stats.recycles,
                "connection_age_s": (now - stats.opened_at) if stats.opened_at and stats.state == "open" else None}


class QuoteBoard(_Worker):
    """Top of book (best bid/ask) for every live contract over one public socket."""

    def __init__(self, symbols: tuple[str, ...] = tuple(CONTRACTS), *, endpoints: Endpoints = Endpoints(),
                 connect: Callable[[str], Any] = _default_connect, clock: Callable[[], float] = time.time,
                 max_age_s: float = MAX_CONNECTION_AGE_S, silence_s: float = SILENCE_RECONNECT_S,
                 idle_timeout_s: float = IDLE_TIMEOUT_S, backoff: tuple[float, ...] = BACKOFF_S):
        super().__init__(clock, idle_timeout_s)
        self.symbols = symbols
        self.books: dict[str, TopOfBook] = {}
        self.rejected = 0
        streams = "/".join(f"{s.lower()}@depth5@500ms" for s in symbols)
        self.channel = Channel(f"{endpoints.public_ws}/stream?streams={streams}", on_message=self._on_message,
                               connect=connect, clock=clock, max_age_s=max_age_s, silence_s=silence_s,
                               backoff=backoff, wait=self._wait, should_stop=self._should_stop)

    def start(self) -> "QuoteBoard":  # type: ignore[override]
        super().start("binance-quotes", self.channel.run)
        return self

    def _on_message(self, message: Any) -> None:
        try:
            top = parse_depth_event(message, self.symbols)
        except BinanceDataError:
            self.rejected += 1
            return
        with self.lock:
            previous = self.books.get(top.symbol)
            if previous is not None and top.update_id <= previous.update_id:
                self.rejected += 1   # duplicate or out-of-order book update
                return
            self.books[top.symbol] = replace(top, received_at=self.clock())

    def quote(self, symbol: str, now: float) -> TopOfBook | None:
        """The latest top of book, or None if it is too old to show."""
        with self.lock:
            top = self.books.get(symbol)
        if top is None or self.channel.stats.state != "open" or now - top.received_at > QUOTE_STALE_S:
            return None
        return top


# ---------------------------------------------------------------------------
# Process-wide connection owner
# ---------------------------------------------------------------------------

class BinanceHub:
    """Owns every Binance socket in this Streamlit process (see module docstring)."""

    def __init__(self, *, kline_factory: Callable[[str, str], KlineStream] | None = None,
                 quotes_factory: Callable[[], QuoteBoard] | None = None):
        self._kline_factory = kline_factory or (lambda symbol, interval: KlineStream(symbol, interval))
        self._quotes_factory = quotes_factory or (lambda: QuoteBoard())
        self._lock = threading.Lock()
        self._workers: dict[tuple, _Worker] = {}
        self._leases: dict[str, dict[str, tuple]] = {}   # session -> {"kline"|"quotes": key}

    def _lease(self, session_id: str, kind: str, key: tuple, factory: Callable[[], _Worker]) -> _Worker:
        with self._lock:
            self._leases.setdefault(session_id, {})[kind] = key
            worker = self._workers.get(key)
            if worker is None or not worker.alive():
                worker = factory().start()
                self._workers[key] = worker
            worker.touch()
            stale = self._collect()
        for old in stale:
            old.stop()
        return worker

    def kline(self, session_id: str, symbol: str, interval: str) -> KlineStream:
        return self._lease(session_id, "kline", ("kline", symbol, interval),
                           lambda: self._kline_factory(symbol, interval))  # type: ignore[return-value]

    def quotes(self, session_id: str) -> QuoteBoard:
        return self._lease(session_id, "quotes", ("quotes",), self._quotes_factory)  # type: ignore[return-value]

    def release(self, session_id: str, kind: str | None = None) -> None:
        with self._lock:
            leases = self._leases.get(session_id, {})
            for name in [kind] if kind else list(leases):
                leases.pop(name, None)
            if not leases:
                self._leases.pop(session_id, None)
            stale = self._collect()
        for worker in stale:
            worker.stop()

    def _collect(self) -> list[_Worker]:
        """Workers no session leases (or that stopped themselves). Caller holds the lock."""
        wanted = {key for leases in self._leases.values() for key in leases.values()}
        stale = [key for key, worker in self._workers.items() if key not in wanted or not worker.alive()]
        return [self._workers.pop(key) for key in stale]

    def active(self) -> list[tuple]:
        with self._lock:
            return sorted(key for key, worker in self._workers.items() if worker.alive())

    def shutdown(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
            self._leases.clear()
        for worker in workers:
            worker.stop()


_HUB: BinanceHub | None = None
_HUB_LOCK = threading.Lock()


def hub() -> BinanceHub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = BinanceHub()
        return _HUB

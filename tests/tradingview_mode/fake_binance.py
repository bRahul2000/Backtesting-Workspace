"""Deterministic stand-ins for Binance REST and WebSocket (tests only).

``FakeMarket`` is the truth: bars per symbol/interval. ``FakeRest`` serves it
like /fapi/v1/klines; ``FakeConnect`` hands out sockets whose messages the test
pushes. ``Clock`` is wall time plus a jump offset, so a 24 h connection
lifetime can be crossed instantly.
"""
from __future__ import annotations

import queue
import threading
import time

from ui.tradingview_mode.component import binance as B


class Clock:
    def __init__(self):
        self.offset = 0.0

    def __call__(self) -> float:
        return time.time() + self.offset

    def jump(self, seconds: float) -> None:
        self.offset += seconds


def kline_row(t: int, o: float, h: float, l: float, c: float, v: float = 1.0, seconds: int = 900) -> list:
    return [t * 1000, f"{o:.2f}", f"{h:.2f}", f"{l:.2f}", f"{c:.2f}", f"{v:.3f}", (t + seconds) * 1000 - 1,
            "0", 1, "0", "0", "0"]


def kline_msg(t: int, o: float, h: float, l: float, c: float, *, final: bool, event_ms: int, v: float = 1.0,
              symbol: str = "BTCUSDT", interval: str = "15m", seconds: int = 900, combined: bool = True) -> dict:
    data = {"e": "kline", "E": event_ms, "s": symbol,
            "k": {"t": t * 1000, "T": (t + seconds) * 1000 - 1, "s": symbol, "i": interval, "f": 1, "L": 2,
                  "o": f"{o:.2f}", "c": f"{c:.2f}", "h": f"{h:.2f}", "l": f"{l:.2f}", "v": f"{v:.3f}", "n": 3,
                  "x": final, "q": "0", "V": "0", "Q": "0", "B": "0"}}
    return {"stream": f"{symbol.lower()}@kline_{interval}", "data": data} if combined else data


def mark_msg(event_ms: int, price: float = 80000.0, symbol: str = "BTCUSDT") -> dict:
    return {"stream": f"{symbol.lower()}@markPrice@1s",
            "data": {"e": "markPriceUpdate", "E": event_ms, "s": symbol, "p": f"{price:.8f}", "ap": f"{price:.8f}",
                     "P": f"{price:.8f}", "i": f"{price - 5:.8f}", "r": "0.00010000", "T": event_ms + 3_600_000}}


def depth_msg(event_ms: int, update_id: int, bid: float, ask: float, symbol: str = "BTCUSDT") -> dict:
    return {"stream": f"{symbol.lower()}@depth5@500ms",
            "data": {"e": "depthUpdate", "E": event_ms, "T": event_ms, "s": symbol, "U": update_id - 1, "u": update_id,
                     "pu": update_id - 2, "b": [[f"{bid:.2f}", "1.000"]], "a": [[f"{ask:.2f}", "2.000"]]}}


class FakeMarket:
    """Bars keyed by open time; the newest may be forming (final decided by server time)."""

    def __init__(self, clock: Clock, seconds: int = 900, count: int = 3000, price: float = 80000.0):
        self.clock, self.seconds = clock, seconds
        now = int(clock())
        first = (now // seconds - count + 1) * seconds
        self.bars = {}
        for i in range(count):
            t = first + i * seconds
            p = price + i
            self.bars[t] = (p, p + 5, p - 5, p + 1, 10.0)

    def extend_to_now(self) -> None:
        last = max(self.bars)
        now = int(self.clock())
        while last + self.seconds <= now:
            last += self.seconds
            p = self.bars[last - self.seconds][3]
            self.bars[last] = (p, p + 5, p - 5, p + 2, 10.0)

    def rows(self, limit: int, end_ms: int | None = None) -> list:
        """Like /fapi/v1/klines: the ``limit`` newest bars opening at or before endTime."""
        self.extend_to_now()
        times = [t for t in sorted(self.bars) if end_ms is None or t * 1000 <= end_ms][-limit:]
        return [kline_row(t, *self.bars[t][:4], self.bars[t][4], seconds=self.seconds) for t in times]


class FakeRest:
    def __init__(self, market: FakeMarket, *, contract_error: str | None = None, offline: bool = False):
        self.market, self.contract_error, self.offline = market, contract_error, offline
        self.calls: list[tuple] = []

    def _check(self):
        if self.offline:
            raise B.BinanceNetworkError("offline")

    def server_time_ms(self) -> int:
        self._check()
        self.calls.append(("time",))
        return int(self.market.clock() * 1000)

    def contract(self, symbol: str) -> B.ContractSpec:
        self._check()
        self.calls.append(("contract", symbol))
        if self.contract_error:
            raise B.BinanceDataError(self.contract_error)
        info = B.CONTRACTS[symbol]
        return B.ContractSpec(symbol, info["contract_type"], "TRADING", "0.10" if symbol == "BTCUSDT" else "0.01",
                              info["digits"], "COIN")

    def klines(self, symbol: str, interval: str, limit: int, end_ms: int | None = None) -> list:
        self._check()
        if not 1 <= limit <= 1500:
            raise B.BinanceDataError("Binance REST HTTP 400: limit must be 1..1500")
        self.calls.append(("klines", symbol, interval, limit) if end_ms is None else ("klines", symbol, interval, limit, end_ms))
        return self.market.rows(limit, end_ms)


class FakeSocket:
    def __init__(self, url: str):
        self.url = url
        self.inbox: queue.Queue = queue.Queue()
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed.set()
        return False

    def push(self, message) -> None:
        import json
        self.inbox.put(json.dumps(message) if not isinstance(message, (str, Exception)) else message)

    def drop(self) -> None:
        """Server-side close (e.g. Binance's 24 h cut-off)."""
        self.inbox.put(ConnectionResetError("server closed the connection"))

    def recv(self, timeout: float):
        try:
            item = self.inbox.get(timeout=min(timeout, 0.02))
        except queue.Empty:
            raise TimeoutError from None
        if isinstance(item, Exception):
            raise item
        return item


class FakeConnect:
    def __init__(self, *, fail: bool = False):
        self.sockets: list[FakeSocket] = []
        self.attempts: list[float] = []
        self.fail = fail
        self.lock = threading.Lock()

    def __call__(self, url: str) -> FakeSocket:
        with self.lock:
            self.attempts.append(time.monotonic())
            if self.fail:
                raise ConnectionRefusedError("network unreachable")
            socket = FakeSocket(url)
            self.sockets.append(socket)
            return socket

    @property
    def current(self) -> FakeSocket:
        return self.sockets[-1]


def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def fake_stream(symbol="BTCUSDT", interval="15m", *, clock=None, rest=None, connect=None, **kwargs) -> B.KlineStream:
    clock = clock or Clock()
    seconds = B.INTERVALS[interval]
    rest = rest or FakeRest(FakeMarket(clock, seconds))
    connect = connect or FakeConnect()
    kwargs.setdefault("backoff", (0.05, 0.1))
    kwargs.setdefault("idle_timeout_s", 10 ** 9)
    return B.KlineStream(symbol, interval, rest=rest, connect=connect, clock=clock, **kwargs)

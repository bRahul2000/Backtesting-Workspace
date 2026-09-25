"""Live market-data providers for TradingView Mode (read-only).

Two logical markets, each available from two sources that are *different
instruments* and are never mixed:

  BTC   Binance Futures BTCUSDT Perpetual  |  Exness MT5 BTCUSDm (CFD)
  Gold  Binance Futures XAUUSDT Perpetual  |  Exness MT5 XAUUSDm (CFD)

Every provider returns a :class:`LiveView`: one bar frame from that provider
alone, a status dict for the payload and an identity that travels with the
data (so a later comparison tool can line up BTCUSDT Perp vs BTCUSDm by time
without losing which is which). React only renders what a view contains.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from . import binance
from . import live as mt5

LIVE_TIMEFRAMES: tuple[str, ...] = ("15m", "30m", "1h")
SOURCES: dict[str, str] = {"binance": "Binance Futures", "exness": "Exness MT5"}
DEFAULT_SOURCE = "binance"
MARKETS: dict[str, dict[str, str]] = {
    "BTC": {"label": "BTC", "binance": "BTCUSDT", "exness": "BTCUSDm"},
    "GOLD": {"label": "Gold", "binance": "XAUUSDT", "exness": "XAUUSDm"},
}
#: Registry instrument -> live market (used only to preselect the Live market).
INSTRUMENT_MARKETS = {"BTCUSD": "BTC", "XAUUSDm": "GOLD", "XAUUSD": "GOLD"}
UNSUPPORTED_MESSAGE = "Live mode supports BTC and Gold (Binance Futures or Exness MT5)."
BINANCE_NOTE = "Reference market feed — execution prices may differ from Exness."
STATUSES = ("CONNECTING", "LIVE", "STALE", "DISCONNECTED", "ERROR")

assert set(LIVE_TIMEFRAMES) == set(binance.INTERVALS) == set(mt5.LIVE_TIMEFRAMES)


@dataclass(frozen=True)
class LiveState:
    """Live mode. ``streaming`` is False during setup (nothing is connected or
    read until Go Live)."""

    market: str | None
    source: str
    timeframe: str
    streaming: bool = False

    @property
    def symbol(self) -> str | None:
        return provider_symbol(self.market, self.source) if self.market else None

    @property
    def target(self) -> tuple[str, str, str] | None:
        """(source, provider symbol, timeframe) while streaming, else None."""
        return (self.source, self.symbol, self.timeframe) if self.streaming and self.market else None


def provider_symbol(market: str, source: str) -> str:
    return MARKETS[market][source]


def market_for_instrument(instrument: str | None) -> str | None:
    return INSTRUMENT_MARKETS.get(instrument or "")


def identity(market: str, source: str) -> dict[str, Any]:
    """What the data *is*. Kept intact end to end; never normalized away."""
    symbol = provider_symbol(market, source)
    if source == "binance":
        contract = binance.CONTRACTS[symbol]
        return {"market": market, "source": source, "source_label": SOURCES[source], "provider": "Binance Futures",
                "venue": "Binance USDⓈ-M Futures", "symbol": symbol, "contract": contract["label"],
                "contract_type": contract["contract_type"], "instrument_kind": "USDT-margined perpetual futures",
                "instrument": contract["label"], "dataset_key": f"BINANCE_LIVE:{symbol}",
                "volume_unit": "base asset", "time_basis": "UTC (exchange time)"}
    info = mt5.LIVE_SYMBOLS[symbol]
    return {"market": market, "source": source, "source_label": SOURCES[source], "provider": info["provider"],
            "venue": "Exness (MetaTrader 5)", "symbol": symbol, "contract": symbol, "contract_type": "CFD",
            "instrument_kind": "broker CFD", "instrument": info["instrument"], "dataset_key": f"MT5_LIVE:{symbol}",
            "volume_unit": "tick volume", "time_basis": "UTC (broker server time, verified UTC+0)"}


def title(ident: dict[str, Any]) -> str:
    return f"{ident['contract']} · {ident['source_label']}"


def catalog() -> dict[str, Any]:
    return {"markets": [{"key": key, "label": value["label"]} for key, value in MARKETS.items()],
            "sources": [{"key": key, "label": label} for key, label in SOURCES.items()],
            "timeframes": list(LIVE_TIMEFRAMES),
            "contracts": {market: {source: title(identity(market, source)) for source in SOURCES} for market in MARKETS}}


@dataclass(frozen=True)
class LiveView:
    """One provider's bars and status. ``frame`` columns: timestamp (UTC), open,
    high, low, close, volume."""

    frame: pd.DataFrame
    status: dict[str, Any]
    identity: dict[str, Any]


class LiveProvider(Protocol):
    source: str

    def view(self, now: float) -> LiveView: ...


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({"timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
                         **{column: pd.Series([], dtype=float) for column in ("open", "high", "low", "close", "volume")}})


def _quote(key: str, label: str, value: float | None, title_text: str) -> dict[str, Any]:
    return {"key": key, "label": label, "value": value, "title": title_text}


def _base_status(ident: dict, timeframe: str, status: str, reason: str) -> dict[str, Any]:
    return {"enabled": True, "phase": "streaming", "status": status, "reason": reason,
            "market": ident["market"], "source": ident["source"], "source_label": ident["source_label"],
            "symbol": ident["symbol"], "provider": ident["provider"], "title": title(ident), "timeframe": timeframe,
            "identity": ident, "note": BINANCE_NOTE if ident["source"] == "binance" else None,
            "indicators_include_forming_bar": True, **catalog()}


# ---------------------------------------------------------------------------
# Binance Futures (public WebSocket + REST, owned by binance.hub())
# ---------------------------------------------------------------------------

class BinanceFuturesProvider:
    source = "binance"

    def __init__(self, market: str, timeframe: str, *, session_id: str, hub: binance.BinanceHub | None = None):
        self.market, self.timeframe, self.session_id = market, timeframe, session_id
        self.symbol = provider_symbol(market, "binance")
        self.hub = hub or binance.hub()

    def view(self, now: float) -> LiveView:
        stream = self.hub.kline(self.session_id, self.symbol, self.timeframe)
        board = self.hub.quotes(self.session_id)
        snap = stream.snapshot(now)
        ident = identity(self.market, "binance")
        frame = snap["frame"].drop(columns=["final"])
        spec, mark = snap["spec"], snap["mark"]
        digits = spec.digits if spec else None
        top = board.quote(self.symbol, now) if snap["status"] in ("LIVE", "STALE") else None
        live = snap["status"] == "LIVE"
        spread = round(top.ask - top.bid, digits) if top and digits is not None else None
        status = {
            **_base_status(ident, self.timeframe, snap["status"], snap["reason"]),
            "digits": digits, "tick_size": spec.tick_size if spec else None,
            "last": snap["last_price"] if live or snap["status"] == "STALE" else None,
            "mark": mark.mark if mark and (live or snap["status"] == "STALE") else None,
            "bid": top.bid if top else None, "ask": top.ask if top else None, "spread": spread,
            "spread_points": None, "point": float(spec.tick_size) if spec else None,
            "quotes": [
                _quote("last", "Last", snap["last_price"] if snap["status"] in ("LIVE", "STALE") else None,
                       "Last traded price (close of the forming Binance kline)"),
                _quote("mark", "Mark", mark.mark if mark and snap["status"] in ("LIVE", "STALE") else None,
                       "Binance mark price (markPrice@1s)"),
                _quote("bid", "Bid", top.bid if top else None, "Binance best bid (top of book, 500 ms)"),
                _quote("ask", "Ask", top.ask if top else None, "Binance best ask (top of book, 500 ms)"),
                _quote("spread", "Spread", spread, "Binance best ask − best bid"),
            ],
            "updated_utc": snap["updated_at"],
            "heartbeat_age_s": round(now - snap["updated_at"], 1) if snap["updated_at"] else None,
            "tick_age_s": None, "tick_time_ms": top.event_ms if top else None,
            "forming_bar_time": snap["forming_bar_time"], "bar_count": int(len(frame)),
            "rejected_updates": snap["book"]["out_of_order"] + snap["book"]["malformed"],
            "stream": {**snap["book"], "reconciles": snap["reconciles"], "connections": snap["connections"],
                       "recycles": snap["recycles"], "connection_age_s": snap["connection_age_s"]},
        }
        return LiveView(frame, status, ident)


def binance_watch_quote(board: binance.QuoteBoard, symbol: str, now: float) -> dict[str, Any] | None:
    top = board.quote(symbol, now)
    return None if top is None else {"status": "LIVE", "bid": top.bid, "ask": top.ask, "event_ms": top.event_ms}


# ---------------------------------------------------------------------------
# Exness MT5 (read-only file bridge, see live.py)
# ---------------------------------------------------------------------------

class ExnessMT5Provider:
    source = "exness"

    def __init__(self, market: str, timeframe: str, *, books: dict, folder: Path | None = None):
        self.market, self.timeframe = market, timeframe
        self.symbol = provider_symbol(market, "exness")
        self.books, self.folder = books, folder

    def view(self, now: float) -> LiveView:
        key = (self.symbol, self.timeframe)
        book = self.books.get(key) or mt5.empty_book(self.symbol, self.timeframe)
        feed = mt5.read_feed(self.folder or mt5.common_files_dir(), self.symbol, self.timeframe)
        verdict = None
        if feed.snapshot is not None and feed.error is None:
            book, verdict = mt5.apply_snapshot(book, feed.snapshot, feed.seed)
        self.books[key] = book
        self.last_verdict = verdict
        return exness_view(book, feed, now, self.market)


def exness_view(book: mt5.Book, feed: mt5.FeedRead, now: float, market: str | None = None) -> LiveView:
    """Chart frame and status for one MT5 book (pure; no I/O)."""
    symbol, timeframe = book.symbol, book.timeframe
    market = market or next(key for key, value in MARKETS.items() if value["exness"] == symbol)
    seconds = mt5.LIVE_TIMEFRAMES[timeframe][1]
    snapshot = book.snapshot
    status, reason = mt5.connection_status(file_found=feed.file_found, snapshot=snapshot, error=feed.error,
                                           has_bars=not book.bars.empty, now=now)
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime(book.bars["time"].astype("int64"), unit="s", utc=True),
        "open": book.bars["open"].astype(float), "high": book.bars["high"].astype(float),
        "low": book.bars["low"].astype(float), "close": book.bars["close"].astype(float),
        "volume": book.bars["tick_volume"].astype(float),
    }) if not book.bars.empty else _empty_frame()
    ident = identity(market, "exness")
    current = status in ("LIVE", "STALE")
    # A stopped or broken feed shows no quote and no forming candle (its last bars stay, labelled).
    quote = mt5.quote_payload(snapshot if current else None)
    forming = mt5.forming_bar_time(book.bars, seconds, snapshot.tick_time_ms) if current and snapshot else None
    status_dict = {
        **_base_status(ident, timeframe, status, reason), **quote,
        "quotes": [
            _quote("bid", "Bid", quote["bid"], "Exness MT5 bid"),
            _quote("ask", "Ask", quote["ask"], "Exness MT5 ask"),
            _quote("spread", "Spread", quote["spread"],
                   f"{quote['spread_points']} points (broker)" if quote["spread_points"] is not None else "Broker spread"),
        ],
        "source_detail": "Exness MT5 (read-only file bridge)",
        "updated_utc": snapshot.written_utc if snapshot else None,
        "heartbeat_age_s": round(now - snapshot.written_utc, 1) if snapshot else None,
        "tick_age_s": round(now - snapshot.tick_time_ms / 1000, 1) if snapshot else None,
        "forming_bar_time": forming, "bar_count": int(len(book.bars)), "rejected_updates": book.rejected,
    }
    return LiveView(frame, status_dict, ident)


# ---------------------------------------------------------------------------
# Comparison support (backend only; no analytics yet)
# ---------------------------------------------------------------------------

def comparison_frame(first: LiveView, second: LiveView) -> pd.DataFrame:
    """Align two providers' bars by UTC bar time for a later comparison tool.

    Columns are prefixed with each provider's symbol, and ``attrs["identities"]``
    keeps both identities; nothing is merged or averaged."""
    if first.status["timeframe"] != second.status["timeframe"]:
        raise ValueError("compare bars of the same timeframe only.")
    if first.identity["dataset_key"] == second.identity["dataset_key"]:
        raise ValueError("compare two different providers.")
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    left = first.frame[columns].rename(columns={c: f"{first.identity['symbol']}_{c}" for c in columns[1:]})
    right = second.frame[columns].rename(columns={c: f"{second.identity['symbol']}_{c}" for c in columns[1:]})
    joined = left.merge(right, on="timestamp", how="inner")
    joined.attrs["identities"] = [first.identity, second.identity]
    return joined

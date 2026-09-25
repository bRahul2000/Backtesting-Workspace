"""Load the two feeds for the comparison lab (read-only for all validated data).

Exness: the registered, validated datasets through the TradingView Mode
timeframe resolver. A timeframe without a native file (XAUUSDm 30m) is derived
from M15 by the project's own ``aggregate_ohlcv`` (complete buckets only).

Binance: USDⓈ-M Futures public klines through ``binance.fetch_history``
(paged backwards with endTime), paced, and cached under
``research/feed_comparison/cache`` (git-ignored). Nothing is written into any
dataset folder.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time

import pandas as pd

from services.market_datasets import dataset
from ui.tradingview_mode.component import binance as B
from ui.tradingview_mode.timeframes import load_resolution_data, resolve_timeframe, timeframe_seconds
from utils.data_validation import load_ohlcv_csv

from . import thresholds as TH

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
OUTPUT = HERE / "output"

PAIRS = {
    "XAU": {"label": "Gold", "binance": "XAUUSDT", "binance_label": "XAUUSDT Perpetual (Binance Futures)",
            "exness": "XAUUSDm", "exness_label": "XAUUSDm (Exness MT5)", "exness_m15": "EXNESS_XAUUSDM_M15",
            "binance_digits": 2},
    "BTC": {"label": "BTC", "binance": "BTCUSDT", "binance_label": "BTCUSDT Perpetual (Binance Futures)",
            "exness": "BTCUSDm", "exness_label": "BTCUSDm (Exness MT5)", "exness_m15": "EXNESS_BTCUSDM_M15",
            "binance_digits": 1},
}
TIMEFRAMES = ("15m", "30m", "1h")


@dataclass(frozen=True)
class ExnessFeed:
    frame: pd.DataFrame
    dataset_key: str
    native: bool
    source_label: str


def exness_feed(pair: str, timeframe: str) -> ExnessFeed:
    """The registered Exness data at this timeframe (native file, or derived from M15)."""
    resolution = resolve_timeframe(dataset(PAIRS[pair]["exness_m15"]), timeframe)
    frame = load_resolution_data(resolution, load_ohlcv_csv)
    return ExnessFeed(frame.reset_index(drop=True), resolution.source.key, resolution.native, resolution.source_label)


class PacedRest(B.BinanceRest):
    """Public REST with a pause between kline pages (well under Binance's weight limits)."""

    def __init__(self, pause_s: float = 0.25):
        super().__init__()
        self.pause_s, self.requests = pause_s, 0

    def klines(self, *args, **kwargs):
        if self.requests:
            time.sleep(self.pause_s)
        self.requests += 1
        return super().klines(*args, **kwargs)


def _bars_to_frame(bars: list[B.Bar]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.to_datetime([b.time for b in bars], unit="s", utc=True).astype("datetime64[ns, UTC]"),
        "open": [b.open for b in bars], "high": [b.high for b in bars], "low": [b.low for b in bars],
        "close": [b.close for b in bars], "volume": [b.volume for b in bars],
    })


def binance_feed(pair: str, timeframe: str, start: pd.Timestamp, end: pd.Timestamp, *, refresh: bool = False,
                 rest=None, cache: Path = CACHE) -> tuple[pd.DataFrame, dict]:
    """Completed Binance candles from `start` (or the contract's first candle) to `end`."""
    symbol = PAIRS[pair]["binance"]
    seconds = timeframe_seconds(timeframe)
    cache.mkdir(parents=True, exist_ok=True)
    data_path = cache / f"binance_{symbol}_{timeframe}.csv"
    meta_path = cache / f"binance_{symbol}_{timeframe}.json"
    request = {"symbol": symbol, "interval": timeframe, "start": start.isoformat(), "end": end.isoformat()}
    if not refresh and data_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("request") == request:
            frame = pd.read_csv(data_path)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).astype("datetime64[ns, UTC]")
            return frame, {**meta, "from_cache": True}
    rest = rest or PacedRest()
    server_ms = rest.server_time_ms()
    count = int((end - start).total_seconds() // seconds) + 1
    bars = B.fetch_history(rest, symbol, timeframe, count, server_ms, end_ms=int(end.timestamp() * 1000) + seconds * 1000 - 1)
    bars = [bar for bar in bars if bar.final and start.timestamp() <= bar.time <= end.timestamp()]
    frame = _bars_to_frame(bars)
    meta = {"request": request, "requested_bars": count, "received_bars": len(frame),
            "first": frame["timestamp"].iloc[0].isoformat() if len(frame) else None,
            "last": frame["timestamp"].iloc[-1].isoformat() if len(frame) else None,
            "history_start_reached": len(frame) < count, "rest_requests": getattr(rest, "requests", None),
            "fetched_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
            "endpoint": f"{B.REST_BASE}/fapi/v1/klines (public, paged with endTime)"}
    frame.to_csv(data_path, index=False)
    meta_path.write_text(json.dumps(meta, indent=2))
    return frame, {**meta, "from_cache": False}


def feeds(pair: str, timeframe: str, *, refresh: bool = False) -> tuple[pd.DataFrame, dict, ExnessFeed]:
    exness = exness_feed(pair, timeframe)
    seconds = timeframe_seconds(timeframe)
    first, last = exness.frame["timestamp"].iloc[0], exness.frame["timestamp"].iloc[-1]
    start = first - pd.Timedelta(seconds=TH.WARMUP_BARS * seconds)   # warm-up for Binance indicators
    binance, meta = binance_feed(pair, timeframe, start, last, refresh=refresh)
    return binance, meta, exness

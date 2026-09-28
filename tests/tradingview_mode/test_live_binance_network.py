"""Live: Binance Futures against the REAL public network (skipped when offline).

Proves, for BTCUSDT and XAUUSDT perpetuals, that REST history loads, the
WebSocket connects, the forming candle updates and the last update changes.
"""
import time

import pytest

from ui.tradingview_mode.component import binance as B

try:
    _SERVER_MS = B.BinanceRest(timeout=5).server_time_ms()
except Exception:  # offline / blocked: these tests cannot prove anything here
    _SERVER_MS = None

pytestmark = pytest.mark.skipif(_SERVER_MS is None, reason="Binance Futures public API unreachable")


@pytest.mark.parametrize("symbol, contract_type", [("BTCUSDT", "PERPETUAL"), ("XAUUSDT", "TRADIFI_PERPETUAL")])
def test_real_rest_contract_and_history(symbol, contract_type):
    rest = B.BinanceRest()
    spec = rest.contract(symbol)
    assert (spec.symbol, spec.contract_type, spec.status) == (symbol, contract_type, "TRADING")
    for interval, seconds in B.INTERVALS.items():
        server_ms = rest.server_time_ms()
        bars = B.fetch_history(rest, symbol, interval, B.SEED_BARS, server_ms)  # paged: > 1 request
        assert len(bars) == B.SEED_BARS
        assert all(b.time - a.time == seconds for a, b in zip(bars, bars[1:]))
        assert all(bar.final for bar in bars[:-1]) and not bars[-1].final
        assert bars[-1].time == server_ms // 1000 // seconds * seconds


@pytest.mark.parametrize("symbol", ["BTCUSDT", "XAUUSDT"])
def test_real_websocket_goes_live_and_updates_the_forming_candle(symbol):
    stream = B.KlineStream(symbol, "15m").start()
    board = B.QuoteBoard((symbol,)).start()
    try:
        deadline = time.time() + 30
        # LIVE can precede the first markPrice@1s message by up to a second: wait for both.
        while time.time() < deadline and not ((snap := stream.snapshot(time.time()))["status"] == "LIVE" and snap["mark"]):
            time.sleep(0.25)
        first = stream.snapshot(time.time())
        assert first["status"] == "LIVE", first["reason"]
        assert len(first["frame"]) == B.SEED_BARS and first["forming_bar_time"] is not None
        assert first["mark"] is not None and first["spec"].contract_type == B.CONTRACTS[symbol]["contract_type"]
        start_messages = stream.channel.stats.messages
        time.sleep(5)
        later = stream.snapshot(time.time())
        assert stream.channel.stats.messages > start_messages + 3  # markPrice@1s + kline updates keep arriving
        assert later["updated_at"] > first["updated_at"]            # the last update changes
        assert later["book"]["malformed"] == 0 and later["book"]["out_of_order"] == 0
        top = board.quote(symbol, time.time())
        assert top is not None and 0 < top.bid <= top.ask and top.symbol == symbol
        assert abs(top.bid - later["last_price"]) / top.bid < 0.01  # same market, same moment
    finally:
        stream.stop()
        board.stop()

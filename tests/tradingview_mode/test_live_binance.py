"""Live: Binance Futures provider (deterministic; the real network is in test_live_binance_network.py)."""
import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time

import pandas as pd
import pytest

from ui.tradingview_mode.component import binance as B
from ui.tradingview_mode.component import live as L
from ui.tradingview_mode.component import providers as P
from ui.tradingview_mode.component import terminal as T
from ui.tradingview_mode.component.protocol import PayloadValidationError, parse_event, validate_payload
from ui.tradingview_mode.component.state import IndicatorInstance, TerminalState, apply_event
from ui.tradingview_mode.indicators import calculate_indicator
from ui.tradingview_mode.timeframes import TimeframeResolution

sys.path.insert(0, str(Path(__file__).parent))
from fake_binance import (Clock, FakeConnect, FakeMarket, FakeRest, depth_msg, fake_stream, kline_msg,  # noqa: E402
                          kline_row, mark_msg, wait_for)
from synthetic_mt5_feed import SyntheticFeed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
T0 = 1_790_319_600  # 2026-09-25 07:00 UTC, on the 15m/30m/1h grid
_ids = iter(range(10**9))


def ev(kind, **data):
    return parse_event({"id": f"b-{next(_ids)}", "type": kind, "data": data})


def bar(t, c=100.0, final=False):
    return B.Bar(t, c, c + 1, c - 1, c, 1.0, final)


def upd(t, c=100.0, final=False, event_ms=None, h=None):
    b = B.Bar(t, 100.0, h or max(100.0, c) + 1, min(100.0, c) - 1, c, 2.0, final)
    return B.KlineUpdate(b, event_ms if event_ms is not None else t * 1000 + 1)


# ---- symbol mapping and contracts -------------------------------------------------------------

def _info(symbol="XAUUSDT", contract="TRADIFI_PERPETUAL", status="TRADING", tick="0.01"):
    return {"symbols": [{"symbol": "ETHUSDT", "contractType": "PERPETUAL", "status": "TRADING", "filters": []},
                        {"symbol": symbol, "contractType": contract, "status": status, "underlyingType": "COMMODITY",
                         "filters": [{"filterType": "PRICE_FILTER", "tickSize": tick}]}]}


def test_markets_map_to_the_right_contract_per_source():
    assert P.provider_symbol("BTC", "binance") == "BTCUSDT" and P.provider_symbol("GOLD", "binance") == "XAUUSDT"
    assert P.provider_symbol("BTC", "exness") == "BTCUSDm" and P.provider_symbol("GOLD", "exness") == "XAUUSDm"
    assert B.CONTRACTS["BTCUSDT"]["contract_type"] == "PERPETUAL"
    assert B.CONTRACTS["XAUUSDT"]["contract_type"] == "TRADIFI_PERPETUAL"
    btc, gold = P.identity("BTC", "binance"), P.identity("GOLD", "binance")
    assert (btc["dataset_key"], btc["contract"], btc["provider"]) == ("BINANCE_LIVE:BTCUSDT", "BTCUSDT Perpetual", "Binance Futures")
    assert (gold["dataset_key"], gold["contract"], gold["instrument_kind"]) == (
        "BINANCE_LIVE:XAUUSDT", "XAUUSDT Perpetual", "USDT-margined perpetual futures")
    assert P.market_for_instrument("BTCUSD") == "BTC" and P.market_for_instrument("XAUUSDm") == "GOLD"
    assert P.market_for_instrument("ETHUSD") is None


def test_contract_spec_is_checked_against_exchange_info():
    spec = B.parse_contract(_info(), "XAUUSDT")
    assert (spec.contract_type, spec.tick_size, spec.digits) == ("TRADIFI_PERPETUAL", "0.01", 2)
    assert B.parse_contract(_info("BTCUSDT", "PERPETUAL", tick="0.10"), "BTCUSDT").digits == 1
    for bad, text in ((_info(contract="PERPETUAL"), "expected TRADIFI_PERPETUAL"), (_info(status="SETTLING"), "not TRADING"),
                      ({"symbols": []}, "not listed"), (_info(tick="0"), "tickSize"), ([], "symbol list")):
        with pytest.raises(B.BinanceDataError, match=text):
            B.parse_contract(bad, "XAUUSDT")


# ---- REST seed ----------------------------------------------------------------------------------

def test_rest_seed_rows_become_final_and_forming_bars():
    rows = [kline_row(T0 + i * 900, 100 + i, 106 + i, 95 + i, 101 + i) for i in range(4)]
    server_ms = (T0 + 3 * 900 + 120) * 1000  # two minutes into the 4th bar
    bars = B.parse_rest_klines(rows, "15m", server_ms)
    assert [b.time for b in bars] == [T0, T0 + 900, T0 + 1800, T0 + 2700]
    assert [b.final for b in bars] == [True, True, True, False]
    assert (bars[0].open, bars[0].high, bars[0].low, bars[0].close, bars[0].volume) == (100.0, 106.0, 95.0, 101.0, 1.0)


@pytest.mark.parametrize("mutate, text", [
    (lambda r: r[1].__setitem__(0, r[1][0] + 60_000), "aligned"),
    (lambda r: r[1].__setitem__(6, r[1][6] + 1), "close time"),
    (lambda r: r[1].__setitem__(2, "1.00"), "high/low"),
    (lambda r: r[1].__setitem__(4, "nan"), "finite"),
    (lambda r: r[1].__setitem__(5, "-1"), "volume"),
    (lambda r: r.insert(2, list(r[1])), "strictly increasing"),
    (lambda r: r[1].__setitem__(0, "x"), "integer"),
    (lambda r: r.__setitem__(1, [1, 2]), "malformed"),
])
def test_malformed_rest_history_is_refused(mutate, text):
    rows = [kline_row(T0 + i * 900, 100, 106, 95, 101) for i in range(3)]
    mutate(rows)
    with pytest.raises(B.BinanceDataError, match=text):
        B.parse_rest_klines(rows, "15m", (T0 + 3000) * 1000)


# ---- WebSocket normalization -------------------------------------------------------------------------

def test_kline_event_normalization_and_identity_checks():
    message = kline_msg(T0, 100, 110, 90, 105, final=False, event_ms=T0 * 1000 + 500, v=12.5)
    update = B.parse_kline_event(B.unwrap(message), "BTCUSDT", "15m")
    assert update.bar == B.Bar(T0, 100.0, 110.0, 90.0, 105.0, 12.5, False) and update.event_ms == T0 * 1000 + 500
    data = B.unwrap(message)
    for mutate, text in ((lambda d: d.update(s="ETHUSDT"), "expected BTCUSDT"), (lambda d: d["k"].update(i="1h"), "interval"),
                         (lambda d: d["k"].update(x="false"), "boolean"), (lambda d: d.update(E=T0 * 1000 - 1), "precedes"),
                         (lambda d: d["k"].update(h="1"), "high/low"), (lambda d: d.update(e="aggTrade"), "not a kline")):
        broken = copy.deepcopy(data)
        mutate(broken)
        with pytest.raises(B.BinanceDataError, match=text):
            B.parse_kline_event(broken, "BTCUSDT", "15m")
    top = B.parse_depth_event(B.unwrap(depth_msg(5, 9, 99.5, 100.5)), ("BTCUSDT",))
    assert (top.bid, top.ask, top.update_id) == (99.5, 100.5, 9)
    with pytest.raises(B.BinanceDataError, match="ask below bid"):
        B.parse_depth_event(B.unwrap(depth_msg(5, 9, 101, 100)), ("BTCUSDT",))
    mark = B.parse_mark_event(B.unwrap(mark_msg(7, 80000.0)), "BTCUSDT")
    assert (mark.mark, mark.index, mark.event_ms) == (80000.0, 79995.0, 7)


# ---- kline book: forming, final, duplicate, out-of-order ----------------------------------------------

def seeded_book():
    book = B.KlineBook("BTCUSDT", "15m")
    book.seed([bar(T0, final=True), bar(T0 + 900, final=True), bar(T0 + 1800)], asof_ms=(T0 + 1800) * 1000 + 100)
    return book


def test_forming_candle_updates_in_place():
    book = seeded_book()
    assert book.apply(upd(T0 + 1800, 103.0, event_ms=(T0 + 1800) * 1000 + 200)) == "update"
    assert book.apply(upd(T0 + 1800, 98.0, event_ms=(T0 + 1800) * 1000 + 300)) == "update"
    assert len(book.bars) == 3 and book.bars[-1].close == 98.0 and not book.bars[-1].final
    assert book.finalized == 0


def test_final_candle_rolls_exactly_once():
    book = seeded_book()
    t = T0 + 1800
    assert book.apply(upd(t, 104.0, final=True, event_ms=(t + 900) * 1000 - 1)) == "final"
    assert book.apply(upd(t, 104.0, final=True, event_ms=(t + 900) * 1000)) == "duplicate"   # repeated final
    assert book.apply(upd(t, 107.0, final=True, event_ms=(t + 900) * 1000 + 1)) == "out_of_order"  # never changes again
    assert book.apply(upd(t, 108.0, final=False, event_ms=(t + 900) * 1000 + 2)) == "out_of_order"
    assert book.apply(upd(t + 900, 105.0, event_ms=(t + 900) * 1000 + 10)) == "new"
    assert book.finalized == 1 and [b.time for b in book.bars] == [T0, T0 + 900, t, t + 900]
    assert book.bars[2].close == 104.0 and book.bars[2].final and not book.needs_reconcile


def test_duplicate_and_out_of_order_updates_are_rejected():
    book = seeded_book()
    t = T0 + 1800
    assert book.apply(upd(t, 103.0, event_ms=t * 1000 + 500)) == "update"
    assert book.apply(upd(t, 103.0, event_ms=t * 1000 + 600)) == "duplicate"
    before = list(book.bars)
    assert book.apply(upd(t, 90.0, event_ms=t * 1000 + 400)) == "out_of_order"      # older event time
    assert book.apply(upd(T0 + 900, 90.0, event_ms=t * 1000 + 700)) == "out_of_order"  # finalized bar
    assert book.apply(upd(T0 - 900, 90.0, event_ms=t * 1000 + 800)) == "out_of_order"  # before the window
    assert book.bars == before and (book.out_of_order, book.duplicates) == (3, 1)
    late = B.KlineBook("BTCUSDT", "15m")
    late.seed([bar(T0)], asof_ms=T0 * 1000 + 900)
    assert late.apply(upd(T0, 90.0, event_ms=T0 * 1000 + 800)) == "superseded"  # older than the REST snapshot
    assert late.bars == [bar(T0)] and (late.superseded, late.out_of_order) == (1, 0)


def test_missed_final_or_gap_asks_for_rest_reconciliation_and_finalizes_once():
    book = seeded_book()
    t = T0 + 1800
    assert book.apply(upd(t + 900, 101.0, event_ms=(t + 900) * 1000 + 5)) == "new"  # final of t never arrived
    assert book.needs_reconcile and not book.bars[-2].final
    changed = book.reconcile([bar(t, 104.0, final=True), bar(t + 900, 101.5)], asof_ms=(t + 900) * 1000 + 50)
    assert changed == 2 and book.bars[-2] == bar(t, 104.0, final=True) and book.finalized == 1
    assert not book.needs_reconcile
    assert book.reconcile([bar(t, 104.0, final=True)], asof_ms=(t + 900) * 1000 + 60) == 0 and book.finalized == 1
    assert book.reconcile([bar(t, 99.0, final=False)], asof_ms=(t + 900) * 1000 + 70) == 0  # never un-finalize
    assert book.apply(upd(t + 2700, 102.0, event_ms=(t + 2700) * 1000)) == "new" and book.needs_reconcile  # gap
    times = [b.time for b in book.bars]
    assert times == sorted(set(times))


# ---- streams: seed, live, stale, reconnect, 24 h lifecycle ------------------------------------------

@pytest.fixture
def stream_parts():
    clock = Clock()
    market = FakeMarket(clock)
    rest, connect = FakeRest(market), FakeConnect()
    streams = []

    def make(**kwargs):
        stream = fake_stream(clock=clock, rest=rest, connect=connect, **kwargs).start()
        streams.append(stream)
        return stream

    yield clock, market, rest, connect, make
    for stream in streams:
        stream.stop()


def _forming(stream):
    return stream.book.bars[-1].time


def test_stream_seeds_from_rest_then_goes_live_on_websocket_updates(stream_parts):
    clock, market, rest, connect, make = stream_parts
    stream = make()
    assert wait_for(lambda: len(stream.book.bars) == B.SEED_BARS)
    assert ("klines", "BTCUSDT", "15m", B.SEED_BARS) in rest.calls and ("contract", "BTCUSDT") in rest.calls
    assert connect.current.url == f"{B.MARKET_WS}/stream?streams=btcusdt@kline_15m/btcusdt@markPrice@1s"
    t = _forming(stream)
    connect.current.push(mark_msg(int(clock() * 1000)))
    o, h, l = market.bars[t][:3]
    connect.current.push(kline_msg(t, o, h, l, h + 1.0, final=False, event_ms=int(clock() * 1000)))  # close > high: refused
    connect.current.push(kline_msg(t, o, max(h, 80124.0), min(l, 80122.0), 80123.0, final=False, event_ms=int(clock() * 1000)))
    assert wait_for(lambda: stream.book.bars[-1].close == 80123.0)
    snap = stream.snapshot(clock())
    assert snap["status"] == "LIVE" and snap["last_price"] == 80123.0 and snap["mark"].mark == 80000.0
    assert snap["forming_bar_time"] == t and snap["spec"].digits == 1 and snap["connections"] == 1
    assert snap["book"]["malformed"] == 1  # the inconsistent candle was rejected, not drawn


def test_socket_that_goes_silent_is_stale_then_reconnected(stream_parts):
    clock, market, rest, connect, make = stream_parts
    stream = make()
    assert wait_for(lambda: stream.channel.stats.state == "open" and stream.book.bars)
    connect.current.push(mark_msg(int(clock() * 1000)))
    assert wait_for(lambda: stream.channel.stats.messages == 1)
    clock.jump(B.STALE_S + 1)
    status, reason = stream.status(clock())
    assert status == "STALE" and "socket is open" in reason
    clock.jump(B.SILENCE_RECONNECT_S)
    assert wait_for(lambda: len(connect.sockets) == 2 and stream.channel.stats.state == "open")
    assert stream.channel.stats.silent_reconnects == 1 and connect.sockets[0].closed.is_set()


def test_no_trades_is_stale_even_while_mark_price_keeps_the_socket_alive(stream_parts):
    clock, market, rest, connect, make = stream_parts
    stream = make()
    assert wait_for(lambda: stream.channel.stats.state == "open" and stream.book.bars)
    clock.jump(B.KLINE_STALE_S + 5)
    connect.current.push(mark_msg(int(clock() * 1000)))
    assert wait_for(lambda: stream.channel.stats.messages == 1)
    status, reason = stream.status(clock())
    assert status == "STALE" and "kline update" in reason


def test_server_close_reconnects_with_backoff_and_reconciles_without_duplicates(stream_parts):
    clock, market, rest, connect, make = stream_parts
    stream = make()
    assert wait_for(lambda: stream.book.bars and stream.channel.stats.state == "open")
    t = _forming(stream)
    connect.current.push(kline_msg(t, *market.bars[t][:4], final=False, event_ms=int(clock() * 1000)))
    connect.current.drop()
    clock.jump(3 * 900)  # three candles close while disconnected
    assert wait_for(lambda: len(connect.sockets) == 2 and stream.reconciles == 2)
    times = [b.time for b in stream.book.bars]
    assert times == sorted(set(times)) and all(b - a == 900 for a, b in zip(times, times[1:]))
    assert stream.book.bars[-1].time == int(clock()) // 900 * 900 and not stream.book.bars[-1].final
    assert all(b.final for b in stream.book.bars[:-1])
    assert stream.book.finalized == 3  # t and the two candles opened while offline, each exactly once
    assert connect.sockets[1].url == connect.sockets[0].url  # same subscription reopened


def test_24_hour_connection_lifecycle_recycles_resubscribes_and_keeps_continuity(stream_parts):
    clock, market, rest, connect, make = stream_parts
    stream = make()
    assert wait_for(lambda: stream.book.bars and stream.channel.stats.state == "open")
    t = _forming(stream)
    connect.current.push(kline_msg(t, *market.bars[t][:4], final=False, event_ms=int(clock() * 1000)))
    assert wait_for(lambda: stream.channel.stats.messages == 1)
    before = {b.time: b for b in stream.book.bars if b.final}
    clock.jump(B.MAX_CONNECTION_AGE_S + 1)  # just past the proactive recycle point (< Binance's 24 h cut-off)
    assert wait_for(lambda: len(connect.sockets) == 2 and stream.channel.stats.state == "open" and stream.reconciles == 2)
    stats = stream.channel.stats
    assert stats.recycles == 1 and stats.silent_reconnects == 0 and connect.sockets[0].closed.is_set()
    assert connect.sockets[1].url == connect.sockets[0].url
    times = [b.time for b in stream.book.bars]
    assert times == sorted(set(times)) and all(b - a == 900 for a, b in zip(times, times[1:]))  # no gap, no duplicate
    assert all(stream.book.bars[i] == before[b.time] for i, b in enumerate(stream.book.bars) if b.time in before)
    final_t = next(b for b in stream.book.bars if b.time == t)
    assert final_t.final
    # Binance may re-send the final kline after reconnecting: it must not roll twice.
    finalized = stream.book.finalized
    connect.current.push(kline_msg(t, final_t.open, final_t.high, final_t.low, final_t.close, final=True, v=final_t.volume,
                                   event_ms=int(clock() * 1000)))
    connect.current.push(mark_msg(int(clock() * 1000)))
    assert wait_for(lambda: stream.channel.stats.messages >= 2)
    assert stream.book.finalized == finalized and stream.book.duplicates + stream.book.out_of_order >= 1
    assert stream.status(clock())[0] in ("LIVE", "STALE")


def test_unreachable_network_backs_off_instead_of_busy_looping():
    connect = FakeConnect(fail=True)
    stream = fake_stream(connect=connect, backoff=(0.2, 0.4, 0.8)).start()
    try:
        time.sleep(1.0)
        attempts = len(connect.attempts)
        assert 2 <= attempts <= 4, attempts
        status, reason = stream.status(time.time())
        assert status == "DISCONNECTED" and "Cannot reach Binance Futures" in reason and "Retrying in" in reason
    finally:
        stream.stop()


def test_unlisted_or_wrong_contract_is_an_error_not_a_fallback():
    clock = Clock()
    rest = FakeRest(FakeMarket(clock), contract_error="XAUUSDT is a PERPETUAL contract, expected TRADIFI_PERPETUAL.")
    stream = fake_stream("XAUUSDT", clock=clock, rest=rest).start()
    try:
        assert wait_for(lambda: stream.fatal is not None)
        status, reason = stream.status(clock())
        assert status == "ERROR" and "TRADIFI_PERPETUAL" in reason and not stream.book.bars
    finally:
        stream.stop()


def test_quote_board_orders_updates_and_hides_stale_quotes():
    clock, connect = Clock(), FakeConnect()
    board = B.QuoteBoard(connect=connect, clock=clock, idle_timeout_s=10**9, backoff=(0.05,)).start()
    try:
        assert wait_for(lambda: board.channel.stats.state == "open")
        assert connect.current.url == f"{B.PUBLIC_WS}/stream?streams=btcusdt@depth5@500ms/xauusdt@depth5@500ms"
        connect.current.push(depth_msg(1, 10, 80000.0, 80000.1))
        connect.current.push(depth_msg(2, 9, 1.0, 2.0))                 # out of order
        connect.current.push(depth_msg(3, 10, 1.0, 2.0))                # duplicate id
        connect.current.push(depth_msg(4, 11, 4100.5, 4100.6, "XAUUSDT"))
        assert wait_for(lambda: board.quote("XAUUSDT", clock()) is not None)
        assert (board.quote("BTCUSDT", clock()).bid, board.rejected) == (80000.0, 2)
        clock.jump(B.QUOTE_STALE_S + 1)
        assert board.quote("BTCUSDT", clock()) is None  # never shown as current when old
    finally:
        board.stop()


def test_server_ping_is_answered_with_pong_by_the_real_client():
    from websockets.sync.server import serve

    ponged = threading.Event()

    def handler(connection):
        connection.send(json.dumps(mark_msg(int(time.time() * 1000))))
        waiter = connection.ping(b"binance-ping")
        if waiter.wait(3):
            ponged.set()
        connection.send(json.dumps(mark_msg(int(time.time() * 1000))))
        time.sleep(0.5)

    with serve(handler, "127.0.0.1", 0) as server:
        port = server.socket.getsockname()[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        seen = []
        channel = B.Channel(f"ws://127.0.0.1:{port}/market/stream", on_message=seen.append,
                            should_stop=lambda: len(seen) >= 2 or time.monotonic() > deadline)
        deadline = time.monotonic() + 5
        channel.run()
        server.shutdown()
    assert ponged.is_set() and len(seen) == 2 and seen[0]["e"] == "markPriceUpdate"


# ---- connection ownership -------------------------------------------------------------------------------

@pytest.fixture
def hub():
    clock = Clock()
    made = []

    def kline(symbol, interval):
        made.append((symbol, interval))
        return fake_stream(symbol, interval, clock=clock)

    hub = B.BinanceHub(kline_factory=kline,
                       quotes_factory=lambda: B.QuoteBoard(connect=FakeConnect(), clock=clock, idle_timeout_s=10**9))
    hub.made = made
    yield hub
    hub.shutdown()


def test_reruns_reuse_one_connection_per_stream(hub):
    threads = threading.active_count()
    first = hub.kline("s1", "BTCUSDT", "15m")
    for _ in range(100):  # a hundred Streamlit reruns / polls
        assert hub.kline("s1", "BTCUSDT", "15m") is first
        hub.quotes("s1")
    assert hub.made == [("BTCUSDT", "15m")] and hub.active() == [("kline", "BTCUSDT", "15m"), ("quotes",)]
    assert hub.kline("s2", "BTCUSDT", "15m") is first  # a second tab shares the subscription
    assert threading.active_count() == threads + 2


def test_switching_and_leaving_release_connections_without_leaks(hub):
    threads = threading.active_count()
    btc = hub.kline("s1", "BTCUSDT", "15m")
    hub.quotes("s1")
    gold = hub.kline("s1", "XAUUSDT", "15m")   # switch market: the BTC socket closes
    assert not btc.alive() and gold.alive() and hub.active() == [("kline", "XAUUSDT", "15m"), ("quotes",)]
    hub.kline("s1", "XAUUSDT", "1h")            # switch timeframe
    assert not gold.alive() and hub.active() == [("kline", "XAUUSDT", "1h"), ("quotes",)]
    hub.release("s1", "kline")                  # switch to Exness
    assert hub.active() == [("quotes",)]
    hub.release("s1")                           # exit Live
    assert hub.active() == []
    assert wait_for(lambda: threading.active_count() == threads)


def test_an_abandoned_stream_stops_itself():
    clock = Clock()
    stream = fake_stream(clock=clock, idle_timeout_s=30).start()
    assert wait_for(lambda: stream.channel.stats.state == "open")
    clock.jump(31)  # the browser tab went away: nobody touches the stream
    assert wait_for(lambda: stream.channel.stats.state == "stopped" and not stream.alive())
    hub = B.BinanceHub(kline_factory=lambda s, i: stream)
    assert stream not in [hub._workers.get(k) for k in hub._workers]


def test_terminal_tears_down_the_previous_provider_on_every_switch():
    calls = []

    class Hub:
        def release(self, session_id, kind=None):
            calls.append(kind)

    session = {T.LIVE_BOOKS_KEY: {("BTCUSDm", "15m"): "mt5 book"}}
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    live = lambda market, source, tf="15m": dataclasses.replace(state, live=P.LiveState(market, source, tf, True))
    assert T.sync_live_connections(live("BTC", "exness"), session, hub=Hub()) is None  # first Go Live
    session[T.LIVE_BOOKS_KEY] = {("BTCUSDm", "15m"): "mt5 book"}
    assert T.sync_live_connections(live("BTC", "exness"), session, hub=Hub()) is None  # rerun: nothing happens
    assert T.LIVE_BOOKS_KEY in session and calls == ["kline"]
    log = T.sync_live_connections(live("BTC", "binance"), session, hub=Hub())
    assert T.LIVE_BOOKS_KEY not in session and "Exness MT5 BTCUSDm 15m closed" in log.message
    T.sync_live_connections(live("BTC", "exness"), session, hub=Hub())
    assert calls[-1] == "kline"  # Binance kline socket released when switching to Exness
    T.sync_live_connections(state, session, hub=Hub())
    assert calls[-1] is None and session[T.LIVE_TARGET_KEY] is None  # exit: every lease released


# ---- payload: labels, no mixing, indicators, isolation ----------------------------------------------------

class StubHub:
    """Hands out one pre-fed stream/board (no threads)."""

    def __init__(self, stream, board):
        self.stream, self.board = stream, board

    def kline(self, session_id, symbol, interval):
        assert (symbol, interval) == (self.stream.symbol, self.stream.interval)
        return self.stream

    def quotes(self, session_id):
        return self.board


def fed_stream(symbol="BTCUSDT", interval="15m", price=80000.0):
    """A stream in the state it would be in after seeding + a live update (no socket)."""
    clock = Clock()
    seconds = B.INTERVALS[interval]
    market = FakeMarket(clock, seconds, price=price)
    stream = fake_stream(symbol, interval, clock=clock, rest=FakeRest(market))
    stream.spec = stream.rest.contract(symbol)
    stream._reconcile(full=True)
    now = clock()
    stream.channel.stats.state, stream.channel.stats.opened_at = "open", now
    stream.channel.stats.last_message_at = now
    stream._on_message(B.unwrap(mark_msg(int(now * 1000), price + 3, symbol)))
    t = stream.book.bars[-1].time
    last = stream.book.bars[-1]
    stream._on_message(B.unwrap(kline_msg(t, last.open, last.high + 1, last.low, last.close + 0.5, final=False,
                                          event_ms=int(now * 1000) + 1, symbol=symbol, interval=interval, seconds=seconds)))
    board = B.QuoteBoard(clock=clock)
    board.channel.stats.state = "open"
    board._on_message(B.unwrap(depth_msg(int(now * 1000), 1, price - 0.1, price, symbol)))
    return stream, board, now


def binance_payload(market="BTC", timeframe="15m", indicators=(), folder=None):
    symbol = P.provider_symbol(market, "binance")
    stream, board, now = fed_stream(symbol, timeframe, 4100.0 if market == "GOLD" else 80000.0)
    hub = StubHub(stream, board)
    view = P.BinanceFuturesProvider(market, timeframe, session_id="t", hub=hub).view(now)
    state = TerminalState(dataset_key="BITSTAMP_BTCUSD_15M", timeframe="15m", indicators=tuple(indicators),
                          live=P.LiveState(market, "binance", timeframe, streaming=True))
    selected = T.dataset(state.dataset_key)
    resolution = TimeframeResolution(timeframe, B.INTERVALS[timeframe], selected, True)
    rows = T.live_rows(state, {}, now, hub=hub, folder=folder or Path("/nonexistent/mt5"))
    payload = T.build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=view.frame, bounds=None,
                                       shown=None, logs=[], notices=[], watchlist=T.watchlist_payload(selected, rows),
                                       live_status=view.status)
    return payload, view


@pytest.mark.parametrize("market, title, digits", [("BTC", "BTCUSDT Perpetual · Binance Futures", 1),
                                                   ("GOLD", "XAUUSDT Perpetual · Binance Futures", 2)])
def test_binance_payload_is_labelled_with_its_source(market, title, digits):
    payload, view = binance_payload(market)
    live = payload["live"]
    assert payload["mode"] == "live" and live["status"] == "LIVE" and live["title"] == title
    assert payload["provider"] == "Binance Futures" and payload["dataset_key"].startswith("BINANCE_LIVE:")
    assert payload["symbol"] == P.provider_symbol(market, "binance") and payload["source"]["label"].startswith(title)
    assert live["note"] == "Reference market feed — execution prices may differ from Exness."
    assert [q["label"] for q in live["quotes"]] == ["Last", "Mark", "Bid", "Ask", "Spread"]
    assert all("Binance" in q["title"] for q in live["quotes"]) and "Exness" not in json.dumps(live["quotes"])
    assert payload["price_precision"] == live["digits"] == digits
    assert payload["trade_overlay"]["available"] is False and payload["trade_overlay"]["trades"] == []
    rows = [row for row in payload["watchlist"] if row["kind"] == "live"]
    assert {(r["symbol"], r["source_label"]) for r in rows} == {("BTCUSDT PERP", "BINANCE"), ("XAUUSDT PERP", "BINANCE"),
                                                                ("BTCUSDm", "EXNESS"), ("XAUUSDm", "EXNESS")}
    assert all(r["live"] is None for r in rows if r["source"] == "exness")  # MT5 off: no Exness value
    json.dumps(payload, allow_nan=False)


def test_exness_payload_has_no_binance_note_and_names_its_source(tmp_path):
    folder = tmp_path / "Files"
    SyntheticFeed(folder, "BTCUSDm").write(time.time())
    provider = P.ExnessMT5Provider("BTC", "15m", books={}, folder=folder)
    view = provider.view(time.time())
    assert view.status["title"] == "BTCUSDm · Exness MT5" and view.status["note"] is None
    assert [q["label"] for q in view.status["quotes"]] == ["Bid", "Ask", "Spread"]
    assert all("Exness" in q["title"] or "broker" in q["title"] for q in view.status["quotes"])


def test_both_providers_expose_the_same_react_facing_fields(tmp_path):
    _, binance_view = binance_payload("BTC")
    folder = tmp_path / "Files"
    SyntheticFeed(folder, "BTCUSDm").write(time.time())
    exness_view = P.ExnessMT5Provider("BTC", "15m", books={}, folder=folder).view(time.time())
    common = {"enabled", "phase", "status", "reason", "market", "source", "source_label", "symbol", "provider", "title",
              "timeframe", "identity", "note", "quotes", "digits", "updated_utc", "heartbeat_age_s", "forming_bar_time",
              "bar_count", "rejected_updates", "markets", "sources", "timeframes", "bid", "ask", "spread"}
    assert common <= set(binance_view.status) and common <= set(exness_view.status)
    assert list(binance_view.frame.columns) == list(exness_view.frame.columns) == [
        "timestamp", "open", "high", "low", "close", "volume"]


def test_contract_refuses_mixed_or_mislabelled_live_payloads():
    payload, _ = binance_payload("BTC")
    for mutate, text in (
        (lambda p: p.update(dataset_key="MT5_LIVE:BTCUSDm") or p["source"].update(dataset_key="MT5_LIVE:BTCUSDm"), "labelled provider"),
        (lambda p: p["live"].update(source_label="Exness MT5"), "source label"),
        (lambda p: p["live"].update(title="BTCUSDT Perpetual"), "title must name the source"),
        (lambda p: p.update(provider="Exness Technologies Ltd") or p["source"].update(provider="Exness Technologies Ltd"), "provider mismatch"),
        (lambda p: p["live"]["identity"].update(source="exness"), "identity"),
        (lambda p: p["watchlist"][0].pop("source"), "name its source"),
    ):
        broken = copy.deepcopy(payload)
        mutate(broken)
        with pytest.raises(PayloadValidationError, match=text):
            validate_payload(broken)


def test_switching_provider_never_combines_histories(tmp_path):
    binance_payload_, binance_view = binance_payload("BTC")
    folder = tmp_path / "Files"
    SyntheticFeed(folder, "BTCUSDm").write(time.time())
    exness_view = P.ExnessMT5Provider("BTC", "15m", books={}, folder=folder).view(time.time())
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m", live=P.LiveState("BTC", "exness", "15m", True))
    selected = T.dataset(state.dataset_key)
    exness_payload = T.build_terminal_payload(
        state=state, selected=selected, resolution=TimeframeResolution("15m", 900, selected, True), frame=exness_view.frame,
        bounds=None, shown=None, logs=[], notices=[], watchlist=[], live_status=exness_view.status)
    exness_bars = {bar["time"]: bar for bar in exness_payload["bars"]}
    assert [b["close"] for b in exness_payload["bars"]] == exness_view.frame["close"].tolist()
    assert [b["close"] for b in binance_payload_["bars"]] == binance_view.frame["close"].tolist()
    shared = set(exness_bars) & {bar["time"] for bar in binance_payload_["bars"]}
    assert all(exness_bars[t] != next(b for b in binance_payload_["bars"] if b["time"] == t) for t in shared)
    assert exness_payload["view_key"] != binance_payload_["view_key"]      # the chart reloads, never tail-stitches
    assert exness_payload["bars_rev"] != binance_payload_["bars_rev"]
    assert (exness_payload["live"]["source"], binance_payload_["live"]["source"]) == ("exness", "binance")


def test_indicators_use_the_active_provider_bars_only():
    indicators = (IndicatorInstance("ema-1", "ema", {"length": 20}, True, "#fff"),
                  IndicatorInstance("vwap-2", "vwap", {}, True, "#fff"),
                  IndicatorInstance("bb-3", "bb", {"length": 20, "stddev": 2.0}, True, "#fff"),
                  IndicatorInstance("rsi-4", "rsi", {"length": 14}, True, "#fff"),
                  IndicatorInstance("macd-5", "macd", {"fast": 12, "slow": 26, "signal": 9}, True, "#fff"),
                  IndicatorInstance("atr-6", "atr", {"length": 14}, True, "#fff"),
                  IndicatorInstance("sma-7", "sma", {"length": 50}, True, "#fff"))
    btc, btc_view = binance_payload("BTC", indicators=indicators)
    gold, gold_view = binance_payload("GOLD", indicators=indicators)
    for payload, view in ((btc, btc_view), (gold, gold_view)):
        items = {item["key"]: item for item in payload["overlays"] + payload["panes"]}
        assert set(items) == {item.key for item in indicators}
        for instance in indicators:
            expected = calculate_indicator(view.frame, instance.key, instance.params)
            for series in items[instance.key]["series"]:
                assert series["data"][-1]["time"] == payload["bars"][-1]["time"]  # includes the forming candle
                assert series["data"][-1]["value"] == pytest.approx(float(expected[series["name"]].iloc[-1]), rel=1e-12)
    assert btc["overlays"][0]["series"][0]["data"][-1] != gold["overlays"][0]["series"][0]["data"][-1]


def test_vwap_keeps_the_daily_utc_reset_on_binance_volume():
    _, view = binance_payload("BTC")
    vwap = calculate_indicator(view.frame, "vwap", {})["value"]
    days = view.frame["timestamp"].dt.date
    first_of_day = days != days.shift()
    typical = (view.frame["high"] + view.frame["low"] + view.frame["close"]) / 3
    assert vwap[first_of_day].round(9).tolist() == typical[first_of_day].round(9).tolist()


# ---- MT5 independence, isolation, safety -------------------------------------------------------------------

def test_binance_live_needs_no_mt5_at_all(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("Binance Live touched the MT5 bridge")

    monkeypatch.setattr(L, "read_feed", boom)
    monkeypatch.setattr(L, "parse_seed", boom)
    for market in ("BTC", "GOLD"):
        payload, _ = binance_payload(market, folder=Path("/nonexistent/MetaQuotes/Common/Files"))
        assert payload["live"]["status"] == "LIVE" and payload["bars"]


def test_state_machine_switches_market_and_source_and_keeps_the_timeframe():
    ctx = T.context_for()
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    setup, _ = apply_event(state, ev("enter_live"), ctx)
    live, log = apply_event(setup, ev("go_live", market="BTC", source="binance", timeframe="30m"), ctx)
    assert live.live == P.LiveState("BTC", "binance", "30m", True) and "Binance Futures BTCUSDT 30m" in log.message
    exness, log = apply_event(live, ev("go_live", market="BTC", source="exness", timeframe="30m"), ctx)
    assert exness.live.target == ("exness", "BTCUSDm", "30m") and "switched to Exness MT5" in log.message
    gold, _ = apply_event(exness, ev("go_live", market="GOLD", source="binance", timeframe="30m"), ctx)
    assert gold.live.target == ("binance", "XAUUSDT", "30m")
    same, log = apply_event(gold, ev("go_live", market="GOLD", source="binance", timeframe="30m"), ctx)
    assert same == gold and log.level == "debug"
    back, _ = apply_event(gold, ev("exit_live"), ctx)
    assert back == state


def test_historical_replay_tester_and_ledger_untouched_by_binance_live():
    ledger = ROOT / "experiments" / "experiments.sqlite3"
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    datasets = [T.dataset(k).path for k in ("EXNESS_BTCUSDM_M15", "BITSTAMP_BTCUSD_15M", "EXNESS_XAUUSDM_M15")]
    before = (digest(ledger), [digest(p) for p in datasets])
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    selected, resolution, frame = T._load(state)
    view = frame.iloc[-300:].reset_index(drop=True)
    build = lambda: T.build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=view,
                                             bounds=None, shown=None, logs=[], notices=[], watchlist=[])
    historical = build()
    for market in ("BTC", "GOLD"):
        binance_payload(market)
    assert build() == historical and historical["mode"] == "historical"
    ctx = T.context_for(T._bounds(frame), __import__("ui.tradingview_mode.component.replay", fromlist=["x"]).frame_times(frame))
    live, _ = apply_event(apply_event(state, ev("enter_live"), ctx)[0], ev("go_live", market="BTC", source="binance", timeframe="15m"), ctx)
    for kind, data in (("enter_replay", {"start": "2026-06-10T14:30"}), ("select_dataset", {"dataset_key": "EXNESS_BTCUSDM_H1"})):
        same, log = apply_event(live, ev(kind, **data), ctx)
        assert same == live and log.level == "error"
    replay, _ = apply_event(state, ev("enter_replay", start="2026-06-10T14:30"), ctx)
    assert apply_event(replay, ev("enter_live"), ctx)[0] == replay
    assert (digest(ledger), [digest(p) for p in datasets]) == before


def test_binance_code_is_market_data_only():
    for name in ("binance.py", "providers.py"):
        text = (ROOT / "ui/tradingview_mode/component" / name).read_text()
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for forbidden in ("/fapi/v1/order", "/fapi/v1/batchOrders", "/fapi/v1/leverage", "/fapi/v2/account",
                          "/fapi/v1/listenKey", "listenKey", "X-MBX-APIKEY", "signature", "hmac", "api_secret",
                          "apiKey", "api_key", "positionRisk", "marginType", "userData", "OrderSend", "order_send"):
            assert forbidden not in code, (name, forbidden)
        assert ".post(" not in code and ".put(" not in code and ".delete(" not in code, name
    paths = set(re.findall(r'"(/fapi/[^"]+)"', (ROOT / "ui/tradingview_mode/component/binance.py").read_text()))
    assert paths == {"/fapi/v1/time", "/fapi/v1/exchangeInfo", "/fapi/v1/klines"}

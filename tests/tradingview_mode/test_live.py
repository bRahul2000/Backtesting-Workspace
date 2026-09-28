"""Live: the read-only Exness MT5 provider (synthetic feed; no terminal needed).

Binance Futures provider tests are in test_live_binance.py."""
import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.component import live as L
from ui.tradingview_mode.component import providers as P
from ui.tradingview_mode.component import terminal as T
from ui.tradingview_mode.component.protocol import parse_event, validate_payload
from ui.tradingview_mode.component.state import IndicatorInstance, TerminalState, apply_event
from ui.tradingview_mode.indicators import calculate_indicator
from ui.tradingview_mode.timeframes import TimeframeResolution

sys.path.insert(0, str(Path(__file__).parent))
from synthetic_mt5_feed import SyntheticFeed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SERVICE = ROOT / "ui/tradingview_mode/mt5_bridge/TradingViewLiveFeed.mq5"
NOW = 1_790_277_720.0  # 2026-09-25 04:02:00 UTC, 12 minutes into the 03:50... M15 bar
_ids = iter(range(10**9))


def ev(kind, **data):
    return parse_event({"id": f"l-{next(_ids)}", "type": kind, "data": data})


def feed_book(folder, symbol="BTCUSDm", timeframe="15m", book=None):
    read = L.read_feed(folder, symbol, timeframe)
    book = book or L.empty_book(symbol, timeframe)
    if read.snapshot is not None and read.error is None:
        book, _ = L.apply_snapshot(book, read.snapshot, read.seed)
    return book, read


MARKET = {"BTCUSDm": "BTC", "XAUUSDm": "GOLD"}


def live_payload(folder, symbol="BTCUSDm", timeframe="15m", now=NOW, indicators=(), book=None):
    book, read = feed_book(folder, symbol, timeframe, book)
    view = P.exness_view(book, read, now)
    frame, status = view.frame, view.status
    state = TerminalState(dataset_key=L.LIVE_SYMBOLS[symbol]["dataset_key"], timeframe="15m",
                          indicators=tuple(indicators), live=P.LiveState(MARKET[symbol], "exness", timeframe, streaming=True))
    selected = T.dataset(L.LIVE_SYMBOLS[symbol]["dataset_key"])
    resolution = TimeframeResolution(timeframe, L.LIVE_TIMEFRAMES[timeframe][1], selected, True)
    payload = T.build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=frame, bounds=None,
                                       shown=None, logs=[], notices=[], watchlist=[], live_status=status)
    return payload, book, frame


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "Common" / "Files"


# ---- 1-3. schema and connection states --------------------------------------------------

def test_live_payload_schema(folder):
    SyntheticFeed(folder, "BTCUSDm").write(NOW)
    payload, _, _ = live_payload(folder)
    validate_payload(payload)
    live = payload["live"]
    assert payload["mode"] == "live" and live["enabled"] and live["status"] == "LIVE"
    assert {"bid", "ask", "spread", "spread_points", "digits", "point", "tick_time_ms", "updated_utc", "heartbeat_age_s",
            "tick_age_s", "forming_bar_time", "bar_count", "reason"} <= set(live)
    assert payload["trade_overlay"] == {"available": False, "trades": [], "reason": "Strategy Tester markers are hidden in Live mode."}
    json.dumps(payload, allow_nan=False)


def test_missing_or_stopped_mt5_is_disconnected(folder):
    payload, _, _ = live_payload(folder)
    assert payload["live"]["status"] == "DISCONNECTED" and payload["bars"] == [] and payload["live"]["bid"] is None
    SyntheticFeed(folder, "BTCUSDm").write(NOW - 600)  # service stopped 10 minutes ago
    stopped = live_payload(folder)[0]
    assert stopped["live"]["status"] == "DISCONNECTED"
    # No stale quote or forming candle survives a stopped feed; the last bars stay, labelled DISCONNECTED.
    assert all(q["value"] is None for q in stopped["live"]["quotes"]) and stopped["live"]["bid"] is None
    assert stopped["live"]["forming_bar_time"] is None and stopped["bars"]


@pytest.mark.parametrize("kwargs, status, text", [
    ({"written": NOW - 12}, "STALE", "not updated"),
    ({"tick_time": NOW - 3600}, "STALE", "No ticks"),
    ({"connected": False}, "CONNECTING", "not connected"),
    ({"server_offset": 3 * 3600}, "ERROR", "UTC+0"),
    ({"written": NOW + 60}, "ERROR", "future"),
])
def test_stale_connecting_and_error_states(folder, kwargs, status, text):
    SyntheticFeed(folder, "BTCUSDm").write(NOW, **kwargs)
    live = live_payload(folder)[0]["live"]
    assert live["status"] == status and text in live["reason"]


@pytest.mark.parametrize("mutate, text", [
    (lambda q: q.update(symbol="ETHUSDm"), "expected"),
    (lambda q: q["tick"].update(ask=q["tick"]["bid"] - 1), "ask below bid"),
    (lambda q: q["bars"]["M15"][-1].__setitem__(0, q["bars"]["M15"][-1][0] + 7), "aligned"),
    (lambda q: q["bars"]["M15"].append(list(q["bars"]["M15"][-1])), "duplicates"),
    (lambda q: q["bars"]["M15"][-1].__setitem__(2, 1.0), "high/low"),
    (lambda q: q.update(schema=2), "schema"),
])
def test_bad_feed_data_is_an_error_not_a_price(folder, mutate, text):
    quote = SyntheticFeed(folder, "BTCUSDm").write(NOW)
    mutate(quote)
    (folder / "tv_live_BTCUSDm_quote.json").write_text(json.dumps(quote))
    live = live_payload(folder)[0]["live"]
    assert live["status"] == "ERROR" and text in live["reason"] and live["bid"] is None
    (folder / "tv_live_BTCUSDm_quote.json").write_text("{not json")
    assert live_payload(folder)[0]["live"]["status"] == "ERROR"


# ---- 4, 9-11. quote identity, UTC, provider, precision ---------------------------------------

def test_bid_ask_spread_are_the_broker_values(folder):
    quote = SyntheticFeed(folder, "BTCUSDm").write(NOW, price=80351.2)
    live = live_payload(folder)[0]["live"]
    assert (live["bid"], live["ask"]) == (quote["tick"]["bid"], quote["tick"]["ask"]) == (80351.2, 80369.7)
    assert live["spread"] == 18.5 and live["spread_points"] == quote["spread_points"] == 1850
    assert (live["digits"], live["point"]) == (2, 0.01)


def test_times_are_utc_epoch_seconds_on_the_bar_grid(folder):
    SyntheticFeed(folder, "BTCUSDm").write(NOW)
    payload, _, _ = live_payload(folder)
    assert all(type(bar["time"]) is int and bar["time"] % 900 == 0 for bar in payload["bars"])
    assert payload["live"]["tick_time_ms"] == int(NOW * 1000)
    assert payload["live"]["forming_bar_time"] == payload["bars"][-1]["time"] == int(NOW // 900 * 900)


def test_provider_and_symbol_identity(folder):
    SyntheticFeed(folder, "XAUUSDm").write(NOW)
    payload, _, _ = live_payload(folder, symbol="XAUUSDm")
    assert (payload["symbol"], payload["provider"], payload["instrument"]) == ("XAUUSDm", "Exness Technologies Ltd", "XAUUSDm")
    assert payload["dataset_key"] == payload["source"]["dataset_key"] == "MT5_LIVE:XAUUSDm"
    assert payload["source"]["read_only"] and payload["source"]["provider"] == payload["provider"]
    assert payload["price_precision"] == payload["live"]["digits"] == 3


# ---- 5-8. forming candle, rollover, duplicates, ordering ----------------------------------------

def test_forming_candle_updates_in_place(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW, price=80000.0)
    first, book, _ = live_payload(folder)
    feed.write(NOW + 1, price=80100.0)
    feed.write(NOW + 2, price=79950.0)
    later, book, _ = live_payload(folder, now=NOW + 2, book=book)
    assert len(later["bars"]) == len(first["bars"])
    assert later["bars"][:-1] == first["bars"][:-1]
    last = later["bars"][-1]
    assert (last["open"], last["high"], last["low"], last["close"]) == (80000.0, 80100.0, 79950.0, 79950.0)


def test_rollover_finalizes_the_bar_and_starts_a_new_one_without_duplicates(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW, price=80000.0)
    before, book, _ = live_payload(folder)
    boundary = (NOW // 900 + 1) * 900
    feed.write(boundary + 3, price=80200.0)
    after, book, _ = live_payload(folder, now=boundary + 3, book=book)
    times = [bar["time"] for bar in after["bars"]]
    assert times == sorted(set(times))
    assert after["bars"][-1]["time"] == int(boundary) and after["live"]["forming_bar_time"] == int(boundary)
    assert after["bars"][-2]["time"] == before["bars"][-1]["time"]
    assert after["bars"][-2]["close"] == 80000.0 and after["bars"][-1]["open"] == 80200.0
    assert len(after["bars"]) == L.SEED_BARS  # window keeps its size


def test_duplicate_update_changes_nothing(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW)
    book, read = feed_book(folder)
    again, verdict = L.apply_snapshot(book, read.snapshot, read.seed)
    assert verdict == "duplicate" and again is book


def test_out_of_order_update_is_rejected_and_a_restarted_service_is_accepted(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW, seq=10)
    book, _ = feed_book(folder)
    feed.write(NOW + 1, seq=9, price=1.0)
    older, _ = feed_book(folder, book=book)
    assert older.rejected == 1 and older.last_seq == 10 and older.bars.equals(book.bars)
    feed.write(NOW - 5, seq=11)  # tick time going backwards
    assert feed_book(folder, book=book)[0].rejected == 1
    restarted = SyntheticFeed(folder, "BTCUSDm", writer_id="synthetic-2")
    restarted.write(NOW + 2, seq=1)
    fresh, _ = feed_book(folder, book=book)
    assert fresh.writer_id == "synthetic-2" and fresh.last_seq == 1 and fresh.rejected == 0


# ---- 12-13. timeframes ---------------------------------------------------------------------------

def test_native_timeframes_use_their_own_mt5_period(folder):
    SyntheticFeed(folder, "BTCUSDm").write(NOW)
    for timeframe, seconds in (("15m", 900), ("30m", 1800), ("1h", 3600)):
        payload, _, _ = live_payload(folder, timeframe=timeframe)
        assert payload["timeframe"] == timeframe and payload["timeframes"] == ["15m", "30m", "1h"]
        assert all(bar["time"] % seconds == 0 for bar in payload["bars"])
        assert payload["bars"][-1]["time"] == int(NOW // seconds * seconds)


def _live(state, ctx=None, market="BTC", source="exness", timeframe="15m"):
    ctx = ctx or T.context_for()
    setup, _ = apply_event(state, ev("enter_live"), ctx)
    return apply_event(setup, ev("go_live", market=market, source=source, timeframe=timeframe), ctx)


def test_no_derived_or_unsupported_live_timeframe():
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    setup, _ = apply_event(state, ev("enter_live"), T.context_for())
    for timeframe in ("4h", "1d", "5m"):
        for source in ("exness", "binance"):
            same, log = apply_event(setup, ev("go_live", market="BTC", source=source, timeframe=timeframe), T.context_for())
            assert same == setup and log.level == "error"
    live, _ = _live(state)
    rejected, log = apply_event(live, ev("select_timeframe", timeframe="4h"), T.context_for())
    assert rejected == live and "not a live timeframe" in log.message
    switched, _ = apply_event(live, ev("select_timeframe", timeframe="1h"), T.context_for())
    assert switched.live.timeframe == "1h" and switched.timeframe == "15m"  # historical selection untouched
    for market, source in (("BTC/USD", "exness"), ("ETH", "binance"), ("BTC", "bitstamp"), ("BTC", "Binance Futures")):
        rejected, log = apply_event(setup, ev("go_live", market=market, source=source, timeframe="15m"), T.context_for())
        assert rejected == setup and log.level == "error"


# ---- mode entry is separate from Go Live (the Live-button bug) ---------------------------------

def test_entering_live_needs_no_feed_and_preselects_the_market_with_binance_default():
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    setup, log = apply_event(state, ev("enter_live"), T.context_for())
    assert setup.live == P.LiveState("BTC", "binance", "15m", streaming=False) and log.level == "info"
    xau, _ = apply_event(TerminalState(dataset_key="EXNESS_XAUUSDM_H1", timeframe="1h"), ev("enter_live"), T.context_for())
    assert xau.live == P.LiveState("GOLD", "binance", "1h", streaming=False)


def test_entering_live_from_bitstamp_is_explicit_not_a_silent_noop():
    state = TerminalState(dataset_key="BITSTAMP_BTCUSD_15M", timeframe="4h")
    setup, log = apply_event(state, ev("enter_live"), T.context_for())
    assert setup.live == P.LiveState("BTC", "binance", "15m", streaming=False)
    assert setup.dataset_key == "BITSTAMP_BTCUSD_15M" and setup.timeframe == "4h"  # nothing changed behind the user's back
    status = T.live_setup_status(setup.live, T.dataset("BITSTAMP_BTCUSD_15M"))
    assert status["phase"] == "setup" and status["current_supported"] is True
    assert status["message"].startswith("BTC/USD (Bitstamp) has no live feed.") and "different instrument" in status["message"]
    assert [m["key"] for m in status["markets"]] == ["BTC", "GOLD"] and status["timeframes"] == ["15m", "30m", "1h"]
    assert [s["label"] for s in status["sources"]] == ["Binance Futures", "Exness MT5"]
    unknown, log = apply_event(state, ev("enter_live"), dataclasses.replace(T.context_for(), dataset_instrument=lambda key: "ETHUSD"))
    assert unknown.live.market is None and P.UNSUPPORTED_MESSAGE in log.message


def test_setup_phase_payload_reads_nothing_from_mt5(folder, monkeypatch):
    calls = []
    monkeypatch.setattr(L, "read_feed", lambda *a, **k: calls.append(a) or None)
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m", live=P.LiveState("BTC", "exness", "15m"))
    selected, resolution, frame = T._load(state)
    payload = T.build_terminal_payload(state=state, selected=selected, resolution=resolution,
                                       frame=frame.iloc[-200:].reset_index(drop=True), bounds=None, shown=None,
                                       logs=[], notices=[], watchlist=[],
                                       live_status=T.live_setup_status(state.live, selected))
    assert payload["mode"] == "live" and payload["live"]["phase"] == "setup" and not calls
    assert payload["dataset_key"] == "EXNESS_BTCUSDM_M15" and not payload["view_key"].endswith("|live")
    assert payload["trade_overlay"]["available"] is False


def test_go_live_requires_live_mode_and_replay_blocks_it():
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    same, log = apply_event(state, ev("go_live", market="BTC", source="exness", timeframe="15m"), T.context_for())
    assert same == state and "enter Live mode" in log.message
    setup, _ = apply_event(state, ev("enter_live"), T.context_for())
    blocked, log = apply_event(setup, ev("select_timeframe", timeframe="1h"), T.context_for())
    assert blocked == setup and "Live bar" in log.message


# ---- 14, 17. nothing written ---------------------------------------------------------------------

def test_reading_never_writes_or_mutates(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW)
    before = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in folder.iterdir()}
    book, read = feed_book(folder)
    seed_copy = read.seed.copy(deep=True)
    snapshot_bars = copy.deepcopy(read.snapshot.bars)
    L.apply_snapshot(book, read.snapshot, read.seed)
    live_payload(folder, book=book)
    pd.testing.assert_frame_equal(read.seed, seed_copy)
    for period, frame in snapshot_bars.items():
        pd.testing.assert_frame_equal(read.snapshot.bars[period], frame)
    after = {path.name: (path.stat().st_mtime_ns, path.read_bytes()) for path in folder.iterdir()}
    assert after == before


def test_research_ledger_and_datasets_unchanged(folder):
    ledger = ROOT / "experiments" / "experiments.sqlite3"
    dataset_file = T.dataset("EXNESS_BTCUSDM_M15").path
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
    before = (digest(ledger), digest(dataset_file))
    feed = SyntheticFeed(folder, "BTCUSDm")
    for step in range(5):
        feed.write(NOW + step)
        live_payload(folder, now=NOW + step)
    assert (digest(ledger), digest(dataset_file)) == before


# ---- 18. zero trade execution --------------------------------------------------------------------

def test_the_mt5_service_and_python_live_code_cannot_trade():
    source = SERVICE.read_text()
    code = re.sub(r"//.*", "", source)  # comments may say what it does NOT do
    for forbidden in ("OrderSend", "OrderSendAsync", "OrderCheck", "OrderModify", "OrderDelete", "CTrade",
                      "Trade.mqh", "PositionOpen", "PositionClose", "PositionModify", "TRADE_ACTION", "MqlTradeRequest",
                      "ExpertRemove", "#property script"):
        assert forbidden not in code, forbidden
    assert "#property service" in source
    for path in (ROOT / "ui/tradingview_mode/component/live.py", ROOT / "ui/tradingview_mode/component/terminal.py",
                 ROOT / "ui/tradingview_mode/component/providers.py"):
        text = path.read_text()
        for forbidden in ("OrderSend", "order_send", "MetaTrader5", "positions_get", "TRADE_ACTION"):
            assert forbidden not in text, (path.name, forbidden)
    live_source = (ROOT / "ui/tradingview_mode/component/live.py").read_text()
    assert "write_text" not in live_source and ".open(" not in live_source and "os.replace" not in live_source


# ---- 19. indicators ---------------------------------------------------------------------------------

def test_live_indicators_are_calculated_in_python_including_the_forming_bar(folder):
    feed = SyntheticFeed(folder, "BTCUSDm")
    feed.write(NOW, price=80400.0)
    indicators = (IndicatorInstance("ema-1", "ema", {"length": 20}, True, "#fff"),
                  IndicatorInstance("vwap-2", "vwap", {}, True, "#fff"),
                  IndicatorInstance("rsi-3", "rsi", {"length": 14}, True, "#fff"),
                  IndicatorInstance("macd-4", "macd", {"fast": 12, "slow": 26, "signal": 9}, True, "#fff"))
    payload, _, frame = live_payload(folder, indicators=indicators)
    assert payload["live"]["indicators_include_forming_bar"] is True
    items = {item["key"]: item for item in payload["overlays"] + payload["panes"]}
    for key, params in (("ema", {"length": 20}), ("vwap", {}), ("rsi", {"length": 14}),
                        ("macd", {"fast": 12, "slow": 26, "signal": 9})):
        expected = calculate_indicator(frame, key, params)
        for series in items[key]["series"]:
            assert series["data"][-1]["time"] == payload["bars"][-1]["time"]  # includes the forming bar
            assert series["data"][-1]["value"] == pytest.approx(float(expected[series["name"]].iloc[-1]), abs=1e-9)


# ---- 15-16, 20. mode isolation ------------------------------------------------------------------------

def test_live_replay_and_historical_are_isolated():
    ctx_state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m", bottom_panel="trades")
    selected, resolution, frame = T._load(ctx_state)
    ctx = T.context_for(T._bounds(frame), __import__("ui.tradingview_mode.component.replay", fromlist=["x"]).frame_times(frame))
    live, _ = _live(ctx_state, ctx, timeframe="30m")
    assert live.replay is None and live.live == P.LiveState("BTC", "exness", "30m", streaming=True)
    for kind, data in (("enter_replay", {"start": "2026-06-10T14:30"}), ("step_forward", {}),
                       ("select_dataset", {"dataset_key": "EXNESS_BTCUSDM_H1"}),
                       ("set_date_range", {"start": "2026-01-01", "end": "2026-01-02"})):
        same, log = apply_event(live, ev(kind, **data), ctx)
        assert same == live and log.level == "error"
    back, _ = apply_event(live, ev("exit_live"), ctx)
    assert back == ctx_state  # historical selection, panel and indicators exactly as before
    replay, _ = apply_event(ctx_state, ev("enter_replay", start="2026-06-10T14:30"), ctx)
    blocked, log = apply_event(replay, ev("enter_live"), ctx)
    assert blocked == replay and "exit Replay" in log.message
    polled, entry = apply_event(live, ev("live_poll"), ctx)
    assert polled == live and entry is None


def test_historical_payload_is_unchanged_by_live_mode(folder):
    SyntheticFeed(folder, "BTCUSDm").write(NOW)
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    selected, resolution, frame = T._load(state)
    view = frame.iloc[-300:].reset_index(drop=True)
    build = lambda: T.build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=view,
                                             bounds=None, shown=None, logs=[], notices=[], watchlist=[])
    before = build()
    live_payload(folder)
    after = build()
    assert before == after and after["live"] == {"enabled": False} and after["mode"] == "historical"


def test_watchlist_shows_live_values_only_for_live_symbols(folder):
    SyntheticFeed(folder, "BTCUSDm").write(NOW)
    quotes = T.live_quotes(folder, NOW)
    assert set(quotes) == {"BTCUSDm"}  # XAUUSDm has no feed file: nothing is faked
    live = P.LiveState("BTC", "exness", "15m", streaming=True)
    rows = T.watchlist_payload(T.dataset("EXNESS_BTCUSDM_M15"), T.live_watchlist(live, {}, quotes))
    live_rows = {(row["source"], row["symbol"]): row for row in rows if row["kind"] == "live"}
    assert live_rows[("exness", "BTCUSDm")]["live"]["bid"] == 80350.0
    assert live_rows[("exness", "BTCUSDm")]["live"]["status"] == "LIVE" and live_rows[("exness", "BTCUSDm")]["source_label"] == "EXNESS"
    assert live_rows[("exness", "XAUUSDm")]["live"] is None
    assert live_rows[("binance", "BTCUSDT PERP")]["live"] is None  # no Binance quote: no value, never the MT5 one
    assert all(row["live"] is None for row in rows if row["kind"] == "dataset")  # registry rows stay historical
    assert T.live_quotes(folder, NOW + 600) == {}  # a stopped feed is not shown as a live value

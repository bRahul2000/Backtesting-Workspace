"""Chart / Signal / Execution source roles and the signal-authority fail-safe (read-only)."""
import copy
import dataclasses
import json
from pathlib import Path
import re
import sys

import pytest

from ui.tradingview_mode.component import providers as P
from ui.tradingview_mode.component import source_roles as R
from ui.tradingview_mode.component import terminal as T
from ui.tradingview_mode.component.protocol import PayloadValidationError, validate_payload
from ui.tradingview_mode.component.state import TerminalState

sys.path.insert(0, str(Path(__file__).parent))
from synthetic_mt5_feed import SyntheticFeed  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_790_320_000.0


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "Common" / "Files"


def chart_status(source="binance", market="GOLD", state="LIVE", timeframe="15m"):
    ident = P.identity(market, source)
    return {"source": source, "source_label": ident["source_label"], "symbol": ident["symbol"], "status": state,
            "updated_utc": NOW, "reason": "", "timeframe": timeframe}


def live_state(market="GOLD", source="binance", timeframe="15m"):
    return TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m",
                         live=P.LiveState(market, source, timeframe, streaming=True))


def roles(session, folder, now, *, market="GOLD", source="binance", chart_state="LIVE"):
    return T.update_source_roles(live_state(market, source), chart_status(source, market, chart_state), session, now,
                                 folder=folder)


def observe(folder, now, market="GOLD", timeframe="15m"):
    return R.observe_exness(market, timeframe, now, folder)


def feed_live(folder, symbol="XAUUSDm", start=NOW, updates=2):
    feed = SyntheticFeed(folder, symbol)
    for i in range(updates):
        feed.write(start + i)
    return feed


def establish(folder, tracker=None):
    """The feed writes and the app observes twice (two fresh, advancing updates)."""
    feed = SyntheticFeed(folder, "XAUUSDm")
    tracker = tracker or R.AuthorityTracker()
    for i in range(R.REQUIRED_FRESH_UPDATES):
        feed.write(NOW + i)
        tracker, assessment, _ = R.advance(tracker, observe(folder, NOW + i))
    assert assessment.ready
    return feed, tracker


def established_session(folder, source="binance"):
    feed = SyntheticFeed(folder, "XAUUSDm")
    session = {}
    for i in range(R.REQUIRED_FRESH_UPDATES):
        feed.write(NOW + i)
        s = roles(session, folder, NOW + i, source=source)
    assert s["signal_authority_ready"] is True
    return feed, session, s


# ---- role model and separation ----------------------------------------------------------------------

def test_signal_source_is_exness_for_each_market_whatever_the_chart_shows(folder):
    assert (R.signal_symbol("GOLD"), R.signal_symbol("BTC")) == ("XAUUSDm", "BTCUSDm")
    feed_live(folder)
    session = {}
    for source in ("binance", "exness", "binance"):
        s = roles(session, folder, NOW + 1, source=source)
        assert s["chart"]["provider"] == P.SOURCES[source] and s["chart"]["is_authoritative"] is False
        assert (s["signal"]["provider"], s["signal"]["symbol"], s["signal"]["is_authoritative"]) == ("Exness MT5", "XAUUSDm", True)
        assert (s["execution"]["provider"], s["execution"]["state"]) == ("Exness MT5", "DISABLED")
    assert s["chart"]["symbol"] == "XAUUSDT"


def test_switching_chart_source_does_not_touch_signal_authority(folder):
    feed, session, _ = established_session(folder)
    for i, source in enumerate(("exness", "binance", "exness")):
        feed.write(NOW + 2 + i)
        s = roles(session, folder, NOW + 2 + i, source=source)
        assert s["signal_authority_ready"] is True and s["signal"]["symbol"] == "XAUUSDm"
    assert any("Chart source: Exness MT5 · XAUUSDm" in e["message"] for e in s["log"])
    assert not any("Signal authority disabled" in e["message"] for e in s["log"])


def test_mismatch_note_only_when_chart_and_signal_markets_differ(folder):
    feed_live(folder)
    session = {}
    assert roles(session, folder, NOW + 1, source="binance")["note"] == R.MISMATCH_NOTE
    assert roles(session, folder, NOW + 1, source="exness")["note"] is None


# ---- Binance can never be authoritative ------------------------------------------------------------------

def test_binance_can_never_satisfy_signal_authority(folder):
    feed_live(folder)
    real = observe(folder, NOW + 1)
    fake = dataclasses.replace(real, provider_source="binance", symbol="XAUUSDm")  # otherwise perfect
    tracker = R.AuthorityTracker()
    for i in range(10):
        tracker, assessment, _ = R.advance(tracker, dataclasses.replace(fake, seq=100 + i))
        assert assessment.ready is False and "only Exness MT5 is authoritative" in assessment.reason
    # There is no parameter that can point the signal source at Binance.
    assert "provider" not in R.observe_exness.__code__.co_varnames[:R.observe_exness.__code__.co_argcount]


def test_binance_live_with_exness_offline_never_enables_signals(folder):
    session = {}
    for i in range(5):
        s = roles(session, folder, NOW + i, source="binance", chart_state="LIVE")  # no MT5 files at all
        assert s["chart"]["state"] == "LIVE" and s["signal_authority_ready"] is False
        assert s["signal"]["state"] == "UNAVAILABLE" and s["signal"]["feed_state"] == "DISCONNECTED"
    assert s["signal"]["reason"].startswith("Exness signal feed unavailable. Binance chart remains live, "
                                            "but Exness strategy signals are disabled.")
    assert s["execution"]["reason"] == "Exness signal source unavailable" and s["readiness"]["enabled"] is False


def test_contract_rejects_a_binance_or_mislabelled_signal_source(folder):
    sys.path.insert(0, str(Path(__file__).parent))
    from test_live_binance import binance_payload
    payload, _ = binance_payload("GOLD")
    _, _, payload["sources"] = established_session(folder)
    validate_payload(payload)
    for mutate, text in (
        (lambda p: p["sources"]["signal"].update(provider="Binance Futures", source="binance"), "must be Exness MT5"),
        (lambda p: p["sources"]["chart"].update(is_authoritative=True), "never authoritative"),
        (lambda p: p["sources"]["readiness"].update(enabled=True), "disabled"),
        (lambda p: p["sources"]["execution"].update(state="READY"), "disabled"),
        (lambda p: p["sources"]["signal"].update(feed_state="STALE"), "LIVE Exness"),
        (lambda p: p["sources"]["chart"].update(source="exness"), "chart being drawn"),
    ):
        broken = copy.deepcopy(payload)
        mutate(broken)
        with pytest.raises(PayloadValidationError, match=text):
            validate_payload(broken)
    from ui.tradingview_mode.component.protocol import _validate_sources
    for mode, live, replay in (("replay", {"enabled": False}, {"enabled": True}), ("historical", {"enabled": False}, {"enabled": False})):
        with pytest.raises(PayloadValidationError, match="never in Replay or Historical"):
            _validate_sources({**payload, "mode": mode, "live": live, "replay": replay})


# ---- authority: establish, fail-safe, recovery --------------------------------------------------------

def test_exness_live_needs_fresh_consecutive_updates_before_authority(folder):
    feed = SyntheticFeed(folder, "XAUUSDm")
    tracker = R.AuthorityTracker()
    feed.write(NOW)
    tracker, a, events = R.advance(tracker, observe(folder, NOW))
    assert not a.ready and "Revalidating" in a.reason and "Exness signal source LIVE" in events
    tracker, a, _ = R.advance(tracker, observe(folder, NOW + 0.3))          # same file again: no new update
    assert not a.ready and a.confirmations == 1
    feed.write(NOW + 1)
    tracker, a, events = R.advance(tracker, observe(folder, NOW + 1))
    assert a.ready and "Signal authority established" in events


@pytest.mark.parametrize("breaker, feed_state", [
    (lambda feed, folder: None, "STALE"),                                                      # service stops writing
    (lambda feed, folder: [p.unlink() for p in folder.glob("tv_live_XAUUSDm_quote.json")], "DISCONNECTED"),
    (lambda feed, folder: (folder / "tv_live_XAUUSDm_quote.json").write_text("{broken"), "ERROR"),
])
def test_any_non_live_state_disables_authority_immediately(folder, breaker, feed_state):
    feed, tracker = establish(folder)
    breaker(feed, folder)
    later = NOW + 1 + R.mt5.HEARTBEAT_STALE_S + 1 if feed_state == "STALE" else NOW + 1.5
    tracker, a, events = R.advance(tracker, observe(folder, later))
    assert not a.ready and tracker.feed_state == feed_state
    assert f"Exness signal source {feed_state}" in events and any(e.startswith("Signal authority disabled") for e in events)
    readiness = R.execution_readiness(observe(folder, later), a)
    assert readiness.enabled is False and readiness.reason == "Exness signal source unavailable"


def test_recovery_revalidates_instead_of_trusting_the_first_new_file(folder):
    feed, tracker = establish(folder)
    tracker, a, _ = R.advance(tracker, observe(folder, NOW + 30))           # stale
    assert not a.ready
    restarted = SyntheticFeed(folder, "XAUUSDm")                            # service restarted: seq back to 1
    restarted.write(NOW + 31)
    tracker, a, events = R.advance(tracker, observe(folder, NOW + 31))
    assert not a.ready and "Revalidating Exness feed (1/2" in a.reason       # one file is not enough
    restarted.write(NOW + 32)
    tracker, a, events = R.advance(tracker, observe(folder, NOW + 32))
    assert a.ready and "Signal authority restored" in events


def test_symbol_mismatch_missing_timeframe_and_stale_bars_disable_authority(folder):
    feed_live(folder)
    good = observe(folder, NOW + 1)
    checks = {name: ok for name, ok, _ in R.authority_checks(good)}
    assert all(checks.values())
    wrong_symbol = dataclasses.replace(good, symbol="XAUUSD")
    assert {n: ok for n, ok, _ in R.authority_checks(wrong_symbol)}["symbol"] is False
    short = dataclasses.replace(good, bar_times=good.bar_times[-50:])
    assert {n: ok for n, ok, _ in R.authority_checks(short)}["timeframe_data"] is False
    old_bars = dataclasses.replace(good, bar_times=tuple(t - 3 * 900 for t in good.bar_times))
    assert {n: ok for n, ok, _ in R.authority_checks(old_bars)}["timestamps"] is False
    stale_quote = dataclasses.replace(good, tick_time_ms=int((NOW - 120) * 1000))
    assert {n: ok for n, ok, _ in R.authority_checks(stale_quote)}["fresh_quote"] is False
    for bad in (wrong_symbol, short, old_bars, stale_quote):
        tracker = R.AuthorityTracker()
        for i in range(4):
            tracker, a, _ = R.advance(tracker, dataclasses.replace(bad, seq=10 + i))
        assert not a.ready
    # A missing seed file for the timeframe: only the last 3 quote bars remain.
    (folder / "tv_live_XAUUSDm_M15_seed.csv").unlink()
    assert {n: ok for n, ok, _ in R.authority_checks(observe(folder, NOW + 1))}["timeframe_data"] is False


def test_changing_market_or_timeframe_starts_validation_over(folder):
    _, tracker = establish(folder)
    tracker, a, events = R.advance(tracker, observe(folder, NOW + 1, timeframe="1h"))
    assert not a.ready and "Signal source: Exness MT5 · XAUUSDm · 1h" in events


# ---- execution, log, isolation, safety ---------------------------------------------------------------

def test_execution_is_disabled_in_every_case(folder):
    session = {}
    seen = []
    feed = SyntheticFeed(folder, "XAUUSDm")
    for step in range(8):
        if step < 4:
            feed.write(NOW + step)
        s = roles(session, folder, NOW + step + (0 if step < 4 else 20), source=("binance", "exness")[step % 2])
        seen.append((s["signal_authority_ready"], s["readiness"]["enabled"], s["execution"]["state"], s["execution"]["reason"]))
    assert {ready for ready, *_ in seen} == {True, False}
    assert all(enabled is False and state == "DISABLED" for _, enabled, state, _ in seen)
    assert {reason for *_, reason in seen} == {"Live execution not enabled", "Exness signal source unavailable"}


def test_source_log_records_transitions_and_keeps_the_last_fifty(folder):
    feed, session, _ = established_session(folder)
    roles(session, folder, NOW + 20)             # stale
    feed.write(NOW + 21)
    roles(session, folder, NOW + 21)
    feed.write(NOW + 22)
    log = roles(session, folder, NOW + 22)["log"]
    messages = [e["message"] for e in log]
    order = ["Exness signal source LIVE", "Signal authority established", "Exness signal source STALE",
             "Signal authority disabled", "Execution DISABLED: Exness signal source unavailable", "Signal authority restored"]
    position = -1
    for expected in order:  # each transition appears, in this order
        position = next(i for i, m in enumerate(messages) if i > position and m.startswith(expected))
    assert re.fullmatch(r"\d\d:\d\d:\d\d", log[0]["time"])
    T.release_source_roles(session, NOW + 23)
    assert session[T.SOURCE_LOG_KEY][-1]["message"].startswith("Live ended") and T.AUTHORITY_KEY not in session
    assert len(R.append_log([], [f"e{i}" for i in range(80)], NOW)) == R.LOG_LIMIT


def test_historical_replay_and_strategy_tester_do_not_carry_source_roles():
    state = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m")
    selected, resolution, frame = T._load(state)
    payload = T.build_terminal_payload(state=state, selected=selected, resolution=resolution,
                                       frame=frame.iloc[-300:].reset_index(drop=True), bounds=None, shown=None,
                                       logs=[], notices=[], watchlist=[])
    assert payload["sources"] is None and payload["mode"] == "historical"
    tester = (ROOT / "ui/tradingview_mode/component/tester.py").read_text()
    assert "source_roles" not in tester and "signal_authority" not in tester


def test_source_roles_code_cannot_trade():
    text = (ROOT / "ui/tradingview_mode/component/source_roles.py").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("OrderSend", "order_send", "MetaTrader5", "positions_get", "TRADE_ACTION", "CTrade", "/fapi/v1/order",
                      "write_text", "os.replace", ".open(", "requests", "subprocess"):
        assert forbidden not in code, forbidden
    assert re.search(r"enabled=False", code) and "enabled=True" not in code

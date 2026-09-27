"""P2.1 real-terminal validation scripts: they compile, and their documented expectations hold when run
through the terminal bridge (a dry run of the manual checklist, not a replacement for it)."""
from pathlib import Path

import pandas as pd
import pytest

from tests.tradingview_mode.test_pine_terminal import ev, payload_for
from ui.tradingview_mode.component import pine_bridge as PB
from ui.tradingview_mode.component import replay as replay_model
from ui.tradingview_mode.component import security_data as SD
from ui.tradingview_mode.component import terminal as T
from ui.tradingview_mode.component.state import TerminalState, apply_event
from ui.tradingview_mode.pine import compile_script

MANUAL = Path("ui/tradingview_mode/pine/parity/manual")
CHECKLIST = Path("ui/tradingview_mode/pine/parity/MANUAL_CHECKLIST.md")
SCRIPTS = sorted(MANUAL.glob("p21_terminal_*.pine"))


def added(dataset_key, timeframe, name):
    state, session = TerminalState(dataset_key=dataset_key, timeframe=timeframe), {}
    state, log = PB.handle_pine_event(ev("pine_add", source=(MANUAL / name).read_text()), state, session)
    assert log.level == "info", log.message
    return state, session


def test_every_script_compiles_with_supported_features_only_and_is_in_the_checklist():
    checklist = CHECKLIST.read_text()
    assert len(SCRIPTS) == 7
    for path in SCRIPTS:
        result = compile_script(path.read_text())
        assert result.ok and not result.diagnostics, (path.name, [d.text() for d in result.diagnostics])
        assert f"`manual/{path.name}`" in checklist


def test_exness_provenance_native_h1_and_aggregated_h4():
    state, session = added("EXNESS_XAUUSDM_M15", "15m", "p21_terminal_exness_history.pine")
    payload, notices = payload_for(state, session)
    script = payload["pine"]["scripts"][0]
    assert not notices and script["error"] is None
    h1, h4 = script["contexts"]
    assert (h1["timeframe"], h1["native"], h1["provider"]) == ("60", True, "Exness MT5")
    assert h1["data_identity"].startswith("EXNESS_XAUUSDM_H1")
    assert (h4["timeframe"], h4["native"], h4["aggregation_base"]) == ("240", False, "15m")
    assert h4["data_identity"].startswith("EXNESS_XAUUSDM_M15") and "inance" not in str(script["contexts"])


def test_gap_scripts_report_the_documented_errors():
    state, session = added("EXNESS_XAUUSDM_H1", "1h", "p21_terminal_gap_lower_tf.pine")
    script = payload_for(state, session)[0]["pine"]["scripts"][0]
    assert script["error"]["message"].startswith("request.security() for a lower timeframe (15) than the chart (60)")
    state, session = added("EXNESS_XAUUSDM_M15", "15m", "p21_terminal_gap_cross_family.pine")
    script = payload_for(state, session)[0]["pine"]["scripts"][0]
    assert script["error"]["message"] == ("Line 5: request.security(): symbol `BINANCE:BTCUSDT` belongs to Binance "
                                          "Futures, but this chart's source is Exness MT5. Requests across data "
                                          "sources are not allowed.") and script["outputs"] == []


def test_replay_walkthrough_values_in_the_checklist():
    state, session = added("EXNESS_BTCUSDM_M15", "15m", "p21_terminal_replay.pine")
    _, _, frame = T._load(state)
    times = replay_model.frame_times(frame)
    ctx = T.context_for(T._bounds(frame), times)
    replaying, _ = apply_event(state, ev("enter_replay", start="2026-09-10T09:30"), ctx)
    seen = []
    for _ in range(6):
        replaying, _ = apply_event(replaying, ev("step_forward"), ctx)
        revealed = replay_model.revealed(frame, replaying.replay)
        payload, _ = payload_for(replaying, session, revealed, replay_model.info(replaying.replay, times))
        script = payload["pine"]["scripts"][0]
        values = {o["title"]: o["data"][-1]["value"] for o in script["outputs"] if o["kind"] == "plot"}
        last = revealed.iloc[-1]
        hour = revealed[revealed["timestamp"] >= last["timestamp"].floor("h")]
        assert values["HTF high (lookahead_on)"] == hour["high"].max()          # knowable so far, never final early
        assert values["HTF low (lookahead_on)"] == hour["low"].min()
        assert values["HTF close (lookahead_on)"] == last["close"]
        assert all(c["max_source_time"] <= int(last["timestamp"].timestamp()) + 900 for c in script["contexts"])
        seen.append((last["timestamp"].strftime("%H:%M"), values["HTF high (lookahead_on)"],
                     values["HTF low (lookahead_on)"], values["HTF close (lookahead_off)"]))
    assert seen[1:5] == [("10:00", 78011.69, 77917.48, 77956.58), ("10:15", 78011.69, 77891.94, 77956.58),
                         ("10:30", 78019.79, 77785.69, 77956.58), ("10:45", 78019.79, 77785.69, 77834.76)]


def test_recorded_terminal_replay_observations_equal_the_engine():
    """The user's step-by-step Replay record (terminal evidence) is exactly what this engine produces."""
    import json

    record = json.loads(Path("ui/tradingview_mode/pine/parity/terminal/p21_terminal_results.json").read_text())
    steps = record["checks"]["p21_terminal_replay"]["observed_steps"]
    state, session = added("EXNESS_BTCUSDM_M15", "15m", "p21_terminal_replay.pine")
    _, _, frame = T._load(state)
    times = replay_model.frame_times(frame)
    ctx = T.context_for(T._bounds(frame), times)
    replaying, _ = apply_event(state, ev("enter_replay", start="2026-09-10T09:30"), ctx)
    for index, step in enumerate(steps):
        if index:
            replaying, _ = apply_event(replaying, ev("step_forward"), ctx)
        revealed = replay_model.revealed(frame, replaying.replay)
        payload, _ = payload_for(replaying, session, revealed, replay_model.info(replaying.replay, times))
        values = {o["title"]: o["data"][-1]["value"] for o in payload["pine"]["scripts"][0]["outputs"] if o["kind"] == "plot"}
        assert revealed["timestamp"].iloc[-1].strftime("%H:%M") == step["bar"]
        assert values["HTF high (lookahead_on)"] == pytest.approx(step["h1_high"], abs=0.005)
        assert values["HTF low (lookahead_on)"] == pytest.approx(step["h1_low"], abs=0.005)
        assert values["HTF close (lookahead_on)"] == pytest.approx(step["h1_close"], abs=0.005)
        assert values["chart close"] == pytest.approx(step["chart_close"], abs=0.005)
        if "completed_h1_close" in step:
            assert values["HTF close (lookahead_off)"] == pytest.approx(step["completed_h1_close"], abs=0.005)
    assert all(check["result"] == "PASS" for check in record["checks"].values())
    assert record["evidence_tiers"]["real_tradingview_verified"][0].startswith("historical request.security() mapping")


def test_binance_scripts_in_live_use_native_binance_contexts_and_the_forming_bar():
    now = pd.Timestamp("2026-09-27 10:37", tz="UTC")

    class Rest:
        def klines(self, symbol, interval, limit, end_ms=None):
            size = {"1h": 3_600_000, "4h": 14_400_000}[interval]
            last = int(now.timestamp() * 1000) // size * size
            return [[o, "100", "105", "95", str(101 + (o // size) % 7), "1", o + size - 1]
                    for o in [last - k * size for k in range(limit)][::-1]]

    provider = SD.BinanceProvider(rest=Rest(), clock=lambda: now.timestamp())
    stamps = pd.date_range(now.floor("15min") - pd.Timedelta(minutes=15 * 300), periods=301, freq="15min", tz="UTC")
    frame = pd.DataFrame({"timestamp": stamps, "open": 100.0, "high": 104.0, "low": 96.0, "close": 101.0, "volume": 1.0})
    expected_contexts = {"p21_terminal_binance_history.pine": 3, "p21_terminal_binance_history_pane.pine": 2,
                         "p21_terminal_binance_live.pine": 1}
    for name, count in expected_contexts.items():
        state, session = added("EXNESS_BTCUSDM_M15", "15m", name)
        for tick in (101.0, 103.5, 99.25):
            frame.loc[frame.index[-1], ["close", "high", "low"]] = [tick, max(104.0, tick), min(96.0, tick)]
            section = PB.pine_payload(state, frame, session, identity=("live", "BINANCE_LIVE:BTCUSDT", "15m"),
                                      timeframe_seconds=900, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT", mintick=0.1,
                                      forming_last=True, chart_family="binance", mode="live",
                                      knowable_until=int(frame["timestamp"].iloc[-1].timestamp() * 1000),
                                      provider=provider)
            script = section["scripts"][0]
            assert script["error"] is None and len(script["contexts"]) == count
            assert all(c["provider"] == "Binance Futures" and c["native"] and c["forming"] for c in script["contexts"])
            if name == "p21_terminal_binance_live.pine":
                values = {o["title"]: o["data"][-1]["value"] for o in script["outputs"] if o["kind"] == "plot"}
                assert values["HTF close (forming)"] == pytest.approx(tick)

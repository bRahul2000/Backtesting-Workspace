"""Zoneflow custom-Pine compatibility: Rahul's exact 572-line "Gold Range Hunter - Monthly Profiles V2" strategy
(fixtures/gold_range_hunter_monthly_profiles_v2.pine, never edited) plus focused tests of every capability it needed:
input.time(), polymorphic color qualifiers for input.color() defaults, calendar functions in a time zone and
time(timeframe, session, timezone)."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pandas as pd
import pytest

from ui.tradingview_mode.component import security_data as SD
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context, resolve_inputs

from .helpers import bars, diagnostics, plots, run

FIXTURE = Path(__file__).parent / "fixtures" / "gold_range_hunter_monthly_profiles_v2.pine"
FIXTURE_SHA256 = "d30ea9ea63000d3c59c55c47cd2022b813a3fc203586d57764057fbfae17d5d4"
CUTOFF = "2026-06-03"            # Gold V2 sealed windows start here: rows from this date on are never parsed


def v6(body: str, header: str = 'indicator("T")') -> str:
    return f"//@version=6\n{header}\n" + body.strip("\n") + "\n"


def errors(source: str) -> list[tuple[int, str]]:
    return [(line, message) for kind, line, message in diagnostics(source) if kind in ("error", "gap")]


# ---- the exact script -----------------------------------------------------------------------------------------------

def test_fixture_is_the_exact_user_script():
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    text = raw.decode()
    assert len(text.split("\n")) == 572                       # the editor's line count (trailing newline = line 572)
    assert 'strategy("Gold Range Hunter - Monthly Profiles V2"' in text


def test_exact_script_compiles_without_diagnostics():
    result = compile_script(FIXTURE.read_text())
    assert result.ok, [d.text() for d in result.diagnostics]
    assert result.diagnostics == []
    assert result.meta["kind"] == "strategy"
    kinds = [(i.kind, i.title) for i in result.inputs]
    assert kinds[:2] == [("time", "Backtest Start Date Combined AB"), ("time", "Backtest End Date")]
    assert [i.defval for i in result.inputs[:2]] == [1756665000000, 1924972140000]
    colors = {i.title: i.as_dict()["defval"] for i in result.inputs if i.kind == "color"}
    assert set(colors) == {"Box Fill", "Box Border"}


# ---- input.time() --------------------------------------------------------------------------------------------------

DATE_FILTER = """
startDate = input.time(1756665000000, "Backtest Start Date Combined AB")
endDate = input.time(1924972140000, "Backtest End Date")
inBacktest = time >= startDate and time <= endDate
plot(inBacktest ? 1 : 0, "in")
plot(time >= startDate ? 1 : 0, "ge")
plot(time <= endDate ? 1 : 0, "le")
"""


def test_input_time_is_an_input_int_in_milliseconds_and_compares_with_time():
    # 2025-08-31 18:30:00 UTC is 1756665000000 ms: the 18:00 and 18:15 bars are before it, 18:30 is included (>=)
    out, _ = run(v6(DATE_FILTER), bars(6, start="2025-08-31 18:00"))
    p = plots(out)
    assert p["ge"] == [0, 0, 1, 1, 1, 1]
    assert p["le"] == [1] * 6
    assert p["in"] == [0, 0, 1, 1, 1, 1]
    # 2030-12-31 18:29 UTC: the 18:15 bar is inside, 18:30 is after the end (<=)
    out, _ = run(v6(DATE_FILTER), bars(3, start="2030-12-31 18:15"))
    assert plots(out)["le"] == [1, 0, 0]


def test_input_time_overrides_and_validation():
    result = compile_script(v6(DATE_FILTER))
    start = result.inputs[0]
    assert start.kind == "time" and start.as_dict()["defval"] == 1756665000000
    later = 1756665000000 + 30 * 60_000
    values, problems = resolve_inputs(result.program, {0: later})
    assert problems == []
    out = run_script(PineExecution(result.program, values), data_context(
        bars(6, start="2025-08-31 18:00"), timeframe_seconds=900, ticker="T", tickerid="T:T", mintick=0.01), ("t",), "t")
    assert plots(out)["ge"] == [0, 0, 0, 0, 1, 1]
    _, problems = resolve_inputs(result.program, {0: "2025-09-01"})
    assert problems == ["Backtest Start Date Combined AB: must be a UNIX time in milliseconds"]
    values, problems = resolve_inputs(result.program, {0: float(later)})
    assert problems == [] and values[start.node_id] == later


def test_input_time_accepts_the_full_signature_and_is_input_qualified():
    source = v6("""
t = input.time(1767323040000, "When", tooltip="tip", inline="a", group="g", confirm=false,
     display=display.none, active=true)
simple int s = t
plot(time >= t ? 1 : 0)
""")
    assert errors(source) == []
    assert compile_script(source).inputs[0].defval == 1767323040000


@pytest.mark.parametrize("defval, fragment", [
    ("time", "a `series int` was used but a `const int` is expected"),
    ('"2025-09-01"', "`input.time` with argument `defval`"),
])
def test_input_time_rejects_non_constant_or_non_int_defaults(defval, fragment):
    found = errors(v6(f"t = input.time({defval})\nplot(t)"))
    assert found and fragment in found[0][1], found


def test_input_time_result_is_not_const():
    found = errors(v6("t = input.time(0)\nn = input.int(t)\nplot(n)"))
    assert found and "input int" in found[0][1], found


# ---- input.color() defaults: qualifier propagation -------------------------------------------------------------------

@pytest.mark.parametrize("defval", [
    "#2196F3", "#2196F355", "color.blue", "color.new(color.blue, 85)", "color.new(#FF0000, 50)",
    "color.new(color.blue, 85 + 5)", "color.new(color = color.red, transp = 20)", "color.rgb(33, 150, 243)",
    "color.rgb(33, 150, 243, 40)", "true ? color.red : color.blue",
])
def test_constant_color_expressions_are_valid_input_color_defaults(defval):
    assert errors(v6(f'c = input.color({defval}, "C")\nplot(close, color=c)')) == []


def test_line_137_default_is_a_const_color_with_the_right_value():
    result = compile_script(v6('c = input.color(color.new(color.blue, 85), "Box Fill")\nplot(close, color=c)'))
    assert result.ok
    color = result.inputs[0].defval
    assert (color.r, color.g, color.b, color.t) == (0x21, 0x96, 0xF3, 85)


@pytest.mark.parametrize("defval, qualifier", [
    ("color.new(color.blue, close)", "series color"),
    ("close > open ? color.green : color.red", "series color"),
    ("color.new(color.blue, bar_index % 100)", "series color"),
    ("color.rgb(close % 255, 0, 0)", "series color"),
    ("base", "input color"),
    ("color.new(base, 50)", "input color"),
])
def test_non_constant_color_defaults_are_rejected(defval, qualifier):
    found = errors(v6(f'base = input.color(color.red)\nc = input.color({defval}, "C")\nplot(close, color=c)'))
    assert found and f"a `{qualifier}` was used but a `const color` is expected" in found[0][1], found


def test_color_functions_keep_the_strongest_argument_qualifier():
    source = v6("""
base = input.color(color.red)
k = input.color(color.new(color.blue, 85))
simple color s = color.new(base, 50)
plot(close, color=color.new(base, close > open ? 0 : 50))
""")
    assert errors(source) == []
    found = errors(v6("base = input.color(color.red)\nk = input.color(color.new(base, 50))\nplot(close, color=k)"))
    assert found and "a `input color` was used" in found[0][1], found


# ---- calendar functions in a time zone -----------------------------------------------------------------------------

TZ_BODY = """
plot(hour(time, "{tz}"), "h")
plot(minute(time, "{tz}"), "m")
plot(dayofweek(time, "{tz}"), "dow")
plot(month(time, "{tz}"), "mon")
plot(dayofmonth(time, "{tz}"), "dom")
"""


@pytest.mark.parametrize("tz", ["Asia/Kolkata", "Asia/Calcutta", "UTC+5:30", "UTC+05:30", "GMT+0530"])
def test_calendar_parts_in_india_time(tz):
    # 2026-01-31 (Saturday) 18:15 UTC = 2026-01-31 23:45 IST; 18:30 UTC = 2026-02-01 (Sunday) 00:00 IST
    out, _ = run(v6(TZ_BODY.format(tz=tz)), bars(2, start="2026-01-31 18:15"))
    p = plots(out)
    assert p["h"] == [23, 0] and p["m"] == [45, 0]
    assert p["dow"] == [7, 1] and p["mon"] == [1, 2] and p["dom"] == [31, 1]


def test_iana_zones_follow_daylight_saving_and_offsets_can_be_negative():
    body = 'plot(hour(time, "America/New_York"), "ny")\nplot(hour(time, "UTC-3"), "m3")\nplot(hour(time), "utc")'
    out, _ = run(v6(body), bars(1, start="2026-01-15 15:00"))
    assert plots(out) == {"ny": [10], "m3": [12], "utc": [15]}
    out, _ = run(v6(body), bars(1, start="2026-07-15 15:00"))
    assert plots(out)["ny"] == [11]


def test_invalid_time_zone_is_a_runtime_error():
    result = compile_script(v6('plot(hour(time, "Mars/Olympus"))'))
    out = run_script(PineExecution(result.program, {}), data_context(bars(3), timeframe_seconds=900, ticker="T",
                                                                     tickerid="T:T", mintick=0.01), ("t",), "t")
    assert out.error is not None and "Invalid time zone 'Mars/Olympus'" in out.error["message"]


# ---- time(timeframe, session, timezone) -------------------------------------------------------------------------------

def in_session(session: str, tz: str | None, start: str, n: int) -> list[int]:
    tz_arg = f', "{tz}"' if tz else ""
    body = f'plot(na(time(timeframe.period, "{session}"{tz_arg})) ? 0 : 1, "s")\nplot(time(timeframe.period, "{session}"{tz_arg}), "t")'
    out, _ = run(v6(body), bars(n, start=start))
    p = plots(out)
    # inside the session time() is the bar's own open time
    times = [int(ts.timestamp() * 1000) for ts in pd.date_range(start, periods=n, freq="15min", tz="UTC")]
    assert [t for t, s in zip(p["t"], p["s"]) if s] == [t for t, s in zip(times, p["s"]) if s]
    return p["s"]


def test_morning_range_session_in_india_time():
    # "0330-0545" IST = 22:00-00:15 UTC: bars opening 22:00 ... 00:00 are inside, 00:15 is not (end exclusive)
    assert in_session("0330-0545", "Asia/Kolkata", "2026-03-02 21:30", 13) == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0]


def test_ny_range_session_in_india_time():
    # "1700-1830" IST = 11:30-13:00 UTC
    assert in_session("1700-1830", "Asia/Kolkata", "2026-03-02 11:00", 10) == [0, 0, 1, 1, 1, 1, 1, 1, 0, 0]


def test_session_without_a_time_zone_uses_the_exchange_time_zone_utc():
    # 03:30 ... 05:30 UTC open inside the session (9 bars); 05:45 is the exclusive end
    assert in_session("0330-0545", None, "2026-03-02 03:00", 13) == [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0]


def test_multiple_periods_days_and_overnight_sessions():
    # 2026-03-06 is a Friday (6), 2026-03-07 a Saturday (7)
    assert in_session("0000-0030,0100-0115:6", "UTC", "2026-03-06 00:00", 6) == [1, 1, 0, 0, 1, 0]
    assert in_session("0000-0030:7", "UTC", "2026-03-06 00:00", 2) == [0, 0]
    # overnight "2300-0100:7" is the Saturday session: it starts Friday 23:00 and ends Saturday 01:00
    assert in_session("2300-0100:7", "UTC", "2026-03-06 22:45", 10) == [0, 1, 1, 1, 1, 1, 1, 1, 1, 0]
    assert in_session("2300-0100:6", "UTC", "2026-03-06 22:45", 10) == [0] * 10    # Friday's ended at 01:00
    assert in_session("2300-0100:6", "UTC", "2026-03-05 22:45", 10) == [0, 1, 1, 1, 1, 1, 1, 1, 1, 0]


def test_24x7_and_invalid_sessions():
    assert in_session("24x7", None, "2026-03-06 00:00", 3) == [1, 1, 1]
    result = compile_script(v6('plot(time(timeframe.period, "0930-25:00"))'))
    out = run_script(PineExecution(result.program, {}), data_context(bars(3), timeframe_seconds=900, ticker="T",
                                                                     tickerid="T:T", mintick=0.01), ("t",), "t")
    assert out.error is not None and "Invalid session" in out.error["message"]


# ---- acceptance: the exact script on Zoneflow's EXNESS XAUUSDm dataset ----------------------------------------------

def _truncated(path: Path) -> pd.DataFrame:
    """Rows before CUTOFF only; later rows are never parsed (text-level stop on the sorted file)."""
    keep = []
    with open(path) as handle:
        keep.append(handle.readline())
        for line in handle:
            if line[:10] >= CUTOFF:
                break
            keep.append(line)
    frame = pd.read_csv(io.StringIO("".join(keep)))
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


class _TruncatedProvider(SD.DatasetProvider):
    def _load(self, entry):
        return SD._Loaded(SD._frame_bars(_truncated(entry.path), entry.step_seconds), f"truncated<{CUTOFF}", 0.0)


@pytest.fixture(scope="module")
def xau():
    datasets = {d.key: d for d in SD.all_datasets()}
    if "EXNESS_XAUUSDM_M15" not in datasets or not datasets["EXNESS_XAUUSDM_M15"].path.exists():
        pytest.skip("EXNESS XAUUSDm M15 dataset not present")
    frame = _truncated(datasets["EXNESS_XAUUSDM_M15"].path)
    return frame, data_context(frame, timeframe_seconds=900, ticker="XAUUSDm", tickerid="EXNESS:XAUUSDm", mintick=0.001,
                               kind="cfd")


def _accept(data):
    result = compile_script(FIXTURE.read_text())
    assert result.ok
    provider = _TruncatedProvider("exness")
    return run_script(PineExecution(result.program, {}, provider), data, ("grh",), "grh", provider)


def test_exact_script_runs_and_backtests_on_xauusdm(xau):
    frame, data = xau
    assert frame["timestamp"].iloc[-1] < pd.Timestamp(CUTOFF, tz="UTC")
    out = _accept(data)
    assert out.error is None, out.error
    assert out.executed == len(frame)
    report = out.strategy
    trades, metrics = report["trades"], report["metrics"]
    assert len(trades) > 50 and metrics["total_closed_trades"] == len(trades)
    assert metrics["long_trades"] > 0 and metrics["short_trades"] > 0
    assert metrics["commission_paid"] == 0
    # every trade draws entry / SL / TP lines (showTradeLevels) and every range a box; labels are off by default
    drawings = out.drawings
    assert len(drawings["lines"]) == 3 * len(trades) and len(drawings["labels"]) == 0
    assert len(drawings["boxes"]) > 100
    # remove / re-add: a fresh execution reproduces the identical report
    again = _accept(data)
    assert again.strategy["trades"] == trades and again.strategy["metrics"] == metrics


def test_parity_harness_frozen_security_bars_reproduce_the_terminal_run(xau):
    """strategy_parity.run_strategy(--security-bars 60=...) on the same bars gives the identical trade list: the
    tooling that compares this script with a TradingView "List of trades" export on TradingView's own bars."""
    from ui.tradingview_mode.pine.parity.strategy_parity import run_strategy

    frame, data = xau
    h1 = _truncated(next(d for d in SD.all_datasets() if d.key == "EXNESS_XAUUSDM_H1").path)
    broker = run_strategy(FIXTURE.read_text(), frame, mintick=0.001, timeframe_seconds=900, tickerid="EXNESS:XAUUSDm",
                          security_frames={"60": h1}, currency="USD")
    expected = _accept(data).strategy["trades"]
    closed = list(broker.state.closed)
    assert len(closed) == len(expected)
    assert [(t.entry_bar, t.exit_bar, t.entry_price, t.exit_price, t.exit_comment) for t in closed] == \
        [(t["entry_bar"], t["exit_bar"], t["entry_price"], t["exit_price"], t["exit_comment"]) for t in expected]


def test_semantics_probe_separates_semantic_mismatches_from_feed_differences(xau):
    from ui.tradingview_mode.pine.parity import grh_probe

    zf = grh_probe.ours()
    assert len(zf) > 80
    sessions = [t for t, row in zf.items() if row["morning_session_time"] != "na"]
    assert all(zf[t]["morning_session_time"] == str(t) for t in sessions) and len(sessions) == 9
    times = sorted(zf)
    tv_lines = ["2026-05-08 03:30:00 [info] ZF|GRH|" + "|".join([str(t), *zf[t].values()]) for t in times[1:]]
    tv_lines.append("noise without a probe line")
    tv_lines.append("ZF|GRH|" + "|".join(["1778300000000", *zf[times[0]].values()]))    # a bar only TradingView has
    edited = tv_lines[5].replace("|33,150,243,85|", "|33,150,243,80|")
    tv_lines[5] = edited
    report = grh_probe.compare(grh_probe.parse("\n".join(tv_lines)), zf)
    assert report["bars_compared"] == len(times) - 1
    assert [(m["field"], m["tradingview"], m["zoneflow"]) for m in report["semantic_mismatches"]] == \
        [("box_fill_rgbt", "33,150,243,80", "33,150,243,85")]
    assert report["data_source_only_tradingview"] == [1778300000000]
    assert report["data_source_only_zoneflow"] == [times[0]]
    assert report["semantic_parity"] is False
    assert grh_probe.compare(zf, zf)["semantic_parity"] is True

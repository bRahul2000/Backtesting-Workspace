"""request.security() runtime (P2.1): q4 parity, isolation, nesting, slicing, data policy, Replay and Live."""
import copy

import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.component import security_data as SD
from ui.tradingview_mode.component.protocol import PayloadValidationError, validate_payload
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context
from ui.tradingview_mode.pine.parity import security_fixture as S
from ui.tradingview_mode.pine.security import (BarGrid, Bars, Requested, SecurityDataError, _aggregate,
                                               parse_timeframe)

from .helpers import plots

MIN = 60_000
T0 = int(pd.Timestamp("2026-04-06 00:00", tz="UTC").timestamp() * 1000)     # a Monday, 00:00 UTC


def minute_bar(symbol: str, m: int) -> tuple:
    salt = sum(map(ord, symbol))
    f = lambda k: 100.0 + ((k * 37 + salt) % 101) * 0.25                     # noqa: E731
    o, c = f(m), f(m + 1)
    return o, max(o, c) + 0.25 * (m % 3), min(o, c) - 0.25 * (m * 7 % 3), c, 1.0 + m % 5


def minute_bars(symbol: str, first_ms: int, last_ms: int) -> Bars:
    opens = np.arange(first_ms, last_ms + 1, MIN, dtype=np.int64)
    rows = [minute_bar(symbol, int(t) // MIN) for t in opens]
    cols = [np.array(c, dtype=float) for c in zip(*rows)] if rows else [np.zeros(0)] * 5
    return Bars(opens, opens + MIN, *cols)


class FakeBinance:
    """Binance-family provider over deterministic 1-minute bars (requested bars are aggregated from them)."""

    family = "binance"
    SYMBOLS = {"BTCUSDT", "XAUUSDT"}

    def __init__(self, history_minutes: int = 3000):
        self.history = history_minutes
        self.calls = []

    def check_symbol(self, symbol: str) -> str:
        prefix, name = (symbol.split(":", 1) + [None])[:2] if ":" in symbol else (None, symbol)
        if prefix and prefix.upper() != "BINANCE":
            raise SecurityDataError(f"symbol `{symbol}` belongs to Exness MT5, but this chart's source is Binance "
                                    "Futures. Requests across data sources are not allowed.", "cross_family")
        if name.upper() not in self.SYMBOLS:
            raise SecurityDataError(f"symbol `{symbol}` is not available.", "unknown_symbol")
        return name.upper()

    def request(self, symbol, timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms, chart_end_ms):
        name = self.check_symbol(symbol)
        self.calls.append((name, timeframe.text, knowable, until_ms))
        grid = BarGrid(timeframe)
        base = minute_bars(name, T0 - self.history * MIN, chart_end_ms)
        rows = _aggregate(base, 0, base.size, grid)
        bars = Bars(*(np.array(c, dtype=np.int64 if i < 2 else float) for i, c in enumerate(zip(*rows))))
        if knowable:
            bars = bars.upto_close(until_ms)
        other = base.upto_close(until_ms) if knowable and name != parent_tickerid.split(":")[-1] else None
        return Requested(bars, grid, name, f"BINANCE:{name}", {
            "provider_family": "binance", "provider": "fake", "native": True, "aggregation_base": None,
            "data_identity": f"fake:{name}:{timeframe.text}", "fingerprint": None},
            same_as_parent=name == parent_tickerid.split(":")[-1], base=other)


def chart(n: int, symbol: str = "BTCUSDT", start: int = T0) -> pd.DataFrame:
    bars = minute_bars(symbol, start, start + (n - 1) * MIN)
    return pd.DataFrame({"timestamp": pd.to_datetime(bars.time, unit="ms", utc=True), "open": bars.open,
                         "high": bars.high, "low": bars.low, "close": bars.close, "volume": bars.volume})


def run(source, frame, provider, *, knowable=False, forming=False, execution=None, identity=("t",)):
    result = compile_script(source)
    assert result.ok, [d.text() for d in result.diagnostics]
    until = int(frame["timestamp"].iloc[-1].timestamp() * 1000) + (0 if forming else MIN) if knowable else None
    data = data_context(frame, timeframe_seconds=60, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT", mintick=0.1,
                        forming_last=forming, knowable=knowable, knowable_until=until)
    execution = execution or PineExecution(result.program, {}, provider)
    out = run_script(execution, data, identity, "t", provider)
    return out, execution


def script(body: str) -> str:
    return '//@version=6\nindicator("t")\n' + body.strip("\n") + "\n"


def htf_expected(frame, tf_minutes: int, column: str, lookahead: bool, gaps: bool):
    """Independent mapping (q4 rules) over requested bars aggregated from the fake 1-minute data."""
    grid = BarGrid(parse_timeframe(str(tf_minutes)))
    base = minute_bars("BTCUSDT", T0 - 3000 * MIN, int(frame["timestamp"].iloc[-1].timestamp() * 1000))
    rows = _aggregate(base, 0, base.size, grid)
    index = {"open": 2, "high": 3, "low": 4, "close": 5}[column]
    out, previous = [], None
    for stamp in frame["timestamp"]:
        t = int(stamp.timestamp() * 1000)
        if lookahead:
            chosen = max((r for r in rows if r[0] <= t), key=lambda r: r[0])
        else:
            chosen = max((r for r in rows if r[1] <= t + MIN), key=lambda r: r[0])
        out.append(None if gaps and previous == chosen[0] else chosen[index])
        previous = chosen[0]
    return out


# ---- A. historical parity with the frozen q4 TradingView oracle ----------------------------------------------------

def test_engine_reproduces_the_q4_tradingview_oracle_cell_for_cell():
    report = S.engine_parity()
    assert report["matched"] == report["cells"] == 134_400, report["first_mismatches"]
    assert set(report["by_group"]) == {"tf1", "single"} | {c.key for c in S.COMBOS}
    assert all(matched == checked for matched, checked in report["by_group"].values())
    assert report["contexts"] == 13
    import json
    stored = json.loads((S.ROOT / "ours" / "q4_engine_parity.json").read_text())
    assert stored["matched"] == stored["cells"] == 134_400 and stored["by_group"] == {k: list(v) for k, v in report["by_group"].items()}


# ---- B-D. isolation, call paths, tuples -----------------------------------------------------------------------------

def test_two_call_sites_on_the_same_timeframe_do_not_share_state():
    out, _ = run(script("""
counter() =>
    var int n = 0
    n += 1
    n
a = request.security(syminfo.tickerid, "5", counter())
b = request.security(syminfo.tickerid, "5", counter())
plot(a, "a")
plot(b, "b")
"""), chart(60), FakeBinance())
    p = plots(out)
    assert p["a"] == p["b"] and len(out.contexts) == 2
    assert p["a"][-1] == 3000 // 5 + 60 // 5        # one increment per requested bar, not two


def test_user_function_call_paths_get_their_own_contexts():
    out, _ = run(script("""
f() => request.security(syminfo.tickerid, "5", ta.cum(1))
x = f()
y = f()
plot(x, "x")
plot(y, "y")
"""), chart(40), FakeBinance())
    assert plots(out)["x"] == plots(out)["y"] and len(out.contexts) == 2


def test_tuple_elements_keep_their_order_and_equal_single_requests():
    frame = chart(90)
    out, _ = run(script("""
[o, h, l, c] = request.security(syminfo.tickerid, "15", [open, high, low, close])
plot(o, "o")
plot(h, "h")
plot(l, "l")
plot(c, "c")
plot(request.security(syminfo.tickerid, "15", high), "h_single")
"""), frame, FakeBinance())
    p = plots(out)
    assert p["h"] == p["h_single"]
    for column, name in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c")):
        assert p[name] == pytest.approx(htf_expected(frame, 15, column, False, False))


# ---- E-F. gaps / lookahead on OHLC data ----------------------------------------------------------------------------

@pytest.mark.parametrize("gaps", [False, True])
@pytest.mark.parametrize("lookahead", [False, True])
def test_gaps_and_lookahead_follow_the_confirmed_mapping(gaps, lookahead):
    frame = chart(75)
    g = "barmerge.gaps_on" if gaps else "barmerge.gaps_off"
    la = "barmerge.lookahead_on" if lookahead else "barmerge.lookahead_off"
    out, _ = run(script(f'plot(request.security(syminfo.tickerid, "5", close, gaps={g}, lookahead={la}), "v")'),
                 frame, FakeBinance())
    assert plots(out)["v"] == htf_expected(frame, 5, "close", lookahead, gaps)


# ---- G-H. nesting and lower timeframes ------------------------------------------------------------------------------

def test_nesting_depth_one_and_two_work_and_three_fails():
    frame = chart(130)
    out, _ = run(script("""
plot(request.security(syminfo.tickerid, "15", request.security(syminfo.tickerid, "60", close)), "two")
plot(request.security(syminfo.tickerid, "60", close), "one")
"""), frame, FakeBinance())
    assert out.error is None and len(out.contexts) == 3 and {c["depth"] for c in out.contexts} == {1, 2}
    three = compile_script(script("""
v = request.security(syminfo.tickerid, "5", request.security(syminfo.tickerid, "15", request.security(syminfo.tickerid, "60", close)))
plot(v)
"""))
    data = data_context(frame, timeframe_seconds=60, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT", mintick=0.1)
    failed = run_script(PineExecution(three.program, {}, FakeBinance()), data, ("t",), "t", FakeBinance())
    assert "Current Pine engine limit: request.security() can be nested at most 2 levels deep." in failed.error["message"]


def test_lower_timeframe_requests_fail_explicitly():
    frame = chart(30)
    result = compile_script(script('plot(request.security(syminfo.tickerid, "1", close))'))
    data = data_context(frame, timeframe_seconds=300, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT", mintick=0.1)
    out = run_script(PineExecution(result.program, {}, FakeBinance()), data, ("t",), "t", FakeBinance())
    assert "lower timeframe (1) than the chart (5) is not implemented yet" in out.error["message"]
    assert compile_script(script('x = request.security_lower_tf(syminfo.tickerid, "1", close)')).diagnostics[0].kind == "gap"


# ---- I. dependency slicing -------------------------------------------------------------------------------------------

def test_slices_include_exactly_the_dependencies():
    result = compile_script(script("""
len = input.int(5)
float base = close * 2
var float acc = 0.0
acc += 1
unrelated = ta.rsi(close, 14)
plot(unrelated)
x = request.security(syminfo.tickerid, "60", ta.sma(base, len) + acc)
plot(x)
"""))
    spec = next(iter(result.program.security.values()))
    assert spec.slice_lines == (3, 4, 5, 6)


@pytest.mark.parametrize("body,fragment", [
    ("if close > open\n    local = close\n    v = request.security(syminfo.tickerid, '60', local)",
     "uses the local variable `local`"),
    ("var float s = 0.0\nx = request.security(syminfo.tickerid, '60', s)\ns := close",
     "`s` is reassigned on line 5, at or after the request"),
    ("var float s = 0.0\nif close > open\n    s := close\n    alert('up')\nx = request.security(syminfo.tickerid, '60', s)",
     "which also calls `alert()` (a side effect)"),
    ("m = close\nf() => request.security(syminfo.tickerid, '60', m)\nx = f()",
     "inside a function depends on the global variable `m`"),
    ("a = array.new<float>()\nx = request.security(syminfo.tickerid, '60', array.size(a))", "not implemented yet"),
])
def test_unsupported_dependencies_are_explicit_capability_gaps(body, fragment):
    result = compile_script(script(body))
    assert not result.ok
    assert any(fragment in d.message for d in result.diagnostics), [d.text() for d in result.diagnostics]
    assert all(d.kind in ("gap", "warning") for d in result.diagnostics)


# ---- J-K. data policy, cross-family, provenance --------------------------------------------------------------------

def test_cross_family_requests_are_refused_statically_and_at_run_time():
    with pytest.raises(SecurityDataError) as exc:
        SD.DatasetProvider("exness").check_symbol("BINANCE:BTCUSDT")
    assert exc.value.kind == "cross_family" and "Exness MT5" in exc.value.message and "Binance Futures" in exc.value.message
    for symbol in ("XAUUSDm", "EXNESS:BTCUSDm"):
        with pytest.raises(SecurityDataError) as exc:
            SD.BinanceProvider(rest=object()).check_symbol(symbol)
        assert exc.value.kind == "cross_family"
    dynamic = compile_script(script('s = input.string("EXNESS:XAUUSDm")\nplot(request.security(s, "5", close))'))
    frame = chart(20)
    data = data_context(frame, timeframe_seconds=60, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT", mintick=0.1)
    out = run_script(PineExecution(dynamic.program, {}, FakeBinance()), data, ("t",), "t", FakeBinance())
    assert "Requests across data sources are not allowed" in out.error["message"]


def test_exness_provenance_native_aggregated_and_blocked():
    provider = SD.DatasetProvider("exness")
    ask = lambda tf: provider.request("XAUUSDm", parse_timeframe(tf), parent_tickerid="EXNESS:XAUUSDm",  # noqa: E731
                                      parent_seconds=900, knowable=False, until_ms=None, chart_end_ms=None)
    h1, h4, day = ask("60"), ask("240"), ask("D")
    assert h1.provenance["native"] is True and h1.provenance["data_identity"].startswith("EXNESS_XAUUSDM_H1")
    assert h4.provenance["native"] is False and h4.provenance["aggregation_base"] == "15m"
    assert day.provenance["aggregation_base"] == "15m" and day.provenance["fingerprint"].startswith("sha256:")
    assert all(int(t) % 14_400_000 == 0 for t in h4.bars.time)            # server offset 0: 4H on 00/04/08...
    assert all(int(t) % 86_400_000 == 0 for t in day.bars.time)
    for tf in ("W", "M"):
        with pytest.raises(SecurityDataError, match="Current Pine engine limit: (weekly|monthly) Exness MT5 bars"):
            ask(tf)
    with pytest.raises(SecurityDataError, match="not a multiple"):
        ask("20")


def test_binance_native_and_aggregated_intervals_use_public_klines_only():
    class Rest:
        def __init__(self):
            self.calls = []

        def klines(self, symbol, interval, limit, end_ms=None):
            self.calls.append((symbol, interval, limit, end_ms))
            size = {"4h": 14_400_000, "30m": 1_800_000, "1m": 60_000}[interval]
            last = (T0 + 10 * 86_400_000) // size * size
            opens = [last - k * size for k in range(min(limit, 50))][::-1]
            return [[o, "1", "2", "0.5", "1.5", "10", o + size - 1] for o in opens]

    rest = Rest()
    provider = SD.BinanceProvider(rest=rest, clock=lambda: (T0 + 11 * 86_400_000) / 1000)
    native = provider.request("BTCUSDT", parse_timeframe("240"), parent_tickerid="BINANCE:BTCUSDT", parent_seconds=60,
                              knowable=False, until_ms=None, chart_end_ms=T0 + 20 * 86_400_000)
    custom = provider.request("BTCUSDT", parse_timeframe("90"), parent_tickerid="BINANCE:BTCUSDT", parent_seconds=60,
                              knowable=False, until_ms=None, chart_end_ms=T0 + 20 * 86_400_000)
    assert native.provenance["native"] and "klines:BTCUSDT:4h" in native.provenance["data_identity"]
    assert custom.provenance["native"] is False and custom.provenance["aggregation_base"] == "30m"
    assert {call[1] for call in rest.calls} == {"4h", "30m"}                   # klines only, nothing signed


# ---- L-M. Replay: knowable at cursor ---------------------------------------------------------------------------------

def _exness_frame(n: int) -> pd.DataFrame:
    from utils.data_validation import load_ohlcv_csv
    from services.market_datasets import dataset

    frame = load_ohlcv_csv(dataset("EXNESS_BTCUSDM_M15").path)
    return frame.iloc[-n:].reset_index(drop=True)


REPLAY_SCRIPT = script("""
plot(request.security(syminfo.tickerid, "240", close, lookahead=barmerge.lookahead_on), "on")
plot(request.security(syminfo.tickerid, "240", close), "off")
plot(request.security(syminfo.tickerid, "60", ta.ema(close, 5), gaps=barmerge.gaps_on), "gaps")
[h4h, h4l] = request.security(syminfo.tickerid, "240", [high, low])
plot(h4h, "h4h")
""")


def _replay_run(frame, execution=None):
    provider = SD.DatasetProvider("exness")
    until = int(frame["timestamp"].iloc[-1].timestamp() * 1000) + 900_000
    data = data_context(frame, timeframe_seconds=900, ticker="BTCUSDm", tickerid="EXNESS:BTCUSDm", mintick=0.01,
                        knowable=True, knowable_until=until)
    program = compile_script(REPLAY_SCRIPT).program
    execution = execution or PineExecution(program, {}, provider)
    return run_script(execution, data, ("replay", "EXNESS_BTCUSDM_M15"), "r", provider), execution, until


def test_replay_never_uses_data_after_the_cursor_and_lookahead_on_shows_the_forming_bar():
    full = _exness_frame(400)
    cursor = 300
    while int(full["timestamp"].iloc[cursor].timestamp()) % 14_400 != 3600:     # mid-4H (second of four 15m bars... 1h in)
        cursor += 1
    out, _, until = _replay_run(full.iloc[:cursor + 1].reset_index(drop=True))
    assert out.error is None and all(c["max_source_time"] <= until for c in out.contexts)   # ms here; seconds in the payload
    on = plots(out)["on"][-1]
    revealed_close = float(full["close"].iloc[cursor])
    final_4h_close = float(full["close"].iloc[cursor + 11])                    # the 4H bar's final close (future)
    assert on == pytest.approx(revealed_close) and on != final_4h_close        # forming, not final
    historical = run_script(PineExecution(compile_script(REPLAY_SCRIPT).program, {}, SD.DatasetProvider("exness")),
                            data_context(full.iloc[:cursor + 1].reset_index(drop=True), timeframe_seconds=900,
                                         ticker="BTCUSDm", tickerid="EXNESS:BTCUSDm", mintick=0.01),
                            ("historical",), "h", SD.DatasetProvider("exness"))
    assert plots(historical)["on"][-1] == pytest.approx(final_4h_close)       # TradingView historical future bias


def test_provider_refusing_future_bars_is_enforced():
    class Leaky(FakeBinance):
        def request(self, *args, **kwargs):
            answer = super().request(*args, **{**kwargs, "knowable": False})
            return answer                                                      # ignores the cut-off
    # 32 bars: the last 5m bar [30, 35) closes after the cut-off (33): an honest provider would not return it
    out, _ = run(script('plot(request.security(syminfo.tickerid, "5", close))'), chart(32), Leaky(), knowable=True)
    assert "after the knowable time (refused)" in out.error["message"]


def test_a_failing_data_source_is_an_explicit_script_error():
    class Offline(FakeBinance):
        def request(self, *args, **kwargs):
            raise ConnectionError("Binance REST unreachable")
    out, _ = run(script('plot(request.security(syminfo.tickerid, "5", close))'), chart(20), Offline())
    assert out.error["message"] == ("request.security(): the binance data source is unavailable (ConnectionError: "
                                    "Binance REST unreachable).")


def test_replay_incremental_equals_fresh_execution_at_every_step():
    full = _exness_frame(260)
    execution = None
    for step in range(200, 260):
        revealed = full.iloc[:step + 1].reset_index(drop=True)
        incremental, execution, _ = _replay_run(revealed, execution)
        fresh, _, _ = _replay_run(revealed)
        assert incremental.error is None and fresh.error is None
        assert incremental.outputs == fresh.outputs, step
        assert not fresh.incremental and (step == 200 or incremental.executed == 1)


# ---- N. Live: incremental == full recompute on the same received information -----------------------------------------

def test_live_ticks_and_new_bars_equal_a_full_recompute():
    source = script("""
plot(request.security(syminfo.tickerid, "5", close, lookahead=barmerge.lookahead_on), "on")
plot(request.security(syminfo.tickerid, "5", ta.sma(close, 3)), "off")
plot(request.security("XAUUSDT", "15", close, lookahead=barmerge.lookahead_on), "other")
""")
    provider = FakeBinance()
    frame = chart(47)
    _, execution = run(source, frame, provider, knowable=True, forming=True)
    for step, price in enumerate([101.0, 99.5, 103.25, 100.0, 102.0, 98.75]):
        if step == 3:                                                          # a new bar opens (47 -> 48 bars)
            frame = chart(48)
        frame.loc[frame.index[-1], ["close", "high", "low"]] = [price, max(price, 110.0), min(price, 90.0)]
        live, execution = run(source, frame, provider, knowable=True, forming=True, execution=execution)
        full, _ = run(source, frame, provider, knowable=True, forming=True)
        assert live.error is None and live.incremental and live.outputs == full.outputs, step
        assert plots(live)["on"][-1] == pytest.approx(price)                   # the forming requested bar's close


# ---- payload validation -------------------------------------------------------------------------------------------

def test_payload_validator_checks_contexts_independently():
    from tests.tradingview_mode.test_pine_terminal import ev, payload_for, pine_state
    from ui.tradingview_mode.component import replay as replay_model
    from ui.tradingview_mode.component import terminal as T
    from ui.tradingview_mode.component.state import apply_event

    source = script('plot(request.security(syminfo.tickerid, "60", close, lookahead=barmerge.lookahead_on), "h1")')
    state, session = pine_state(source)
    selected, resolution, frame = T._load(state)
    times = replay_model.frame_times(frame)
    replaying, _ = apply_event(state, ev("enter_replay", start="2026-06-10T14:30"), T.context_for(T._bounds(frame), times))
    revealed = replay_model.revealed(frame, replaying.replay)
    payload, notices = payload_for(replaying, session, revealed, replay_model.info(replaying.replay, times))
    contexts = payload["pine"]["scripts"][0]["contexts"]
    assert not notices and payload["pine"]["chart_family"] == "exness" and payload["pine"]["mode"] == "replay"
    assert contexts[0]["provider_family"] == "exness" and contexts[0]["native"] and contexts[0]["timeframe"] == "60"
    for mutate, message in (
            (lambda c: c.__setitem__("max_source_time", c["max_source_time"] + 10 * 86_400), "future leak refused"),
            (lambda c: c.__setitem__("provider_family", "binance"), "cross-family"),
            (lambda c: c.__setitem__("timeframe", "7X"), "timeframe")):
        broken = copy.deepcopy(payload)
        mutate(broken["pine"]["scripts"][0]["contexts"][0])
        with pytest.raises(PayloadValidationError, match=message):
            validate_payload(broken)
    literal = script('plot(request.security("BINANCE:BTCUSDT", "60", close))')
    state2, session2 = pine_state(literal)
    payload2, _ = payload_for(state2, session2)
    assert "Requests across data sources are not allowed" in payload2["pine"]["scripts"][0]["error"]["message"]
    assert payload2["pine"]["scripts"][0]["outputs"] == []

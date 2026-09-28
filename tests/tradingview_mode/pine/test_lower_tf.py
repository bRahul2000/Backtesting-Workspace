"""P2.2-A4 request.security_lower_tf(): the model recorded in P22_LOWER_TF_RESEARCH.md.

TradingView evidence reproduced here: q7 (intrabars belong to the chart bar in which they close), m06 R1 (the
forming chart bar's array ends with the forming received intrabar), R2 (`ignore_invalid_timeframe` -> an na array),
same timeframe -> one element. Everything else follows the documented behaviour and this terminal's locked data
policy (Replay knowable at the cursor, Live received data only, no cross-family data).
"""
import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.component import providers as PR
from ui.tradingview_mode.component import security_data as SD
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine import security as SEC
from ui.tradingview_mode.pine.builtins.arrays import RE10051
from ui.tradingview_mode.pine.engine import data_context
from ui.tradingview_mode.pine.errors import ERROR
from ui.tradingview_mode.pine.security import (BarGrid, Bars, ReceivedBars, Requested, SecurityDataError, _aggregate,
                                               parse_timeframe)

from .helpers import plots
from .test_security import MIN, T0, minute_bar, minute_bars

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from synthetic_mt5_feed import SyntheticFeed  # noqa: E402

PARITY = Path("ui/tradingview_mode/pine/parity")


def bars_at(minutes: int, first_ms: int, last_ms: int) -> Bars:
    base = minute_bars("BTCUSDT", first_ms, last_ms)
    rows = _aggregate(base, 0, base.size, BarGrid(parse_timeframe(str(minutes))))
    return Bars(*(np.array(c, dtype=np.int64 if i < 2 else float) for i, c in enumerate(zip(*rows))))


def chart(minutes: int, n: int, start: int = T0) -> pd.DataFrame:
    b = bars_at(minutes, start, start + n * minutes * MIN - MIN)
    return pd.DataFrame({"timestamp": pd.to_datetime(b.time, unit="ms", utc=True), "open": b.open, "high": b.high,
                         "low": b.low, "close": b.close, "volume": b.volume})


class FakeLTF:
    """Binance-family provider over deterministic 1-minute bars; intrabars from ``first_ms`` on."""

    family = "binance"

    def __init__(self, first_ms: int = T0 - 600 * MIN):
        self.first_ms, self.asks, self.received_bars = first_ms, [], None

    def check_symbol(self, symbol: str) -> str:
        if ":" in symbol and not symbol.upper().startswith("BINANCE:"):
            raise SecurityDataError(f"symbol `{symbol}` belongs to Exness MT5, but this chart's source is Binance "
                                    "Futures. Requests across data sources are not allowed.", "cross_family")
        if symbol.split(":")[-1].upper() != "BTCUSDT":
            raise SecurityDataError(f"symbol `{symbol}` is not available.", "unknown_symbol")
        return "BTCUSDT"

    def request(self, symbol, timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms, chart_end_ms,
                lower=False):
        name = self.check_symbol(symbol)
        self.asks.append((timeframe.text, lower, knowable, until_ms, chart_end_ms))
        end = max(chart_end_ms or 0, until_ms or 0) + 120 * MIN
        bars = bars_at(timeframe.seconds // 60, self.first_ms, end)
        bars = bars.upto_close(until_ms) if knowable else bars.head(int(np.searchsorted(bars.time, chart_end_ms, "right")))
        return Requested(bars, BarGrid(timeframe), name, f"BINANCE:{name}", {
            "provider_family": "binance", "provider": "fake", "native": True, "aggregation_base": None,
            "data_identity": f"fake:{name}:{timeframe.text}", "fingerprint": None}, same_as_parent=True)

    def received(self, symbol, timeframe):
        return self.received_bars


def run(body, frame, provider, minutes, *, knowable=False, forming=False, execution=None, until=None):
    result = compile_script('//@version=6\nindicator("t")\n' + body.strip("\n") + "\n")
    assert result.ok, [d.text() for d in result.diagnostics]
    last_open = int(frame["timestamp"].iloc[-1].timestamp() * 1000)
    if knowable and until is None:
        until = last_open if forming else last_open + minutes * MIN        # the terminal's Live / Replay cut-offs
    data = data_context(frame, timeframe_seconds=minutes * 60, ticker="BTCUSDT", tickerid="BINANCE:BTCUSDT",
                        mintick=0.1, forming_last=forming, knowable=knowable, knowable_until=until)
    execution = execution or PineExecution(result.program, {}, provider)
    out = run_script(execution, data, ("t",), "t", provider)
    return out, execution


def series(body, frame, provider, minutes, **kw):
    out, _ = run(body, frame, provider, minutes, **kw)
    assert out.error is None, out.error
    return plots(out)


def errors(body):
    result = compile_script('//@version=6\nindicator("t")\n' + body.strip("\n") + "\n")
    return [d.message for d in result.diagnostics if d.kind == ERROR]


OFFSETS = """
[t, tc] = request.security_lower_tf(syminfo.tickerid, "{tf}", [time, time_close])
off(array<int> a, int k) => k < a.size() ? (a.get(k) - time) / 60000 : -99
plot(t.size(), "n")
plot(off(t, 0), "o0")
plot(off(tc, 0), "c0")
plot(off(t, 1), "o1")
plot(off(tc, 1), "c1")
plot(t.size() > 0 ? (t.last() - time) / 60000 : -99, "olast")
"""


# ---- mapping: TradingView q7 and the dividing case ------------------------------------------------------------------

def test_q7_non_dividing_intrabars_belong_to_the_chart_bar_they_close_in():
    p = series(OFFSETS.format(tf="10"), chart(15, 12), FakeLTF(), 15)
    for k in range(12):
        row = tuple(p[c][k] for c in ("n", "o0", "c0", "o1", "c1"))
        assert row == ((1, 0, 10, -99, -99) if k % 2 == 0 else (2, -5, 5, 5, 15)), (k, row)   # hh:00 | hh:15


def test_dividing_timeframe_every_intrabar_in_order_and_state_runs_across_chart_bars():
    body = OFFSETS.format(tf="1") + """
float[] ch = request.security_lower_tf(syminfo.tickerid, "1", ta.change(close))
float s = 0.0
for x in ch
    s += nz(x)
plot(s - nz(ta.change(close)), "diff")
[c] = request.security_lower_tf(syminfo.tickerid, "1", [close])
plot(c.last() - close, "lastclose")
"""
    p = series(body, chart(5, 20), FakeLTF(), 5)
    assert set(p["n"]) == {5} and set(p["o0"]) == {0} and set(p["olast"]) == {4}
    assert set(p["lastclose"]) == {0}
    assert all(abs(d) < 1e-9 for d in p["diff"][1:])          # the manual's intrabar ta.change example


def test_same_timeframe_is_a_one_element_array_of_the_chart_bar():
    p = series('a = request.security_lower_tf(syminfo.tickerid, "15", close)\nplot(a.size(), "n")\n'
               'plot(a.size() > 0 ? a.first() - close : na, "d")', chart(15, 8), FakeLTF(), 15)
    assert set(p["n"]) == {1} and set(p["d"]) == {0}


def test_tuples_are_arrays_of_equal_length_matching_the_chart_bar():
    body = """
[o, h, l, c] = request.security_lower_tf(syminfo.tickerid, "5", [open, high, low, close])
plot(o.size() == h.size() and h.size() == l.size() and l.size() == c.size() ? o.size() : -1, "n")
float hi = na
float lo = na
for x in h
    hi := na(hi) ? x : math.max(hi, x)
for x in l
    lo := na(lo) ? x : math.min(lo, x)
plot(o.first() - open, "open")
plot(hi - high, "high")
plot(lo - low, "low")
plot(c.last() - close, "close")
"""
    p = series(body, chart(15, 10), FakeLTF(), 15)
    assert set(p["n"]) == {3}
    for key in ("open", "high", "low", "close"):
        assert all(abs(v) < 1e-9 for v in p[key]), key


# ---- empty and na ---------------------------------------------------------------------------------------------------

def test_no_intrabars_is_an_empty_array_not_na():
    p = series('a = request.security_lower_tf(syminfo.tickerid, "1", close)\nplot(a.size(), "n")\n'
               'plot(na(a) ? 1 : 0, "isna")', chart(5, 10), FakeLTF(first_ms=T0 + 20 * MIN), 5)
    assert p["n"] == [0, 0, 0, 0, 5, 5, 5, 5, 5, 5] and set(p["isna"]) == {0}


def test_a_higher_timeframe_is_an_na_array_with_ignore_and_an_error_without():
    body = """
a = request.security_lower_tf(syminfo.tickerid, "60", close, ignore_invalid_timeframe = true)
[x, y] = request.security_lower_tf(syminfo.tickerid, "60", [open, close], ignore_invalid_timeframe = true)
plot(na(a) ? 1 : 0, "a")
plot(na(x) and na(y) ? 1 : 0, "xy")
"""
    p = series(body, chart(15, 4), FakeLTF(), 15)
    assert set(p["a"]) == {1} and set(p["xy"]) == {1}
    out, _ = run('a = request.security_lower_tf(syminfo.tickerid, "60", close)\nplot(a.size())', chart(15, 4),
                 FakeLTF(), 15)
    assert out.error["message"] == ("request.security_lower_tf(): the timeframe 60 is higher than the chart's (15); "
                                    "only lower or equal timeframes can be requested.")
    out, _ = run('a = request.security_lower_tf(syminfo.tickerid, "60", close, ignore_invalid_timeframe = true)\n'
                 'plot(a.size())', chart(15, 4), FakeLTF(), 15)
    assert "the array is na" in out.error["message"]          # an na array keeps A1's na-array behaviour


def test_ignore_invalid_symbol_gives_na_arrays():
    p = series('a = request.security_lower_tf("BINANCE:NOPE", "1", close, ignore_invalid_symbol = true)\n'
               'plot(na(a) ? 1 : 0, "a")', chart(5, 3), FakeLTF(), 5)
    assert set(p["a"]) == {1}


# ---- arrays: A1 / A2 / A3 -----------------------------------------------------------------------------------------

def test_results_follow_the_a1_array_rules():
    body = """
a = request.security_lower_tf(syminfo.tickerid, "1", time)
plot(bar_index > 0 ? (a[1].first() - time[1]) / 60000 : -1, "prev")
var array<int> keep = na
if bar_index == 2
    keep := a
plot(na(keep) ? -1 : (keep.first() - time) / 60000, "keep")
a.push(0)
plot(a.size(), "mutable")
"""
    p = series(body, chart(5, 6), FakeLTF(), 5)
    assert p["prev"] == [-1, 0, 0, 0, 0, 0]                    # a[1] is the previous bar's array
    assert p["keep"] == [-1, -1, 0, -5, -10, -15]              # the slot keeps bar 2's snapshot
    assert set(p["mutable"]) == {6}                            # a returned array is an ordinary execution-local array
    out, _ = run('a = request.security_lower_tf(syminfo.tickerid, "1", close)\nif bar_index > 0\n    a[1].push(1.0)\n'
                 'plot(0)', chart(5, 3), FakeLTF(), 5)
    assert out.error["message"] == RE10051


def test_user_functions_and_ta_state_run_in_the_intrabar_context():
    body = """
f() => ta.sma(close, 3)
s = request.security_lower_tf(syminfo.tickerid, "1", f())
plot(s.last(), "sma")
"""
    frame = chart(5, 8)
    p = series(body, frame, FakeLTF(), 5)
    ends = [int(t.timestamp() * 1000) + 5 * MIN for t in frame["timestamp"]]
    for k, end in enumerate(ends):
        closes = [minute_bar("BTCUSDT", (end - j * MIN) // MIN)[3] for j in (1, 2, 3)]
        assert abs(p["sma"][k] - sum(closes) / 3) < 1e-9


# ---- Replay: knowable at the cursor ----------------------------------------------------------------------------------

@pytest.mark.parametrize("tf", ["1", "10"])
def test_replay_never_sees_a_future_intrabar_and_matches_the_historical_run(tf):
    frame = chart(15, 10)
    historical = series(OFFSETS.format(tf=tf), frame, FakeLTF(), 15)
    execution = None
    for cursor in range(1, 10):
        view = frame.iloc[:cursor + 1]
        out, execution = run(OFFSETS.format(tf=tf), view, FakeLTF(), 15, knowable=True, execution=execution)
        fresh, _ = run(OFFSETS.format(tf=tf), view, FakeLTF(), 15, knowable=True)
        assert plots(out) == plots(fresh)                                      # incremental == fresh
        for key, values in plots(out).items():
            assert values == historical[key][:cursor + 1], (cursor, key)
        cursor_close = int(view["timestamp"].iloc[-1].timestamp() * 1000) + 15 * MIN
        assert all(c["max_source_time"] is None or c["max_source_time"] <= cursor_close for c in out.contexts)


# ---- Live: received data only, the forming intrabar last (m06 R1) --------------------------------------------------

def live_frame(n_closed: int, forming_minutes: int, last_close: float | None = None) -> pd.DataFrame:
    frame = chart(15, n_closed + 1)
    start = int(frame["timestamp"].iloc[-1].timestamp() * 1000)
    minutes = minute_bars("BTCUSDT", start, start + (forming_minutes - 1) * MIN)
    row = {"open": minutes.open[0], "high": minutes.high.max(), "low": minutes.low.min(),
           "close": minutes.close[-1] if last_close is None else last_close, "volume": minutes.volume.sum()}
    for key, value in row.items():
        frame.loc[frame.index[-1], key] = value
    return frame


def received(frame: pd.DataFrame, forming_minutes: int, last_close: float | None = None) -> ReceivedBars:
    start = int(frame["timestamp"].iloc[-1].timestamp() * 1000)
    b = minute_bars("BTCUSDT", start, start + (forming_minutes - 1) * MIN)
    rows = [(int(b.time[i]), int(b.close_time[i]), float(b.open[i]), float(b.high[i]), float(b.low[i]),
             float(b.close[i]), float(b.volume[i])) for i in range(b.size)]
    if last_close is not None:
        rows[-1] = rows[-1][:5] + (last_close,) + rows[-1][6:]
    return ReceivedBars(rows, forming=True)


LIVE = OFFSETS.format(tf="1") + '[c] = request.security_lower_tf(syminfo.tickerid, "1", [close])\n' \
                                'plot(c.size() > 0 ? c.last() - close : na, "lastEqClose")'


def test_live_forming_bar_ends_with_the_forming_received_intrabar_m06_r1():
    frame = live_frame(6, 10)
    provider = FakeLTF()
    provider.received_bars = received(frame, 10)
    out, execution = run(LIVE, frame, provider, 15, knowable=True, forming=True)
    p = {k: v[-1] for k, v in plots(out).items()}
    assert (p["n"], p["o0"], p["olast"], p["lastEqClose"]) == (10, 0, 9, 0)       # R1: n=10 first=0 last=9
    assert plots(out)["n"][-2] == 15                                               # R1: the confirmed bar n=15
    # a tick: the forming intrabar's value changes; incremental equals a fresh run
    frame = live_frame(6, 10, last_close=123.25)
    provider.received_bars = received(frame, 10, last_close=123.25)
    out, execution = run(LIVE, frame, provider, 15, knowable=True, forming=True, execution=execution)
    fresh, _ = run(LIVE, frame, provider, 15, knowable=True, forming=True)
    assert plots(out) == plots(fresh) and plots(out)["lastEqClose"][-1] == 0
    # a new chart bar: the previous bar's intrabars now come from the provider, its values unchanged
    before = plots(out)
    frame = live_frame(7, 3)
    provider.received_bars = received(frame, 3)
    out, execution = run(LIVE, frame, provider, 15, knowable=True, forming=True, execution=execution)
    assert plots(out)["n"][-2:] == [15, 3] and plots(out)["n"][:-2] == before["n"][:-1]


def test_live_without_a_received_source_shows_no_unreceived_intrabar():
    frame = live_frame(4, 6)
    p = series(OFFSETS.format(tf="1"), frame, FakeLTF(), 15, knowable=True, forming=True)
    assert p["n"][-1] == 0 and p["n"][-2] == 15               # nothing is fetched or synthesised for the forming bar


# ---- limits and diagnostics ------------------------------------------------------------------------------------------

def test_calc_bars_count_and_the_engine_limit(monkeypatch):
    body = 'a = request.security_lower_tf(syminfo.tickerid, "1", close, calc_bars_count = 12)\nplot(a.size(), "n")'
    assert series(body, chart(5, 6), FakeLTF(), 5)["n"] == [0, 0, 0, 2, 5, 5]
    monkeypatch.setattr(SEC, "MAX_BARS_PER_CONTEXT", 30)          # engine limitation (TradingView: 100K-200K)
    p = series('a = request.security_lower_tf(syminfo.tickerid, "1", close)\nplot(a.size(), "n")', chart(5, 6),
               FakeLTF(), 5)
    assert p["n"] == [0, 3, 5, 5, 5, 5]                           # 30 - (5 + 2) = 23 most recent intrabars


def test_provider_is_asked_for_a_lower_timeframe_up_to_the_last_chart_close():
    provider = FakeLTF()
    frame = chart(15, 4)
    series('a = request.security_lower_tf(syminfo.tickerid, "1", close)\nplot(a.size())', frame, provider, 15)
    tf, lower, knowable, until, end = provider.asks[0]
    assert (tf, lower, knowable, until) == ("1", True, False, None)
    assert end == int(frame["timestamp"].iloc[-1].timestamp() * 1000) + 15 * MIN - 1


@pytest.mark.parametrize("body,fragment", [
    ('a = request.security_lower_tf(syminfo.tickerid, "1", close, gaps = barmerge.gaps_on)\nplot(0)', "`gaps`"),
    ('a = request.security_lower_tf(syminfo.tickerid, "1", close, lookahead = barmerge.lookahead_on)\nplot(0)',
     "`lookahead`"),
    ('var float v = 0.0\nv += 1\na = request.security_lower_tf(syminfo.tickerid, "1", v)\nplot(0)',
     "cannot reference the mutable variable `v` directly"),
    ('m = 0.0\nm := close\na = request.security_lower_tf(syminfo.tickerid, "1", m)\nplot(0)',
     "cannot reference the mutable variable `m` directly"),
    ('a = request.security_lower_tf(syminfo.tickerid, "1", array.from(close))\nplot(0)',
     "the expression cannot be a collection"),
])
def test_compile_diagnostics(body, fragment):
    assert any(fragment in message for message in errors(body)), errors(body)


def test_an_immutable_global_and_the_types_compile():
    result = compile_script('//@version=6\nindicator("t")\nk = close * 2\nint[] t = request.security_lower_tf('
                            'syminfo.tickerid, "1", time)\nfloat[] a = request.security_lower_tf(syminfo.tickerid, "1", '
                            'k)\nplot(a.size() + t.size())\n')
    assert result.ok and result.program.uses_arrays


@pytest.mark.parametrize("body,fragment", [
    ('a = request.security_lower_tf(syminfo.tickerid, "1", close, currency = "EUR")\nplot(0)',
     "`currency` conversion is not implemented yet"),
    ('a = request.security_lower_tf("EXNESS:XAUUSDm", "1", close)\nplot(0)', "Requests across data sources"),
])
def test_runtime_diagnostics(body, fragment):
    out, _ = run(body, chart(5, 3), FakeLTF(), 5)
    assert fragment in out.error["message"]


# ---- data authority: providers and received sources -----------------------------------------------------------------

def test_exness_has_no_source_below_its_finest_dataset_and_never_uses_binance():
    provider = SD.DatasetProvider("exness")
    with pytest.raises(SecurityDataError) as exc:
        provider.request("XAUUSDm", parse_timeframe("5"), parent_tickerid="EXNESS:XAUUSDm", parent_seconds=1800,
                         knowable=False, until_ms=None, chart_end_ms=None, lower=True)
    assert exc.value.kind == "missing_source" and "finest dataset is 15m" in exc.value.message
    native = provider.request("BTCUSDm", parse_timeframe("15"), parent_tickerid="EXNESS:BTCUSDm", parent_seconds=3600,
                              knowable=False, until_ms=None, chart_end_ms=None, lower=True)
    assert native.provenance["native"] and native.provenance["provider_family"] == "exness"
    aggregated = provider.request("XAUUSDm", parse_timeframe("30"), parent_tickerid="EXNESS:XAUUSDm",
                                  parent_seconds=3600, knowable=False, until_ms=None, chart_end_ms=None, lower=True)
    assert not aggregated.provenance["native"] and aggregated.provenance["provider_family"] == "exness"


def test_binance_lower_requests_fetch_up_to_the_engine_limit_with_their_own_cache():
    class Rest:
        def __init__(self):
            self.limits = []

        def klines(self, symbol, interval, limit, end_ms=None):
            self.limits.append((interval, limit))
            stop = (end_ms if end_ms is not None else T0) // MIN * MIN
            return [[t, "1", "2", "0.5", "1.5", "3", t + MIN - 1] for t in range(stop - limit * MIN, stop, MIN)]

    rest = Rest()
    provider = SD.BinanceProvider(rest=rest, clock=lambda: T0 / 1000)
    small = provider.request("BTCUSDT", parse_timeframe("1"), parent_tickerid="BINANCE:BTCUSDT", parent_seconds=900,
                             knowable=False, until_ms=None, chart_end_ms=None)
    large = provider.request("BTCUSDT", parse_timeframe("1"), parent_tickerid="BINANCE:BTCUSDT", parent_seconds=900,
                             knowable=False, until_ms=None, chart_end_ms=None, lower=True)
    assert small.bars.size == SD.BINANCE_FETCH_BARS and large.bars.size == SD.BINANCE_LOWER_FETCH_BARS
    assert all(interval == "1m" and limit <= 1500 for interval, limit in rest.limits)


def test_received_from_frame_keeps_only_received_bars_and_aggregates_on_the_grid():
    stamps = pd.to_datetime([T0 + k * 5 * MIN for k in range(4)], unit="ms", utc=True).as_unit("s")  # any resolution
    frame = pd.DataFrame({"timestamp": stamps, "open": [1.0, 2, 3, 4], "high": [2.0, 3, 4, 5], "low": [0.5, 1, 2, 3],
                          "close": [2.0, 3, 4, 4.5], "volume": [1.0, 1, 1, 1], "final": [True, True, True, False]})
    native = SD.received_from_frame(frame, 300)
    assert native.forming and [r[0] for r in native.rows] == [T0 + k * 5 * MIN for k in range(4)]
    ten = SD.received_from_frame(frame, 300, BarGrid(parse_timeframe("10")))
    assert [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in ten.rows] == [
        (T0, T0 + 10 * MIN, 1.0, 3.0, 0.5, 3.0), (T0 + 10 * MIN, T0 + 20 * MIN, 3.0, 5.0, 2.0, 4.5)]
    assert ten.forming
    assert SD.received_from_frame(frame.iloc[:0], 300) is None


def test_binance_received_source_leases_its_own_stream():
    class Stream:
        def snapshot(self, now):
            stamps = pd.to_datetime([T0, T0 + MIN], unit="ms", utc=True)
            return {"frame": pd.DataFrame({"timestamp": stamps, "open": [1.0, 2.0], "high": [2.0, 3.0],
                                           "low": [0.5, 1.0], "close": [1.5, 2.5], "volume": [1.0, 1.0],
                                           "final": [True, False]})}

    class Hub:
        def __init__(self):
            self.leases = []

        def lower_kline(self, session_id, symbol, interval):
            self.leases.append((session_id, symbol, interval))
            return Stream()

    hub = Hub()
    source = PR.lower_tf_received("binance", now=T0 / 1000, session_id="s1", hub=hub)
    got = source("BTCUSDT", parse_timeframe("1"))
    assert hub.leases == [("s1", "BTCUSDT", "1m")] and got.forming and len(got.rows) == 2
    source("BTCUSDT", parse_timeframe("10"))                                  # custom interval: from the 5m stream
    assert hub.leases[-1] == ("s1", "BTCUSDT", "5m")
    assert source("XAUUSDm", parse_timeframe("1")) is None                     # never another family's symbol


def test_exness_received_source_reads_the_mt5_snapshot(tmp_path):
    folder = tmp_path / "Common" / "Files"
    now = 1_790_277_720.0                                                       # 12 minutes into an M15 bar
    SyntheticFeed(folder, "XAUUSDm").write(now)
    source = PR.lower_tf_received("exness", now=now, books={}, folder=folder)
    got = source("XAUUSDm", parse_timeframe("15"))
    assert got is not None and got.forming and got.rows[-1][0] == int(now // 900 * 900) * 1000
    assert source("XAUUSDm", parse_timeframe("5")) is None                      # no M5 feed: nothing received


def test_the_receiving_provider_delegates_to_the_family_provider():
    inner = SD.DatasetProvider("exness")
    wrapped = SD.provider_for("exness", received=lambda symbol, tf: ReceivedBars([], False))
    assert wrapped.family == "exness" and wrapped.received("XAUUSDm", parse_timeframe("15")).rows == []
    assert SD.provider_for("exness").__class__ is inner.__class__


@pytest.mark.parametrize("body", [
    'plot(request.security(syminfo.tickerid, "60", request.security_lower_tf(syminfo.tickerid, "1", close).size()))',
    'f() => request.security_lower_tf(syminfo.tickerid, "1", close).size()\n'
    'plot(request.security(syminfo.tickerid, "60", f()))',
    'a = request.security_lower_tf(syminfo.tickerid, "1", request.security_lower_tf(syminfo.tickerid, "1", close))\n'
    'plot(0)',
])
def test_lower_timeframe_arrays_stay_out_of_requested_expressions(body):
    result = compile_script('//@version=6\nindicator("t")\n' + body + "\n")
    assert not result.ok


def test_a_literal_cross_family_symbol_is_refused_before_running():
    from ui.tradingview_mode.component.pine_bridge import _literal_problem

    result = compile_script('//@version=6\nindicator("t")\na = request.security_lower_tf("BINANCE:BTCUSDT", "15", '
                            'close)\nplot(a.size())\n')
    problem = _literal_problem(result, SD.DatasetProvider("exness"))
    assert problem["message"].startswith("Line 3: request.security_lower_tf(): ") and \
        "Requests across data sources are not allowed" in problem["message"]


def test_frozen_a4_oracle_scripts_are_byte_identical():
    evidence = (PARITY / "P22_LOWER_TF_RESEARCH.md").read_text()
    for name in ("manual/m06_live_lower_tf.pine", "quick/q7_lower_tf_straddle.pine"):
        digest = hashlib.sha256((PARITY / name).read_bytes()).hexdigest()
        assert f"| `{name}` |" in evidence and f"`{digest}`" in evidence, name

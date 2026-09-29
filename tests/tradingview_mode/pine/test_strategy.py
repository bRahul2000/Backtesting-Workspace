"""P3.1 strategy engine: the TradingView-style broker emulator on hand-made OHLC bars, so each documented rule of the
manual ("Strategies" page; parity/P31_STRATEGY_RESEARCH.md) is checked exactly. Engine policies are named as such."""
import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.component import protocol
from ui.tradingview_mode.pine import PineExecution, compile_script, run_script
from ui.tradingview_mode.pine.engine import data_context
from ui.tradingview_mode.pine.errors import ERROR, GAP


def frame(ohlc: list[tuple], start: str = "2026-01-01", freq: str = "1D") -> pd.DataFrame:
    o, h, l, c = zip(*ohlc)
    return pd.DataFrame({"timestamp": pd.date_range(start, periods=len(ohlc), freq=freq, tz="UTC"),
                         "open": o, "high": h, "low": l, "close": c, "volume": [1.0] * len(ohlc)})


def flat(n: int, price: float = 100.0) -> list[tuple]:
    return [(price, price + 1, price - 1, price)] * n


def ctx(bars, mintick=0.01, forming=False):
    return data_context(frame(bars), timeframe_seconds=86_400, ticker="T", tickerid="X:T", mintick=mintick,
                        forming_last=forming)


def strategy(body: str, decl: str = "", version: int = 6) -> str:
    return f'//@version={version}\nstrategy("t", overlay=true{decl})\n' + body.strip("\n") + "\n"


def run(body: str, bars, decl: str = "", version: int = 6, mintick: float = 0.01):
    result = compile_script(strategy(body, decl, version))
    assert result.ok, [d.text() for d in result.diagnostics]
    execution = PineExecution(result.program, {})
    out = run_script(execution, ctx(bars, mintick), ("t",), "t")
    assert out.error is None, out.error
    return execution.runtime.strategy, out


def closed(broker):
    return [(t.entry_id, t.direction, t.entry_bar, round(t.entry_price, 6), t.exit_id, t.exit_bar,
             round(t.exit_price, 6), round(t.qty, 6)) for t in broker.state.closed]


def plots(out) -> dict:
    return {o["title"]: [p["value"] for p in o["data"]] for o in out.outputs if o["kind"] == "plot"}


# ---- market orders, timing, reversal, pyramiding (DOC) ---------------------------------------------------------------

def test_market_orders_fill_at_the_next_bar_open():
    bars = flat(2) + [(101, 103, 99, 102), (105, 106, 104, 105), (110, 111, 109, 110)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
if bar_index == 3
    strategy.close_all()
""", bars)
    assert closed(broker) == [("L", 1, 2, 101.0, "Close position order", 4, 110.0, 1.0)]


def test_process_orders_on_close_fills_on_the_same_closing_tick():
    bars = flat(2) + [(101, 103, 99, 102), (105, 106, 104, 105), (110, 111, 109, 110)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
if bar_index == 3
    strategy.close("L")
""", bars, decl=", process_orders_on_close=true")
    assert closed(broker) == [("L", 1, 1, 100.0, "Close entry(s) order L", 3, 105.0, 1.0)]   # OBS q12 S13 name


def test_position_state_is_visible_on_the_fill_bar_close_and_through_history():
    bars = flat(1) + [(100, 101, 99, 100), (102, 103, 101, 102), (103, 104, 102, 103)]
    _, out = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, qty = 2)
plot(strategy.position_size, "size")
plot(strategy.position_size[1], "prev")
plot(strategy.position_avg_price, "avg")
plot(strategy.opentrades, "open")
""", bars)
    p = plots(out)
    assert p["size"] == [0, 0, 2, 2] and p["prev"] == [None, 0, 0, 2]
    assert p["avg"] == [None, None, 102.0, 102.0] and p["open"] == [0, 0, 1, 1]


def test_entry_reverses_by_adding_the_open_position_size():
    bars = flat(1) + [(100, 101, 99, 100)] * 2 + [(90, 91, 89, 90)] * 3
    broker, out = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long, qty = 15)
if bar_index == 3
    strategy.entry("sell", strategy.short, qty = 5)
plot(strategy.position_size, "size")
""", bars)
    assert plots(out)["size"][-1] == -5
    reversal = [f for f in broker.state.fills if f.kind == "reversal"][0]
    assert (reversal.qty, reversal.price, reversal.position_after) == (20, 90.0, -5)
    assert closed(broker) == [("buy", 1, 2, 100.0, "sell", 4, 90.0, 15.0)]


def test_pyramiding_limits_open_trades_from_strategy_entry():
    bars = flat(12)
    source = """
if bar_index >= 1 and bar_index <= 4
    strategy.entry("E", strategy.long)
plot(strategy.opentrades, "open")
"""
    _, default = run(source, bars)
    _, four = run(source, bars, decl=", pyramiding=4")
    assert plots(default)["open"][-1] == 1 and plots(four)["open"][-1] == 4


def test_strategy_order_nets_positions_without_reversing():
    bars = flat(8)
    _, out = run("""
if bar_index == 1
    strategy.order("buy", strategy.long, qty = 15)
if bar_index >= 2 and bar_index <= 4
    strategy.order("sell" + str.tostring(bar_index), strategy.short, qty = 5)
plot(strategy.position_size, "size")
""", bars)
    assert plots(out)["size"] == [0, 0, 15, 10, 5, 0, 0, 0]


# ---- limit, stop, stop-limit entries (DOC) -------------------------------------------------------------------------

def test_limit_entry_waits_for_its_price_and_fills_at_it_or_better():
    bars = flat(2) + [(100, 100.5, 99.5, 100), (100, 100.5, 97, 98), (95, 96, 94, 95), (95, 96, 94, 95)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, limit = 98.5)
if bar_index == 4
    strategy.close_all()
""", bars)
    assert broker.state.closed[0].entry_bar == 3 and broker.state.closed[0].entry_price == 98.5
    gap = flat(2) + [(97, 97.5, 96.5, 97)] + flat(2, 97)          # the next open gaps below the limit: fill at the open
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, limit = 98.5)
""", gap)
    assert broker.state.trades[0].entry_price == 97


def test_limit_worse_than_market_fills_on_the_next_tick():
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, limit = close + 8)
""", flat(2) + [(100.2, 101, 99, 100)] * 2)
    assert (broker.state.trades[0].entry_bar, broker.state.trades[0].entry_price) == (2, 100.2)


def test_stop_entry_triggers_at_its_level_or_at_a_gap_open():
    bars = flat(2) + [(100, 101, 99.5, 100.5), (100.5, 104, 100, 103)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, stop = 102)
""", bars)
    assert (broker.state.trades[0].entry_bar, broker.state.trades[0].entry_price) == (3, 102)
    better = flat(2) + [(100, 101, 99, 100)] * 2                   # stop below the market: activates immediately
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, stop = close - 5)
""", better)
    assert (broker.state.trades[0].entry_bar, broker.state.trades[0].entry_price) == (2, 100)


def test_stop_limit_activates_the_limit_only_after_the_stop():
    # bar 2 touches the limit (99) before the stop (102) is reached: no fill; bar 3 reaches the stop, bar 4 the limit
    bars = flat(2) + [(100, 100.5, 98.5, 100), (100, 102.5, 100, 102), (101, 101.5, 98.8, 99), (99, 99.5, 98.5, 99)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, stop = 102, limit = 99)
""", bars)
    assert (broker.state.trades[0].entry_bar, broker.state.trades[0].entry_price) == (4, 99)


def test_same_id_modifies_the_pending_order():
    bars = flat(2) + [(100, 100.5, 97.6, 99)] + [(99, 99.5, 96, 97)] * 2
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long, limit = 97.5)
if bar_index == 2
    strategy.entry("L", strategy.long, limit = 96.5)
""", bars)
    assert len(broker.state.trades) == 1 and broker.state.trades[0].entry_price == 96.5


def test_cancel_removes_pending_orders_but_not_a_market_order_placed_earlier():
    bars = flat(6)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long, limit = 50)
if bar_index == 2
    strategy.cancel("buy")
if bar_index == 3
    strategy.entry("m", strategy.long)
if bar_index == 4
    strategy.cancel_all()
""", bars)
    assert [t.entry_id for t in broker.state.trades] == ["m"] and broker.state.orders == []


# ---- strategy.exit brackets, reservation, binding, FIFO (DOC) -----------------------------------------------------

@pytest.mark.parametrize("bar, expected", [
    ((100, 101, 94, 95), ("limit", 100.5)),       # open closer to the high: open -> high -> low, the take-profit first
    ((100, 106, 99, 105), ("stop", 99.5)),        # open closer to the low: open -> low -> high, the stop first
])
def test_bracket_on_the_entry_bar_follows_the_intrabar_path(bar, expected):
    broker, _ = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long)
    strategy.exit("x", "buy", profit = 50, loss = 50)
""", flat(2) + [bar, (95, 96, 94, 95)])
    trade = broker.state.closed[0]
    assert (trade.exit_kind, trade.exit_price, trade.exit_bar) == (*expected, 2)


def test_exit_reservation_in_call_order():
    bars = flat(2) + [(100, 100.5, 98, 98.5)] + flat(2, 98.5)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long, 20)
    strategy.exit("limit", limit = 110, qty = 19)
    strategy.exit("stop", stop = 99, qty = 20)
plot(strategy.position_size, "size")
""", bars)
    assert [(t.exit_id, t.qty) for t in broker.state.closed] == [("stop", 1)]
    assert broker.position() == 19


def test_unknown_from_entry_creates_no_exit_and_exits_without_it_persist():
    bars = flat(2) + [(100, 101, 90, 91)] + [(91, 92, 80, 81)] * 3
    broker, _ = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long)
    strategy.exit("x", "buy2", stop = 95)
""", bars)
    assert broker.state.closed == []
    broker, _ = run("""
if bar_index == 1
    strategy.exit("x", stop = 50)
if bar_index == 2
    strategy.entry("later", strategy.long)
""", flat(3) + [(100, 101, 40, 45)] * 2)
    assert [(t.entry_id, t.exit_id, t.exit_price) for t in broker.state.closed] == [("later", "x", 50)]


def test_exits_close_trades_first_in_first_out():
    bars = flat(1) + [(100, 101, 99, 100)] * 3 + [(100, 100.5, 99.5, 100)] * 3
    broker, _ = run("""
if bar_index == 1
    strategy.entry("Buy1", strategy.long, 5)
if bar_index == 2
    strategy.entry("Buy2", strategy.long, 10)
if bar_index == 3
    strategy.close("Buy2")
""", bars, decl=", pyramiding=2")
    assert [(t.entry_id, t.qty) for t in broker.state.closed] == [("Buy1", 5), ("Buy2", 5)]
    assert [(t.entry_id, t.qty) for t in broker.state.trades] == [("Buy2", 5)]


def test_v5_prefers_absolute_levels_and_v6_the_first_reached():
    body = """
if bar_index == 1
    strategy.entry("buy", strategy.long)
    strategy.exit("x", "buy", profit = 100, limit = 101.5)
"""
    bars = flat(2) + [(100, 103, 99.8, 102)] + flat(2, 102)
    v5, _ = run(body, bars, version=5)
    v6, _ = run(body, bars)
    assert v5.state.closed[0].exit_price == 101.5 and v6.state.closed[0].exit_price == 101.0


def test_partial_exits_split_trades():
    bars = flat(2) + [(100, 103, 99.8, 102)] + flat(2, 102)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("buy", strategy.long, 2)
    strategy.exit("tp1", "buy", qty = 1, profit = 100)
    strategy.exit("tp2", "buy", qty = 3, profit = 200)
""", bars)
    assert [(t.exit_id, t.qty, t.exit_price) for t in broker.state.closed] == [("tp1", 1, 101.0), ("tp2", 1, 102.0)]


# ---- trailing stops (DOC activation / offset; path tracking: POLICY pending oracle) ---------------------------------

def test_long_trailing_stop_activates_and_follows_the_best_price():
    bars = flat(2) + [(100, 101, 99.5, 100.8), (100.8, 104, 100.5, 103.8), (103.8, 104.2, 101, 101.5)]
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
strategy.exit("T", trail_points = 150, trail_offset = 300)
""", bars)
    trade = broker.state.closed[0]           # activation 101.5 on bar 3, best 104.2 on bar 4, stop 101.2
    assert (trade.exit_kind, trade.exit_bar, trade.exit_price) == ("trail", 4, 101.2)


def test_short_trailing_stop_and_same_bar_activation_and_stop_out():
    # open closer to the low: open -> low (activation, best 97) -> high 99.5 crosses the stop 98 on the entry bar
    bars = flat(2) + [(100, 100.2, 97, 99)] + flat(2, 99)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("S", strategy.short)
strategy.exit("T", trail_points = 100, trail_offset = 100)
""", bars)
    trade = broker.state.closed[0]
    assert (trade.exit_kind, trade.exit_bar, trade.exit_price) == ("trail", 2, 98.0)


def test_trailing_gap_through_the_stop_fills_at_the_open():
    bars = flat(2) + [(100, 105, 99.9, 104.9), (95, 96, 94, 95)] + flat(1, 95)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
strategy.exit("T", trail_points = 100, trail_offset = 100)
""", bars)
    # same-bar path open -> low -> high -> close: stop at 104 after the high 105; close 104.9 keeps it; bar 3 gaps to 95
    assert (broker.state.closed[0].exit_bar, broker.state.closed[0].exit_price) == (3, 95.0)


# ---- sizing, commission, slippage (DOC formulas; order classes for slippage: POLICY) --------------------------------

def test_default_quantity_types():
    source = """
if bar_index == 1
    strategy.entry("L", strategy.long)
plot(strategy.position_size, "size")
"""
    bars = flat(2, 50.0) + [(50, 51, 49, 50)] * 2
    _, fixed = run(source, bars, decl=", default_qty_value=3")
    _, cash = run(source, bars, decl=", default_qty_type=strategy.cash, default_qty_value=1000")
    _, pct = run(source, bars, decl=", initial_capital=10000, default_qty_type=strategy.percent_of_equity, "
                                    "default_qty_value=10")
    assert plots(fixed)["size"][-1] == 3 and plots(cash)["size"][-1] == 20 and plots(pct)["size"][-1] == 20


@pytest.mark.parametrize("decl, expected", [
    (", commission_type=strategy.commission.percent, commission_value=1", 10 - 1.0 - 1.1),
    (", commission_type=strategy.commission.cash_per_contract, commission_value=0.5", 10 - 0.5 - 0.5),
    (", commission_type=strategy.commission.cash_per_order, commission_value=2", 10 - 2 - 2),
])
def test_commission_types(decl, expected):
    bars = flat(1) + [(100, 101, 99, 100)] * 2 + [(110, 111, 109, 110)] * 2
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
if bar_index == 2
    strategy.close_all()
""", bars, decl=decl)
    assert broker.state.closed[0].profit == pytest.approx(expected)


def test_slippage_moves_market_and_stop_fills_against_the_order_not_limits():
    bars = flat(2) + [(100, 103, 99.5, 102), (102, 102.5, 101, 102)] + flat(2, 102)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
    strategy.exit("x", "L", limit = 102.5)
if bar_index == 3
    strategy.entry("S", strategy.short, stop = 101.5)
""", bars, decl=", slippage=10")
    assert broker.state.closed[0].entry_price == pytest.approx(100.1)        # market: +10 ticks
    assert broker.state.closed[0].exit_price == pytest.approx(102.5)         # limit: no slippage
    assert broker.state.trades[0].entry_price == pytest.approx(101.4)        # stop: -10 ticks for a sell


def test_state_counters_and_equity():
    bars = flat(1) + [(100, 101, 99, 100)] * 2 + [(110, 111, 109, 110)] * 2 + [(105, 106, 104, 105)] * 2
    _, out = run("""
if bar_index == 1
    strategy.entry("A", strategy.long)
if bar_index == 2
    strategy.close_all()
if bar_index == 3
    strategy.entry("B", strategy.long)
if bar_index == 4
    strategy.close_all()
plot(strategy.netprofit, "net")
plot(strategy.wintrades, "wins")
plot(strategy.losstrades, "losses")
plot(strategy.closedtrades, "closed")
plot(strategy.equity, "equity")
plot(strategy.grossprofit, "gp")
plot(strategy.grossloss, "gl")
""", bars, decl=", initial_capital=1000")
    p = {k: v[-1] for k, v in plots(out).items()}
    assert p == {"net": 5.0, "wins": 1, "losses": 1, "closed": 2, "equity": 1005.0, "gp": 10.0, "gl": 5.0}


def test_individual_trade_functions():
    bars = flat(1) + [(100, 101, 99, 100)] * 2 + [(110, 111, 109, 110)] * 2
    _, out = run("""
if bar_index == 1
    strategy.entry("A", strategy.long, 2, comment = "go")
if bar_index == 2
    strategy.close_all(comment = "out")
plot(strategy.closedtrades > 0 ? strategy.closedtrades.profit(0) : na, "profit")
plot(strategy.closedtrades > 0 ? strategy.closedtrades.exit_price(0) : na, "exit")
plot(strategy.closedtrades > 0 ? strategy.closedtrades.entry_bar_index(0) : na, "ebar")
plot(strategy.closedtrades > 0 ? strategy.closedtrades.size(0) : na, "size")
plot(strategy.opentrades > 0 ? strategy.opentrades.entry_price(0) : na, "openEntry")
""", bars)
    p = plots(out)
    assert p["profit"][-1] == 20 and p["exit"][-1] == 110 and p["ebar"][-1] == 2 and p["size"][-1] == 2
    assert p["openEntry"][2] == 100


def test_margin_v6_default_rejects_entries_larger_than_the_funds_policy():
    bars = flat(1) + [(100, 101, 99, 100)] * 3
    source = """
if bar_index == 1
    strategy.entry("L", strategy.long, 50)
plot(strategy.position_size, "size")
"""
    _, v6 = run(source, bars, decl=", initial_capital=1000")
    _, v6_zero = run(source, bars, decl=", initial_capital=1000, margin_long=0")
    _, v5 = run(source, bars, decl=", initial_capital=1000", version=5)
    assert plots(v6)["size"][-1] == 0 and plots(v6_zero)["size"][-1] == 50 and plots(v5)["size"][-1] == 50


# ---- declaration, analyzer, request restrictions -----------------------------------------------------------------------

def test_declaration_settings_and_unsupported_arguments():
    result = compile_script(strategy("plot(close)", decl=", initial_capital=5000, pyramiding=3, slippage=2, "
                                                        "commission_type=strategy.commission.cash_per_order, "
                                                        "commission_value=1.5, default_qty_type=strategy.cash, "
                                                        "default_qty_value=250"))
    assert result.ok and result.meta["strategy"]["pyramiding"] == 3
    assert result.meta["strategy"]["commission_type"] == "cash_per_order"
    for arg in ("calc_on_every_tick=true", "calc_on_order_fills=true", "use_bar_magnifier=true",
                'close_entries_rule="ANY"', "currency=currency.EUR"):
        diags = compile_script(strategy("plot(close)", decl=", " + arg)).diagnostics
        assert any(d.kind == GAP and d.feature == "strategy" for d in diags), arg


def test_strategy_namespace_only_in_strategies_and_when_removed_in_v6():
    diags = compile_script('//@version=6\nindicator("i")\nstrategy.entry("L", strategy.long)\nplot(close)\n').diagnostics
    assert [d.message for d in diags if d.kind == ERROR] == [
        "`strategy.entry()` can only be used in scripts declared with `strategy()`."]
    ok = compile_script(strategy('strategy.entry("L", strategy.long, when = close > open)\nplot(close)', version=5))
    assert ok.ok


@pytest.mark.parametrize("body", [
    'x = request.security(syminfo.tickerid, "1D", strategy.position_size)\nplot(x)',
    'f() =>\n    strategy.entry("L", strategy.long)\n    close\nx = request.security(syminfo.tickerid, "1D", f())\nplot(x)',
])
def test_strategy_state_and_commands_never_run_in_requested_contexts(body):
    result = compile_script(strategy(body))
    assert any(d.kind == GAP and d.feature == "request" for d in result.diagnostics), [d.text() for d in result.diagnostics]


# ---- determinism, Replay (knowable at cursor), live paper -------------------------------------------------------------

DONCHIAN_LIKE = """
upper = ta.highest(high, 5)
lower = ta.lowest(low, 5)
if close >= upper[1]
    strategy.entry("Long", strategy.long)
if close <= lower[1]
    strategy.entry("Short", strategy.short)
strategy.exit("Trail", trail_points = 150, trail_offset = 300)
plot(strategy.position_size, "size")
"""


def walk(n=120, seed=7):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1.2, n))
    open_ = np.r_[close[0], close[:-1]] + rng.normal(0, 0.2, n)
    high = np.maximum(open_, close) + rng.uniform(0, 1.5, n)
    low = np.minimum(open_, close) - rng.uniform(0, 1.5, n)
    return list(zip(open_.round(2), high.round(2), low.round(2), close.round(2)))


def ledger(broker):
    return [(t.entry_id, t.entry_bar, t.entry_price, t.exit_id, t.exit_bar, t.exit_price, t.qty, t.profit)
            for t in broker.state.closed]


def test_historical_runs_are_deterministic():
    a, _ = run(DONCHIAN_LIKE, walk())
    b, _ = run(DONCHIAN_LIKE, walk())
    assert ledger(a) == ledger(b) and len(ledger(a)) > 5


def test_replay_cursor_never_sees_future_bars_and_incremental_equals_fresh():
    bars = walk()
    program = compile_script(strategy(DONCHIAN_LIKE)).program
    incremental = PineExecution(program, {})
    for cursor in range(30, len(bars) + 1, 7):
        run_script(incremental, ctx(bars[:cursor]), ("replay",), "t")
        fresh = PineExecution(program, {})
        run_script(fresh, ctx(bars[:cursor]), ("replay",), "t")
        broker = incremental.runtime.strategy
        assert ledger(broker) == ledger(fresh.runtime.strategy)
        assert all(t.exit_bar < cursor and t.entry_bar < cursor for t in broker.state.closed)
        assert all(f.bar < cursor for f in broker.state.fills)


def test_live_paper_forming_bar_runs_the_broker_only_and_rolls_back_each_tick():
    bars = flat(3) + [(100, 101, 99, 100)]
    program = compile_script(strategy("""
if bar_index == 2
    strategy.entry("L", strategy.long, stop = 102)
plot(strategy.position_size, "size")
""")).program
    execution = PineExecution(program, {})
    run_script(execution, ctx(bars, forming=True), ("live",), "t")      # forming bar 3: no stop yet
    assert execution.runtime.strategy.state.trades == []
    ticked = bars[:3] + [(100, 103, 99, 102.5)]                             # the forming bar reaches 102
    out = run_script(execution, ctx(ticked, forming=True), ("live",), "t")
    broker = execution.runtime.strategy
    assert [(t.entry_bar, t.entry_price) for t in broker.state.trades] == [(3, 102)]
    assert plots(out)["size"][-1] is None                                  # the script waits for the bar's close
    back = bars[:3] + [(100, 101.5, 99, 101)]                               # a new tick without the stop
    run_script(execution, ctx(back, forming=True), ("live",), "t")
    assert execution.runtime.strategy.state.trades == []                   # rolled back to the committed state
    closed_bar = back + [(101, 101.2, 100.8, 101)]                          # the bar closes, a new one forms
    fresh = PineExecution(program, {})
    run_script(execution, ctx(closed_bar, forming=True), ("live",), "t")
    run_script(fresh, ctx(closed_bar, forming=True), ("live",), "t")
    assert ledger(execution.runtime.strategy) == ledger(fresh.runtime.strategy)


# ---- payload -----------------------------------------------------------------------------------------------------------

def test_strategy_report_payload_validates_and_is_simulation_only():
    broker, out = run(DONCHIAN_LIKE, walk())
    report = out.strategy
    assert report["metrics"]["total_closed_trades"] == len(broker.state.closed)
    assert report["metrics"]["net_profit"] == pytest.approx(sum(t.profit for t in broker.state.closed))
    assert {"trades", "fills", "equity", "metrics", "settings", "pending_orders", "fill_count", "fills_reported",
            "calc_range"} == set(report)
    assert report["fill_count"] == report["fills_reported"] == len(broker.state.fills)
    times = {int(t.timestamp()) for t in pd.date_range("2026-01-01", periods=120, freq="1D", tz="UTC")}
    protocol._validate_strategy({"strategy": report}, times)
    forbidden = ("broker", "account", "ticket", "webhook", "send", "api_key")
    assert not any(word in str(sorted(report["settings"])) for word in forbidden)


# ---- parity tooling and frozen sources --------------------------------------------------------------------------------

import hashlib
from pathlib import Path

from ui.tradingview_mode.pine.parity import strategy_parity as SP

STRATEGIES = Path("ui/tradingview_mode/pine/parity/strategies")
FROZEN = {
    "s01_donchian_trailing_v5.pine": "009965e7becc2ffd27fe371cb1950c850582d9972ba4975b33c7e0945397bb99",
    "q12_strategy_orders_v6.pine": "27369559a27873c47998262bbb8079547a906d1dc6c470e9a2898eb4db027947",
    "q13_strategy_costs_v6.pine": "a6b72b2b486adaa3ec9fc01ed9a3573c85692b3eebc1f5f322f69058035415ca",
    "q14_strategy_margin_close_v6.pine": "2ce88cb27cd7f0a5f446dfe8641ce03f3d26e38a882a86a5d7e90c43261b7f0f",
    "data/BINANCE_BTCUSDT.P_1D.csv": "61a51be41596f75da8075130271eb9fb8f8ddcbfed08197d864d20aecc066b82",
}


def test_tradingview_trade_list_parser_reads_both_header_generations_and_detects_the_timezone(tmp_path):
    bars = frame(flat(1) + [(100, 101, 99, 100)] * 2 + [(110, 111, 109, 110)] * 2)
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
if bar_index == 2
    strategy.close_all()
""", flat(1) + [(100, 101, 99, 100)] * 2 + [(110, 111, 109, 110)] * 2)
    old = tmp_path / "old.csv"
    old.write_text("Trade #,Type,Signal,Date/Time,Price USDT,Contracts,Profit USDT,Profit %,Cumulative profit USDT\n"
                   "1,Exit long,Close position order,2026-01-04 05:30,110,1,10,10,10\n"
                   "1,Entry long,L,2026-01-03 05:30,100,1,10,10,10\n")
    new = tmp_path / "new.csv"
    new.write_text("Trade #,Type,Date and time,Signal,Price USDT,Size (qty),Size (value),Net P&L USDT,Net P&L %\n"
                   "1,Entry long,2026-01-03 00:00,L,100,1,100,10,10\n"
                   "1,Exit long,2026-01-04 00:00,Close position order,110,1,110,10,10\n")
    for path, offset in ((old, 330), (new, 0)):
        report = SP.compare(SP.parse_tradingview_trades(path), broker, bars, mintick=0.01)
        assert report.first_divergence is None and report.matched == 1, report.text()
        assert report.offset.total_seconds() == offset * 60
    wrong = tmp_path / "wrong.csv"
    wrong.write_text(new.read_text().replace(",110,1,110,10,10", ",110.5,1,110,10.5,10"))
    report = SP.compare(SP.parse_tradingview_trades(wrong), broker, bars, mintick=0.01)
    assert report.first_divergence == 1 and {m[1] for m in report.mismatches} == {"exit price", "profit"}


def test_frozen_strategy_parity_sources_and_bars():
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()           # noqa: E731
    for name, expected in FROZEN.items():
        assert digest(STRATEGIES / name) == expected, name


def test_donchian_acceptance_script_runs_unchanged_on_the_frozen_bars():
    frame_ = SP.load_bars(STRATEGIES / "data" / "BINANCE_BTCUSDT.P_1D.csv")
    source = (STRATEGIES / "s01_donchian_trailing_v5.pine").read_text()
    first = SP.run_strategy(source, frame_, mintick=0.1, timeframe_seconds=86_400)
    second = SP.run_strategy(source, frame_, mintick=0.1, timeframe_seconds=86_400)
    assert ledger(first) == ledger(second) and len(first.state.closed) > 100
    assert {t.entry_id for t in first.state.closed} == {"Long", "Short"}
    assert {t.exit_id for t in first.state.closed} <= {"Trail", "Long", "Short"}


# ---- Pine Logs evidence path (TradingView Basic: no CSV export) ----------------------------------------------------------

LOGGED = {
    "q12_strategy_orders_v6_logged.pine": ("q12_strategy_orders_v6.pine", "Q12"),
    "q13_strategy_costs_v6_logged.pine": ("q13_strategy_costs_v6.pine", "Q13"),
    "q14_strategy_margin_close_v6_logged.pine": ("q14_strategy_margin_close_v6.pine", "Q14"),
    "s01_donchian_trailing_v5_logged.pine": ("s01_donchian_trailing_v5.pine", "DONCHIAN"),
}
LOGGED_HASHES = {
    "q12_strategy_orders_v6_logged.pine": "073277f6372bf0eda0edd4039f66ce3f0bdc423eb1df0857e56ee0b360910de4",
    "q13_strategy_costs_v6_logged.pine": "6ca0d106e58b92732223208397402c847345756270f936000673661415639d25",
    "q14_strategy_margin_close_v6_logged.pine": "d7499e06f92728144707de1faa0fd29fa593eb74b55632b381be661ec7c7319e",
    "s01_donchian_trailing_v5_logged.pine": "6e279756db6671eebc85504579abe1102767fdf88c512f06f03483664fb65cba",
}


def test_pine_log_text_and_csv_give_the_same_trade_records(tmp_path):
    logs = ("[2026-09-29T10:00:00.000+05:30]: some other log line\n"
            "2026-09-28 00:00:00 ZF|Q12|BEGIN|closed=1|open=1|last_bar_time=1\n"
            "[2026-09-29T10:00:00.000+05:30]: ZF|Q12|TRADE|0|entry_id=L|size=2|entry_time=1767398400000|entry_bar=2"
            "|entry_price=100|exit_id=Close position order|exit_time=1767484800000|exit_bar=3|exit_price=110"
            "|profit=20|commission=0|runup=11|drawdown=1\n"
            "ZF|Q12|OPEN|0|entry_id=S|size=-1|entry_time=1767571200000|entry_bar=4|entry_price=105\n"
            "ZF|Q13|TRADE|0|entry_id=other|size=1|entry_time=1|exit_time=2|entry_price=1|exit_price=1|profit=0\n"
            "ZF|Q12|SUMMARY|initial=1000|net=20|closed=1\n")
    trades, summary = SP.parse_pine_logs(logs, "Q12")
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("Trade #,Type,Date and time,Signal,Price USDT,Size (qty),Net P&L USDT\n"
                        "1,Entry long,2026-01-03 00:00,L,100,2,20\n1,Exit long,2026-01-04 00:00,Close position order,110,2,20\n"
                        "2,Entry short,2026-01-05 00:00,S,105,1,\n2,Exit short,2026-01-06 00:00,Open,106,1,-1\n")
    from_csv = SP.parse_tradingview_trades(csv_path)
    key = lambda t: (t.number, t.direction, t.entry_signal, t.entry_time, t.entry_price, t.qty)     # noqa: E731
    assert [key(t) for t in trades] == [key(t) for t in from_csv]
    assert (trades[0].exit_signal, trades[0].exit_time, trades[0].exit_price, trades[0].profit) == \
        (from_csv[0].exit_signal, from_csv[0].exit_time, from_csv[0].exit_price, from_csv[0].profit)
    assert trades[1].open and summary == {"initial": "1000", "net": "20", "closed": "1"}
    text_path = tmp_path / "logs.txt"
    text_path.write_text(logs.replace("ZF|Q13", "XX|Q13"))
    assert [key(t) for t in SP.parse_trades(text_path)] == [key(t) for t in trades]


@pytest.mark.parametrize("logged", sorted(LOGGED))
def test_logged_oracles_add_read_only_observation_and_round_trip_through_the_parser(logged):
    original, tag = LOGGED[logged]
    source = (STRATEGIES / logged).read_bytes()
    assert source.startswith((STRATEGIES / original).read_bytes())          # the frozen script, byte for byte
    assert hashlib.sha256(source).hexdigest() == LOGGED_HASHES[logged]
    bars = SP.load_bars(STRATEGIES / "data" / "BINANCE_BTCUSDT.P_1D.csv")
    result = compile_script(source.decode())
    execution = PineExecution(result.program, {})
    data = data_context(bars, timeframe_seconds=86_400, ticker="BTCUSDT.P", tickerid="BINANCE:BTCUSDT.P",
                        mintick=0.1, currency="USDT")
    out = run_script(execution, data, ("parity",), "p")
    assert out.error is None
    text = "\n".join(message for _, _, message in execution.runtime.logs)
    trades, summary = SP.parse_pine_logs(text, tag)
    broker = execution.runtime.strategy
    report = SP.compare(trades, broker, bars, mintick=0.1)
    assert report.first_divergence is None and report.matched == len(broker.state.closed), report.text()
    assert int(summary["closed"]) == len(broker.state.closed) and len(execution.runtime.logs) < 1000
    plain = SP.run_strategy((STRATEGIES / original).read_text(), bars, mintick=0.1, timeframe_seconds=86_400)
    assert ledger(plain) == ledger(broker)                                     # instrumentation changes no trade


# ---- rules settled by the real TradingView logs (q12 / q13 / q14 / Donchian) --------------------------------------------

EVIDENCE = STRATEGIES / "evidence"
EVIDENCE_HASHES = {
    "tradingview_q12_pine_logs.csv": "5b1f76be89e0dd4c953ec8ff16056b893ab43f5c8d568d7319e027c622daf4c5",
    "tradingview_q13_pine_logs.csv": "fc334a00efc0676e54f48f9ae7ec2feb3de1b9f34ff1ae755b1ed45f9416bf69",
    "tradingview_q14_pine_logs.csv": "8a424cf7784ea973947c717981a0be8e9becaef85f4279f5da33bda09a498fb4",
    "tradingview_donchian_pine_logs.csv": "ca4805c1951c721a61c11439072b1e573acfe42e099446e2cf9c467cea4c589b",
}


def test_market_entries_beyond_pyramiding_are_not_filled_obs_q12_s8():
    broker, _ = run("""
if bar_index == 1
    strategy.entry("a", strategy.long)
    strategy.entry("b", strategy.long)
""", flat(4))
    assert [t.entry_id for t in broker.state.trades] == ["a"]


def test_close_order_names_obs_q12():
    broker, _ = run("""
if bar_index == 1
    strategy.entry("A", strategy.long)
if bar_index == 2
    strategy.close("A")
if bar_index == 3
    strategy.entry("B", strategy.long)
if bar_index == 4
    strategy.close_all()
""", flat(7))
    assert [t.exit_id for t in broker.state.closed] == ["Close entry(s) order A", "Close position order"]


def test_cash_size_uses_the_fill_price_with_slippage_truncated_to_six_decimals_obs_q13():
    broker, _ = run("""
if bar_index == 1
    strategy.entry("C", strategy.long)
""", flat(2, 105637.9) + [(105637.9, 105700, 105600, 105650)] * 2,
        decl=", default_qty_type=strategy.cash, default_qty_value=10000, slippage=20", mintick=0.1)
    trade = broker.state.trades[0]
    assert trade.entry_price == pytest.approx(105639.9) and trade.qty == pytest.approx(0.094661)


def test_trade_excursions_follow_the_path_until_the_exit_net_of_entry_commission_obs_q12_q13():
    # the take-profit fills on the way up: the run-up stops at the exit; the exit's slippage counts in the drawdown
    broker, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
    strategy.exit("x", "L", profit = 50, loss = 500)
""", flat(2) + [(100, 100.8, 94, 95), (95, 96, 94, 95)], decl=", commission_type=strategy.commission.cash_per_order, "
                                                              "commission_value=3")
    trade = broker.state.closed[0]
    assert (trade.exit_price, trade.max_runup, trade.max_drawdown) == (100.5, 0.5 - 3, 0 + 3)
    stop, _ = run("""
if bar_index == 1
    strategy.entry("L", strategy.long)
    strategy.exit("x", "L", loss = 100)
""", flat(2) + [(100, 100.2, 98, 98.5)] + flat(1, 98.5), decl=", slippage=5")
    trade = stop.state.closed[0]
    assert trade.exit_price == pytest.approx(99.0) and trade.max_drawdown == pytest.approx(1.05)   # 100.05 - 99.00


def test_prices_are_put_on_the_tick_grid_obs_donchian():
    # 2-decimal data, tick 0.1: the market entry at the nearest tick, the trailing stop away from the market
    broker, _ = run("""
if bar_index == 1
    strategy.entry("S", strategy.short)
strategy.exit("T", trail_points = 150, trail_offset = 300)
""", flat(2, 7465.18) + [(7465.18, 7495.81, 7337.44, 7411.35)] + flat(1, 7411.35), mintick=0.1)
    trade = broker.state.closed[0]
    assert (trade.entry_price, trade.exit_price) == (7465.2, 7367.5)                     # TradingView trade 0
    assert (round(trade.max_runup, 6), round(trade.max_drawdown, 6)) == (127.8, 30.6)


def test_strategy_max_drawdown_is_measured_from_the_closed_equity_peak_obs_q14():
    broker, _ = run("""
if bar_index == 1
    strategy.entry("A", strategy.long)
if bar_index == 2
    strategy.close_all()
if bar_index == 4
    strategy.entry("B", strategy.long)
if bar_index == 6
    strategy.close_all()
""", flat(2) + [(100, 104, 99, 103), (103, 104, 102, 103)] + [(103, 103.5, 102.5, 103)] +
        [(103, 103.5, 95, 96), (96, 97, 95, 96), (97, 98, 96, 97)])
    # A: +3 (run-up 4 intrabar is ignored by the peak); B: entry 103, worst 95 -> 8 below the closed peak 1_000_003
    assert broker.state.max_drawdown == pytest.approx(8.0)


@pytest.mark.parametrize("name, script, tag", [
    ("q12", "q12_strategy_orders_v6.pine", "Q12"),
    ("q13", "q13_strategy_costs_v6.pine", "Q13"),
    ("q14", "q14_strategy_margin_close_v6.pine", "Q14"),
])
def test_oracles_match_the_real_tradingview_logs_trade_by_trade(name, script, tag):
    path = EVIDENCE / f"tradingview_{name}_pine_logs.csv"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EVIDENCE_HASHES[path.name]
    trades, summary = SP.parse_pine_logs(path.read_text(), tag)
    bars = SP.load_bars(STRATEGIES / "data" / "BINANCE_BTCUSDT.P_1D.csv")
    broker = SP.run_strategy((STRATEGIES / script).read_text(), bars, mintick=0.1, timeframe_seconds=86_400)
    report = SP.compare(trades, broker, bars, mintick=0.1)
    assert report.first_divergence is None and report.matched == len(trades), report.text()
    assert all(row["match"] for row in SP.compare_summary(summary, broker).values()), SP.compare_summary(summary, broker)


def test_donchian_acceptance_matches_tradingview_trade_by_trade():
    """244 of 246 trades identical in every field; trades #103 and #150 enter at TradingView's daily open, which is
    one tick away from the Binance kline open of the frozen bars (a data-source difference): their bars, times, exits
    and every other field match and the price difference is exactly one tick, carried into profit and excursions."""
    path = EVIDENCE / "tradingview_donchian_pine_logs.csv"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == EVIDENCE_HASHES[path.name]
    trades, summary = SP.parse_pine_logs(path.read_text(), "DONCHIAN")
    bars = SP.load_bars(STRATEGIES / "data" / "BINANCE_BTCUSDT.P_1D.csv")
    broker = SP.run_strategy((STRATEGIES / "s01_donchian_trailing_v5.pine").read_text(), bars, mintick=0.1,
                             timeframe_seconds=86_400)
    report = SP.compare(trades, broker, bars, mintick=0.1)
    assert (report.tradingview, report.engine, report.matched) == (246, 246, 244)
    assert {(n, f) for n, f, _, _ in report.mismatches} == {
        (103, "entry price"), (103, "profit"), (103, "run-up"), (103, "drawdown"),
        (150, "entry price"), (150, "profit"), (150, "run-up")}
    for number, tv_open in ((103, 19547.6), (150, 49943.5)):
        ours = broker.state.closed[number - 1]
        assert trades[number - 1].entry_price == tv_open
        assert abs(ours.entry_price - tv_open) == pytest.approx(0.1)
        assert bars["open"].iloc[ours.entry_bar] == ours.entry_price       # we fill at the Binance open itself
    rows = SP.compare_summary(summary, broker)
    assert {k for k, row in rows.items() if not row["match"]} == {"equity", "net", "gross_profit", "gross_loss"}
    assert rows["max_drawdown"]["match"] and rows["closed"]["match"] and rows["wins"]["match"]
    assert rows["net"]["tradingview"] - rows["net"]["engine"] == pytest.approx(0.2)        # the two ticks above


def test_donchian_parity_report_regenerates_byte_for_byte_from_frozen_inputs(monkeypatch):
    import json
    import urllib.request

    def offline(*args, **kwargs):
        raise AssertionError("the acceptance must not use the network")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    path = EVIDENCE / "tradingview_donchian_pine_logs.csv"
    bars = SP.load_bars(STRATEGIES / "data" / "BINANCE_BTCUSDT.P_1D.csv")
    broker = SP.run_strategy((STRATEGIES / "s01_donchian_trailing_v5.pine").read_text(), bars, mintick=0.1,
                             timeframe_seconds=86_400)
    report = SP.compare(SP.parse_trades(path), broker, bars, mintick=0.1, until=bars["timestamp"].iloc[-1].to_pydatetime())
    payload = report.as_dict()
    payload["summary"] = SP.compare_summary(SP.parse_pine_logs(path.read_text())[1], broker)
    frozen = (EVIDENCE / "donchian_parity_report.json").read_text()
    assert json.dumps(payload, indent=1, sort_keys=True) + "\n" == frozen
    assert (payload["sequence_matched"], payload["fully_matched"]) == (246, 244)
    assert sorted({m["trade"] for m in payload["mismatches"]}) == [103, 150]

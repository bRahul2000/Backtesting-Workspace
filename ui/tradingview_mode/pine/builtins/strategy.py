"""strategy() and the strategy.* built-ins (P3.1; see parity/P31_STRATEGY_RESEARCH.md).

The commands only record hypothetical orders in the runtime's broker emulator (``pine/strategy.py``); they never reach
a broker. Declaration arguments are read by the analyzer (``strategy_settings``); arguments whose behaviour is not
implemented are capability gaps there, so nothing here pretends to support them.
"""
from __future__ import annotations

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, constant, variable
from ..strategy import ExitCommand, LONG, SHORT
from ..values import NA, is_na

# ---- the declaration (arguments validated by analyzer.strategy_settings) ----------------------------------------------

STRATEGY_PARAMS = (
    "title", "shorttitle", "overlay", "format", "precision", "scale", "pyramiding", "calc_on_order_fills",
    "calc_on_every_tick", "max_bars_back", "backtest_fill_limits_assumption", "default_qty_type", "default_qty_value",
    "initial_capital", "currency", "slippage", "commission_type", "commission_value", "process_orders_on_close",
    "close_entries_rule", "margin_long", "margin_short", "explicit_plot_zorder", "max_lines_count", "max_labels_count",
    "max_boxes_count", "calc_bars_count", "risk_free_rate", "use_bar_magnifier", "fill_orders_on_standard_ohlc",
    "max_polylines_count", "dynamic_requests", "behind_chart")
builtin("strategy", *(P(name, "const any", NA) for name in STRATEGY_PARAMS), returns="void",
        kind="declaration")(lambda rt, site, a: NA)

# ---- constants -----------------------------------------------------------------------------------------------------

constant("strategy.long", "long", "string")
constant("strategy.short", "short", "string")
constant("strategy.fixed", "fixed", "string")
constant("strategy.cash", "cash", "string")
constant("strategy.percent_of_equity", "percent_of_equity", "string")
for _name in ("percent", "cash_per_contract", "cash_per_order"):
    constant(f"strategy.commission.{_name}", _name, "string")
for _name in ("none", "cancel", "reduce"):
    constant(f"strategy.oca.{_name}", _name, "string")
for _name in ("NONE", "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "HKD", "SGD", "SEK", "NOK", "TRY", "ZAR",
              "INR", "KRW", "RUB", "MYR", "BTC", "ETH", "USDT"):
    constant(f"currency.{_name}", _name, "string")

S, F, I, B = "series string", "series float", "series int", "series bool"


def _broker(rt, name: str):
    if rt.strategy is None:
        raise PineRuntimeError(f"`{name}()` can only be used in strategy() scripts.", 0)
    return rt.strategy


def _direction(value, name: str) -> int:
    if value in ("long", LONG, True):
        return LONG
    if value in ("short", SHORT, False):
        return SHORT
    raise PineRuntimeError(f"`{name}()`: the direction must be strategy.long or strategy.short.", 0)


def _opt(value):
    return None if value is None or is_na(value) else value


def _text(value):
    return None if value is None or is_na(value) else str(value)


def _when(a) -> bool:
    when = a.get("when", True)
    return bool(when) and not is_na(when)


def _close(rt) -> float:
    return float(rt.data.close[rt.bar])


# ---- order placement commands ----------------------------------------------------------------------------------------

_ORDER = (P("id", S), P("direction", S), P("qty", F, NA), P("limit", F, NA), P("stop", F, NA),
          P("oca_name", S, NA), P("oca_type", "input string", "none"), P("comment", S, NA),
          P("alert_message", S, NA), P("disable_alert", B, False), P("when", B, True))


@builtin("strategy.entry", *_ORDER, returns="void")
def _entry(rt, site, a):
    if not _when(a):
        return NA
    _broker(rt, "strategy.entry").entry(rt.bar, _close(rt), str(a["id"]), _direction(a["direction"], "strategy.entry"),
                                        _opt(a["qty"]), _opt(a["limit"]), _opt(a["stop"]), _text(a["oca_name"]),
                                        a["oca_type"] or "none", _text(a["comment"]))
    return NA


@builtin("strategy.order", *_ORDER, returns="void")
def _order(rt, site, a):
    if not _when(a):
        return NA
    _broker(rt, "strategy.order").order(rt.bar, _close(rt), str(a["id"]), _direction(a["direction"], "strategy.order"),
                                        _opt(a["qty"]), _opt(a["limit"]), _opt(a["stop"]), _text(a["oca_name"]),
                                        a["oca_type"] or "none", _text(a["comment"]))
    return NA


@builtin("strategy.exit", P("id", S), P("from_entry", S, NA), P("qty", F, NA), P("qty_percent", F, NA),
         P("profit", F, NA), P("limit", F, NA), P("loss", F, NA), P("stop", F, NA), P("trail_price", F, NA),
         P("trail_points", F, NA), P("trail_offset", F, NA), P("oca_name", S, NA), P("comment", S, NA),
         P("comment_profit", S, NA), P("comment_loss", S, NA), P("comment_trailing", S, NA),
         P("alert_message", S, NA), P("alert_profit", S, NA), P("alert_loss", S, NA), P("alert_trailing", S, NA),
         P("disable_alert", B, False), P("when", B, True), returns="void")
def _exit(rt, site, a):
    if not _when(a):
        return NA
    broker = _broker(rt, "strategy.exit")
    values = {k: _opt(a[k]) for k in ("qty", "qty_percent", "profit", "limit", "loss", "stop", "trail_price",
                                       "trail_points", "trail_offset")}
    if values["qty"] is not None and values["qty"] <= 0:
        return NA
    command = ExitCommand(0, str(a["id"]), _text(a["from_entry"]) or None, rt.bar, values["qty"],
                          values["qty_percent"], values["profit"], values["limit"], values["loss"], values["stop"],
                          values["trail_price"], values["trail_points"], values["trail_offset"],
                          _text(a["comment"]), _text(a["comment_profit"]), _text(a["comment_loss"]),
                          _text(a["comment_trailing"]))
    broker.exit(rt.bar, command)
    return NA


@builtin("strategy.close", P("id", S), P("comment", S, NA), P("qty", F, NA), P("qty_percent", F, NA),
         P("alert_message", S, NA), P("immediately", B, False), P("disable_alert", B, False), P("when", B, True),
         returns="void")
def _close_cmd(rt, site, a):
    if _when(a):
        _broker(rt, "strategy.close").close(rt.bar, str(a["id"]), a["qty"], a["qty_percent"], _text(a["comment"]),
                                            bool(a["immediately"]))
    return NA


@builtin("strategy.close_all", P("comment", S, NA), P("alert_message", S, NA), P("immediately", B, False),
         P("disable_alert", B, False), P("when", B, True), returns="void")
def _close_all(rt, site, a):
    if _when(a):
        _broker(rt, "strategy.close_all").close(rt.bar, None, NA, NA, _text(a["comment"]), bool(a["immediately"]))
    return NA


@builtin("strategy.cancel", P("id", S), P("when", B, True), returns="void")
def _cancel(rt, site, a):
    if _when(a):
        _broker(rt, "strategy.cancel").cancel(str(a["id"]))
    return NA


@builtin("strategy.cancel_all", P("when", B, True), returns="void")
def _cancel_all(rt, site, a):
    if _when(a):
        _broker(rt, "strategy.cancel_all").cancel(None)
    return NA


@builtin("strategy.default_entry_qty", P("fill_price", F), returns="series float")
def _default_entry_qty(rt, site, a):
    return _broker(rt, "strategy.default_entry_qty").default_qty(a["fill_price"])


for _fn in ("convert_to_account", "convert_to_symbol"):       # account currency = chart currency (currency.NONE)
    builtin(f"strategy.{_fn}", P("value", F), returns="series float")(lambda rt, site, a: a["value"])


# ---- state variables -------------------------------------------------------------------------------------------------

def _state(name: str, key: str, type_: str) -> None:
    def impl(rt, bar):
        if rt.strategy is None:
            raise PineRuntimeError(f"`strategy.{name}` can only be used in strategy() scripts.", 0)
        return rt.strategy.value(key, bar)
    variable(f"strategy.{name}", f"series {type_}")(impl)


for _name, _type in (("position_size", "float"), ("position_avg_price", "float"), ("position_entry_name", "string"),
                     ("opentrades", "int"), ("closedtrades", "int"), ("wintrades", "int"), ("losstrades", "int"),
                     ("eventrades", "int"), ("netprofit", "float"), ("grossprofit", "float"), ("grossloss", "float"),
                     ("openprofit", "float"), ("equity", "float"), ("max_drawdown", "float"), ("max_runup", "float"),
                     ("max_contracts_held_all", "float"), ("max_contracts_held_long", "float"),
                     ("max_contracts_held_short", "float"), ("avg_trade", "float"), ("avg_winning_trade", "float"),
                     ("avg_losing_trade", "float")):
    _state(_name, _name, _type)


def _percent(name: str, key: str) -> None:
    def impl(rt, bar):
        if rt.strategy is None:
            raise PineRuntimeError(f"`strategy.{name}` can only be used in strategy() scripts.", 0)
        value = rt.strategy.value(key, bar)
        return NA if is_na(value) else value / rt.strategy.settings.initial_capital * 100.0
    variable(f"strategy.{name}", "series float")(impl)


for _name in ("netprofit", "grossprofit", "grossloss"):        # manual: a percentage of the initial capital
    _percent(f"{_name}_percent", _name)

variable("strategy.initial_capital", "simple float")(
    lambda rt, bar: _broker(rt, "strategy.initial_capital").settings.initial_capital)
variable("strategy.account_currency", "simple string")(lambda rt, bar: rt.data.currency)
variable("strategy.closedtrades.first_index", "series int")(lambda rt, bar: 0)     # no trimming below 9000 trades


# ---- individual trade information -------------------------------------------------------------------------------------

def _trade(rt, name: str, num, closed: bool):
    broker = _broker(rt, name)
    trades = broker.state.closed if closed else broker.state.trades
    if is_na(num):
        return None
    index = int(num)
    return trades[index] if 0 <= index < len(trades) else None


def _field(prefix: str, name: str, returns: str, getter, closed: bool) -> None:
    full = f"strategy.{prefix}.{name}"

    def impl(rt, site, a):
        trade = _trade(rt, full, a["trade_num"], closed)
        return NA if trade is None else getter(rt, trade)
    builtin(full, P("trade_num", I), returns=returns)(impl)


def _open_profit(rt, trade) -> float:
    return (float(rt.data.close[rt.bar]) - trade.entry_price) * trade.direction * trade.qty


_COMMON = (
    ("entry_id", "series string", lambda rt, t: t.entry_id),
    ("entry_price", "series float", lambda rt, t: t.entry_price),
    ("entry_bar_index", "series int", lambda rt, t: t.entry_bar),
    ("entry_time", "series int", lambda rt, t: t.entry_time),
    ("entry_comment", "series string", lambda rt, t: t.entry_comment if t.entry_comment is not None else NA),
    ("size", "series float", lambda rt, t: t.qty * t.direction),
    ("commission", "series float", lambda rt, t: t.commission),
)
for _name, _ret, _get in _COMMON:
    _field("opentrades", _name, _ret, _get, closed=False)
    _field("closedtrades", _name, _ret, _get, closed=True)
_field("opentrades", "profit", "series float", _open_profit, closed=False)
_field("opentrades", "max_runup", "series float", lambda rt, t: t.max_runup * t.qty, closed=False)
_field("opentrades", "max_drawdown", "series float", lambda rt, t: t.max_drawdown * t.qty, closed=False)
for _name, _ret, _get in (
        ("profit", "series float", lambda rt, t: t.profit),
        ("max_runup", "series float", lambda rt, t: t.max_runup),
        ("max_drawdown", "series float", lambda rt, t: t.max_drawdown),
        ("exit_id", "series string", lambda rt, t: t.exit_id),
        ("exit_price", "series float", lambda rt, t: t.exit_price),
        ("exit_time", "series int", lambda rt, t: t.exit_time),
        ("exit_bar_index", "series int", lambda rt, t: t.exit_bar),
        ("exit_comment", "series string", lambda rt, t: t.exit_comment if t.exit_comment is not None else NA)):
    _field("closedtrades", _name, _ret, _get, closed=True)

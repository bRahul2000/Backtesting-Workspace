"""Script outputs and the render protocol sent to the chart.

The plot family (plot, plotshape, plotchar, hline, fill, bgcolor, barcolor)
stores one value/color per bar per call site. Drawing objects (line/label/box/
table/polyline/linefill) will be a second store of objects created, updated
and deleted bar by bar, serialized next to these outputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .values import NA, Color, is_na


class PerBar:
    """One value per bar index (grows with the data; overwritten on re-execution)."""

    __slots__ = ("data",)

    def __init__(self):
        self.data: list[Any] = []

    def set(self, bar: int, value) -> None:
        if bar >= len(self.data):
            self.data.extend([None] * (bar + 1 - len(self.data)))
        self.data[bar] = value

    def get(self, bar: int):
        return self.data[bar] if 0 <= bar < len(self.data) else None


@dataclass
class Output:
    node_id: int
    kind: str
    title: str = ""
    options: dict = field(default_factory=dict)
    values: PerBar = field(default_factory=PerBar)
    colors: PerBar = field(default_factory=PerBar)
    texts: PerBar = field(default_factory=PerBar)


def css(color) -> str | None:
    return color.css() if isinstance(color, Color) else None


def _number(value):
    if value is None or is_na(value) or isinstance(value, bool):     # None: a bar without an execution (P3.1)
        return None
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else value


def render(outputs: list[Output], times: list[int], prefix: str) -> list[dict]:
    """Chart-ready outputs. ``times`` are bar open times (epoch seconds, UTC)."""
    ids = {output.node_id: f"{prefix}-{index}" for index, output in enumerate(outputs)}
    n = len(times)
    result = []
    for output in outputs:
        out_id = ids[output.node_id]
        offset = int(output.options.get("offset") or 0)

        def shifted(bar: int) -> int | None:
            target = bar + offset
            return times[target] if 0 <= target < n else None

        if output.kind == "plot":
            data = []
            for bar in range(n):
                time = shifted(bar)
                if time is None:
                    continue
                value = _number(output.values.get(bar))
                color = css(output.colors.get(bar))
                data.append({"time": time, "value": value, "color": color})
            data.sort(key=lambda p: p["time"])
            result.append({"id": out_id, "kind": "plot", "title": output.title, **output.options, "data": data})
        elif output.kind in ("shape", "char"):
            data = []
            for bar in range(n):
                hit = output.values.get(bar)
                time = shifted(bar)
                if time is None or hit is None or hit is False or is_na(hit):
                    continue
                point = {"time": time, "color": css(output.colors.get(bar)), "text": output.texts.get(bar) or ""}
                if output.options.get("location") == "absolute":
                    price = _number(hit)
                    if price is None:
                        continue
                    point["price"] = price
                data.append(point)
            result.append({"id": out_id, "kind": output.kind, "title": output.title, **output.options, "data": data})
        elif output.kind == "hline":
            price = _number(output.values.get(0) if output.values.data else None)
            if price is None and output.values.data:
                price = next((_number(v) for v in output.values.data if _number(v) is not None), None)
            result.append({"id": out_id, "kind": "hline", "title": output.title, "price": price,
                           "color": css(next((c for c in output.colors.data if c is not None), None)), **output.options})
        elif output.kind == "fill":
            refs = output.options.get("refs", ())
            data = []
            for bar in range(n):
                time = shifted(bar)
                color = css(output.colors.get(bar))
                if time is not None and color is not None:
                    data.append({"time": time, "color": color})
            options = {k: v for k, v in output.options.items() if k != "refs"}
            result.append({"id": out_id, "kind": "fill", "title": output.title, **options,
                           "between": [ids.get(ref) for ref in refs], "data": data})
        elif output.kind in ("bgcolor", "barcolor"):
            data = []
            for bar in range(n):
                time = shifted(bar)
                color = css(output.colors.get(bar))
                if time is not None and color is not None:
                    data.append({"time": time, "color": color})
            result.append({"id": out_id, "kind": output.kind, "title": output.title, "data": data})
    return result


# ---- drawing objects (P2.3a; P2.3b: superseded linefills, oracle-support tables) -------------------------------------

DRAWING_LISTS = {"line": "lines", "label": "labels", "box": "boxes", "linefill": "linefills", "table": "tables"}


def _plain(value):
    if isinstance(value, Color):
        return css(value)
    if isinstance(value, float):
        return _number(value)
    return None if is_na(value) else value


def render_drawings(store, prefix: str) -> dict:
    """The live drawing objects of a run, with their raw Pine coordinates (``xloc`` + x as a bar index or a UNIX time
    in ms, y as a price): the browser maps them onto the chart. Keys are stable across realtime ticks. Superseded
    linefills are not rendered (q9v), nor are linefills whose source line was garbage-collected (they stay alive and
    listed, q11 row G, but have no geometry); tables carry their cells (P2.3b oracle-support tables-core)."""
    result = {name: [] for name in DRAWING_LISTS.values()}
    for drawing in store.objects():
        if drawing.superseded or (drawing.kind == "linefill" and not all(
                drawing.props[end] in store.live for end in ("line1", "line2"))):
            continue
        item = {"key": f"{prefix}:{drawing.kind}:{drawing.oid}", "kind": drawing.kind, "bar": drawing.created_bar}
        cells = []
        for name, value in drawing.props.items():
            if isinstance(name, tuple):                 # a table cell ("cell", column, row)
                if value is not None:
                    cells.append({"column": name[1], "row": name[2], **{k: _plain(v) for k, v in value.items()}})
            elif drawing.kind == "linefill" and name in ("line1", "line2"):
                item[name] = f"{prefix}:line:{value}"
            else:
                item[name] = _plain(value)
        if drawing.kind == "table":
            item["cells"] = sorted(cells, key=lambda c: (c["row"], c["column"]))
        result[DRAWING_LISTS[drawing.kind]].append(item)
    return result


# ---- strategy report (P3.1) ----------------------------------------------------------------------------------------

MAX_REPORT_FILLS = 40_000               # chart markers: every fill up to this many (ENGINE LIMIT)
MAX_REPORT_TRADES = 9000              # TradingView keeps the latest 9000 trades in its report (manual)


def _num(value):
    return None if value is None or is_na(value) or (isinstance(value, float) and not math.isfinite(value)) else value


def strategy_metrics(broker, last_close) -> dict:
    """Strategy Tester metrics, all derived from the broker's single trade ledger."""
    s, settings = broker.state, broker.settings
    closed = s.closed
    wins = [t.profit for t in closed if t.profit > 1e-9]
    losses = [t.profit for t in closed if t.profit < -1e-9]
    open_profit = broker.open_profit(last_close) if last_close is not None else 0.0
    longs = [t for t in closed if t.direction > 0]
    shorts = [t for t in closed if t.direction < 0]
    return {
        "initial_capital": settings.initial_capital,
        "net_profit": s.netprofit, "net_profit_percent": s.netprofit / settings.initial_capital * 100,
        "gross_profit": s.grossprofit, "gross_loss": s.grossloss,
        "profit_factor": _num(s.grossprofit / s.grossloss) if s.grossloss > 0 else None,
        "commission_paid": s.commission_paid,
        "total_closed_trades": len(closed), "winning_trades": len(wins), "losing_trades": len(losses),
        "even_trades": s.evens, "percent_profitable": len(wins) / len(closed) * 100 if closed else None,
        "avg_trade": s.netprofit / len(closed) if closed else None,
        "avg_winning_trade": sum(wins) / len(wins) if wins else None,
        "avg_losing_trade": sum(losses) / len(losses) if losses else None,
        "largest_winning_trade": max(wins) if wins else None, "largest_losing_trade": min(losses) if losses else None,
        "max_drawdown": s.max_drawdown, "max_runup": s.max_runup,
        "open_profit": open_profit, "open_trades": len(s.trades), "position_size": broker.position(),
        "ending_equity": settings.initial_capital + s.netprofit + open_profit,
        # ENGINE POLICY (not TradingView-verified): bars in a trade = exit bar index - entry bar index
        "avg_bars_in_trade": sum(t.exit_bar - t.entry_bar for t in closed) / len(closed) if closed else None,
        "long_trades": len(longs), "long_net_profit": sum(t.profit for t in longs),
        "short_trades": len(shorts), "short_net_profit": sum(t.profit for t in shorts),
        "margin_calls": s.margin_calls,
    }


def render_strategy(broker, times: list, prefix: str) -> dict:
    """The strategy report sent to the chart: closed and open trades, fills (chart markers), equity per closed bar
    and metrics. Times are epoch seconds; bars are indices into the run's bars."""
    s = broker.state
    last = broker.bar if broker.bar >= 0 else None
    last_close = float(broker.data.close[last]) if last is not None and not math.isnan(broker.data.close[last]) else None

    def when(bar):
        return times[bar] if 0 <= bar < len(times) else None

    def percent(profit, t):
        # ENGINE POLICY (not TradingView-verified): net P&L relative to the entry value (entry price x quantity)
        value = abs(t.entry_price * t.qty)
        return None if profit is None or not value else profit / value * 100

    trades = [{
        "key": f"{prefix}:trade:{t.number}", "number": t.number, "open": False, "direction": t.direction,
        "entry_id": t.entry_id, "entry_bar": t.entry_bar, "entry_time": when(t.entry_bar), "entry_price": t.entry_price,
        "entry_comment": t.entry_comment, "exit_id": t.exit_id, "exit_bar": t.exit_bar, "exit_time": when(t.exit_bar),
        "exit_price": t.exit_price, "exit_kind": t.exit_kind, "exit_comment": t.exit_comment, "qty": t.qty,
        "profit": t.profit, "profit_percent": percent(t.profit, t), "commission": t.commission,
        "max_runup": t.max_runup, "max_drawdown": t.max_drawdown, "bars_held": t.exit_bar - t.entry_bar,
    } for t in s.closed[-MAX_REPORT_TRADES:]]
    for index, t in enumerate(s.trades):
        trades.append({
            "key": f"{prefix}:open:{t.uid}", "number": len(s.closed) + index + 1, "open": True, "direction": t.direction,
            "entry_id": t.entry_id, "entry_bar": t.entry_bar, "entry_time": when(t.entry_bar),
            "entry_price": t.entry_price, "entry_comment": t.entry_comment, "exit_id": None, "exit_bar": None,
            "exit_time": None, "exit_price": None, "exit_kind": None, "exit_comment": None, "qty": t.qty,
            "profit": (profit := None if last_close is None else (last_close - t.entry_price) * t.direction * t.qty),
            "profit_percent": percent(profit, t), "commission": t.commission,
            "max_runup": t.max_runup * t.qty, "max_drawdown": t.max_drawdown * t.qty,
            "bars_held": (last - t.entry_bar) if last is not None else None,
        })
    # every fill is a chart marker (the latest MAX_REPORT_FILLS fills; fill_count says how many exist)
    fills = [{"key": f"{prefix}:fill:{i}", "bar": f.bar, "time": when(f.bar), "id": f.order_id, "kind": f.kind,
              "exit_kind": f.exit_kind, "side": f.direction, "qty": f.qty, "price": f.price,
              "position_after": f.position_after, "comment": f.comment}
             for i, f in enumerate(s.fills)][-MAX_REPORT_FILLS:]
    equity = [[when(bar), value] for bar, value in s.equity_curve if when(bar) is not None]
    return {"trades": trades, "fills": fills, "equity": equity, "metrics": strategy_metrics(broker, last_close),
            "pending_orders": len(s.orders), "settings": dict(vars(broker.settings)),
            "fill_count": len(s.fills), "fills_reported": len(fills),
            "calc_range": {"bars": len(times), "first_time": times[0] if times else None,
                           "last_time": times[-1] if times else None}}

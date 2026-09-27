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
    if is_na(value) or isinstance(value, bool):
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

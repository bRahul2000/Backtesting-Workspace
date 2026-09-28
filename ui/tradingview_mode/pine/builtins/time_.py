"""Time, barstate.*, syminfo.* and timeframe.* built-ins (exchange time zone: UTC)."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from ..errors import PineRuntimeError
from ..registry import Param as P, builtin, constant, variable
from ..values import NA, is_na

UTC = timezone.utc
for _index, _day in enumerate(("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"), start=1):
    constant(f"dayofweek.{_day}", _index, "int")


def _dt(ms) -> datetime:
    return datetime.fromtimestamp(ms / 1000, UTC)


_PARTS = {
    "year": lambda d: d.year, "month": lambda d: d.month, "dayofmonth": lambda d: d.day,
    "dayofweek": lambda d: (d.weekday() + 1) % 7 + 1,     # Pine: 1 = Sunday ... 7 = Saturday
    "hour": lambda d: d.hour, "minute": lambda d: d.minute, "second": lambda d: d.second,
    "weekofyear": lambda d: d.isocalendar()[1],
}


def _check_tz(tz) -> None:
    if not is_na(tz) and tz not in ("", "UTC", "GMT", "Etc/UTC", "GMT+0", "UTC+0"):
        raise PineRuntimeError(f"Time zone {tz!r} is not implemented yet (this engine uses UTC).", 0)


for _name, _part in _PARTS.items():
    variable(_name, returns="series int")(
        lambda rt, bar, _part=_part: NA if (t := rt.series_at("time", bar)) is NA else _part(_dt(t)))

    def _fn(rt, site, a, _part=_part):
        _check_tz(a["timezone"])
        return NA if is_na(a["time"]) else _part(_dt(a["time"]))

    builtin(_name, P("time", "series int"), P("timezone", "series string", NA), returns="series int")(_fn)


# ---- timeframes --------------------------------------------------------------------------------------------

def timeframe_string(seconds: int) -> str:
    if seconds % 2_592_000 == 0 and seconds >= 2_592_000:
        return f"{seconds // 2_592_000}M" if seconds // 2_592_000 > 1 else "M"
    if seconds % 604_800 == 0:
        return f"{seconds // 604_800}W" if seconds // 604_800 > 1 else "W"
    if seconds % 86_400 == 0:
        return f"{seconds // 86_400}D" if seconds // 86_400 > 1 else "D"
    if seconds % 60 == 0:
        return str(seconds // 60)
    return f"{seconds}S"


_TF = re.compile(r"^(\d*)([SDWM]?)$")


def timeframe_seconds(text: str, chart_seconds: int) -> int:
    if is_na(text) or text == "":
        return chart_seconds
    match = _TF.match(text.upper())
    if not match:
        raise PineRuntimeError(f"Invalid timeframe {text!r}.", 0)
    count = int(match.group(1) or 1)
    unit = match.group(2)
    return count * {"": 60, "S": 1, "D": 86_400, "W": 604_800, "M": 2_592_000}[unit]


def floor_time(ms: int, seconds: int) -> int:
    """Open time (ms) of the period of ``seconds`` containing ``ms`` (UTC; weeks start Monday, months on the 1st)."""
    d = _dt(ms)
    if seconds >= 2_592_000:
        months = seconds // 2_592_000
        index = (d.year * 12 + d.month - 1) // months * months
        return int(datetime(index // 12, index % 12 + 1, 1, tzinfo=UTC).timestamp() * 1000)
    if seconds >= 604_800 and seconds % 604_800 == 0:
        monday = datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() - d.weekday() * 86_400
        return int(monday * 1000)
    return ms // (seconds * 1000) * (seconds * 1000)


@builtin("time", P("timeframe", "series string", ""), P("session", "series string", NA), P("timezone", "series string", NA),
         returns="series int")
def _time(rt, site, a):
    if not is_na(a["session"]):
        raise PineRuntimeError("time() with a session argument is not implemented yet.", 0)
    _check_tz(a["timezone"])
    t = rt.series_at("time", rt.bar)
    if t is NA:
        return NA
    seconds = timeframe_seconds(a["timeframe"], rt.data.timeframe_seconds)
    if seconds < rt.data.timeframe_seconds:
        raise PineRuntimeError("time() for a lower timeframe than the chart is not implemented yet.", 0)
    return floor_time(t, seconds)


@builtin("time_close", P("timeframe", "series string", ""), P("session", "series string", NA),
         P("timezone", "series string", NA), returns="series int")
def _time_close_fn(rt, site, a):
    start = _time(rt, site, a)
    if start is NA:
        return NA
    seconds = timeframe_seconds(a["timeframe"], rt.data.timeframe_seconds)
    return start + seconds * 1000


@builtin("timestamp", P("year", "series int"), P("month", "series int"), P("day", "series int"),
         P("hour", "series int", 0), P("minute", "series int", 0), P("second", "series int", 0), returns="series int",
         overloads=((P("timezone", "series string"), P("year", "series int"), P("month", "series int"),
                     P("day", "series int"), P("hour", "series int", 0), P("minute", "series int", 0),
                     P("second", "series int", 0)),
                    (P("dateString", "const string"),)))
def _timestamp(rt, site, a):
    if "dateString" in a:
        text = a["dateString"].replace(" ", "T")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise PineRuntimeError(f"timestamp(): cannot parse {a['dateString']!r}.", 0) from None
        return int((parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).timestamp() * 1000)
    _check_tz(a.get("timezone", NA))
    parts = [a[k] for k in ("year", "month", "day", "hour", "minute", "second")]
    if any(is_na(p) for p in parts):
        return NA
    y, mo, d, h, mi, s = (int(p) for p in parts)
    first = datetime(y + (mo - 1) // 12, (mo - 1) % 12 + 1, 1, tzinfo=UTC)   # months/days may overflow, as in Pine
    return int((first.timestamp() + (d - 1) * 86_400 + h * 3600 + mi * 60 + s) * 1000)


# ---- barstate ---------------------------------------------------------------------------------------------

def _realtime(rt, bar) -> bool:
    confirmed = rt.data.confirmed_until
    return confirmed is not None and bar >= confirmed


variable("barstate.isfirst", "series bool")(lambda rt, bar: bar == 0)
variable("barstate.islast", "series bool")(lambda rt, bar: bar == rt.data.size - 1)
variable("barstate.ishistory", "series bool")(lambda rt, bar: not _realtime(rt, bar))
variable("barstate.isrealtime", "series bool")(lambda rt, bar: _realtime(rt, bar))
variable("barstate.isconfirmed", "series bool")(lambda rt, bar: not _realtime(rt, bar))
variable("barstate.isnew", "series bool")(lambda rt, bar: not _realtime(rt, bar) or rt.bar_reruns == 0)
variable("barstate.islastconfirmedhistory", "series bool")(
    lambda rt, bar: bar == ((rt.data.confirmed_until if rt.data.confirmed_until is not None else rt.data.size) - 1))

# ---- syminfo -----------------------------------------------------------------------------------------------

for _name, _getter, _type in (
    ("ticker", lambda d: d.ticker, "string"), ("tickerid", lambda d: d.tickerid, "string"),
    ("mintick", lambda d: d.mintick, "float"), ("pointvalue", lambda d: 1.0, "float"),
    ("pricescale", lambda d: round(1 / d.mintick) if d.mintick else 100, "int"), ("minmove", lambda d: 1, "int"),
    ("currency", lambda d: d.currency, "string"), ("basecurrency", lambda d: d.basecurrency, "string"),
    ("type", lambda d: d.type, "string"), ("description", lambda d: d.description, "string"),
    ("timezone", lambda d: "Etc/UTC", "string"), ("session", lambda d: d.session, "string"),
    ("prefix", lambda d: d.tickerid.split(":")[0] if ":" in d.tickerid else "", "string"),
    ("root", lambda d: d.ticker, "string"), ("volumetype", lambda d: "base", "string"),
):
    variable(f"syminfo.{_name}", f"simple {_type}")(lambda rt, bar, _getter=_getter: _getter(rt.data))

# ---- timeframe -----------------------------------------------------------------------------------------------

_TFV = {
    "period": ("string", lambda s: timeframe_string(s)), "main_period": ("string", lambda s: timeframe_string(s)),
    "multiplier": ("int", lambda s: int(timeframe_string(s).rstrip("SDWM") or 1)),
    "isseconds": ("bool", lambda s: s < 60), "isminutes": ("bool", lambda s: 60 <= s < 86_400),
    "isintraday": ("bool", lambda s: s < 86_400), "isdaily": ("bool", lambda s: s % 86_400 == 0 and s < 604_800),
    "isweekly": ("bool", lambda s: s % 604_800 == 0 and s < 2_592_000), "ismonthly": ("bool", lambda s: s >= 2_592_000),
    "isdwm": ("bool", lambda s: s >= 86_400), "isticks": ("bool", lambda s: False),
}
for _name, (_type, _fn) in _TFV.items():
    variable(f"timeframe.{_name}", f"simple {_type}")(lambda rt, bar, _fn=_fn: _fn(rt.data.timeframe_seconds))


def _period(rt, bar):
    """v6 always includes the multiplier ("1D"); v5 omits a multiplier of 1 ("D")."""
    text = timeframe_string(rt.data.timeframe_seconds)
    return "1" + text if (rt.program.script.version or 5) >= 6 and text in ("D", "W", "M") else text


variable("timeframe.period", "simple string")(_period)
variable("timeframe.main_period", "simple string")(_period)


@builtin("timeframe.in_seconds", P("timeframe", "simple string", ""), returns="simple int")
def _in_seconds(rt, site, a):
    return timeframe_seconds(a["timeframe"], rt.data.timeframe_seconds)


@builtin("timeframe.from_seconds", P("seconds", "simple int"), returns="simple string")
def _from_seconds(rt, site, a):
    return timeframe_string(int(a["seconds"]))


@builtin("timeframe.change", P("timeframe", "series string"), returns="series bool")
def _change(rt, site, a):
    seconds = timeframe_seconds(a["timeframe"], rt.data.timeframe_seconds)
    now, before = rt.series_at("time", rt.bar), rt.series_at("time", rt.bar - 1)
    if before is NA:
        return True
    return floor_time(now, seconds) != floor_time(before, seconds)

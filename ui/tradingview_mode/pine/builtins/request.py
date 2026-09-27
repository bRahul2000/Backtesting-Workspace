"""request.security() and barmerge.* (P2.1).

``request.security`` is a special form (``kind="security"``): the runtime never evaluates its ``expression``
argument in the calling context; the security manager runs it in the requested context (see security.py).
Every other ``request.*`` stays an explicit capability gap."""
from __future__ import annotations

from ..registry import Param as P, builtin, constant
from ..values import NA

for _name in ("gaps_on", "gaps_off", "lookahead_on", "lookahead_off"):
    constant(f"barmerge.{_name}", _name, "string")


@builtin("request.security", P("symbol", "series string"), P("timeframe", "series string"),
         P("expression", "series any"), P("gaps", "simple string", "gaps_off"),
         P("lookahead", "simple string", "lookahead_off"), P("ignore_invalid_symbol", "input bool", False),
         P("currency", "series string", NA), P("calc_bars_count", "simple int", NA), kind="security")
def _security(rt, node, args):   # never called: the runtime dispatches kind="security" to the security manager
    raise AssertionError("request.security is dispatched by the runtime")

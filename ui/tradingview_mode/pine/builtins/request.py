"""request.security() (P2.1), request.security_lower_tf() (P2.2-A4) and barmerge.*.

Both are special forms (``kind="security"``): the runtime never evaluates their ``expression`` argument in the
calling context; the security manager runs it in the requested context (see security.py). Every other
``request.*`` stays an explicit capability gap."""
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


# no `gaps` / `lookahead` parameters (Pine manual); the result is one array (or a tuple of arrays) per chart bar
@builtin("request.security_lower_tf", P("symbol", "series string"), P("timeframe", "series string"),
         P("expression", "series any"), P("ignore_invalid_symbol", "input bool", False),
         P("currency", "series string", NA), P("ignore_invalid_timeframe", "input bool", False),
         P("calc_bars_count", "simple int", NA), kind="security")
def _security_lower_tf(rt, node, args):   # never called (see above)
    raise AssertionError("request.security_lower_tf is dispatched by the runtime")

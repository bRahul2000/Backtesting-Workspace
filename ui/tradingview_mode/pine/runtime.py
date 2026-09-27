"""Bar-by-bar Pine interpreter.

Execution model (Pine's):
* The script body runs once per bar, oldest to newest.
* Every variable, function parameter and history expression is a series.
  Its history is recorded per execution of its declaration (a local block that
  does not run on a bar records nothing that bar, exactly like Pine).
* ``var`` keeps its value across bars; ``varip`` also keeps intrabar updates.
* Stateful built-ins (ta.* ...) keep state per call site; the key includes the
  chain of user-function call sites, so ``f()`` called twice has two states.
* Re-running a bar (a live forming candle) first rolls every series and
  call-site state back to the end of the previous bar, so live updates only
  re-execute the last bar (commit/rollback, like Pine's realtime model).

The runtime reads market data through ``DataContext``; request.security()
will add further contexts later without changing the interpreter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from . import ast as A
from . import values as V
from .errors import PineRuntimeError
from .values import NA, Color, is_na, truthy

MISSING = object()
MAX_LOOP_ITERATIONS = 100_000
MAX_CALL_DEPTH = 64


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

@dataclass
class DataContext:
    """One symbol/timeframe of bars (UTC). Arrays may grow between runs (live)."""

    time: np.ndarray            # bar open time, epoch milliseconds (int64)
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    timeframe_seconds: int
    ticker: str = ""
    tickerid: str = ""
    mintick: float = 0.01
    currency: str = "USD"
    basecurrency: str = ""
    type: str = "crypto"
    description: str = ""
    session: str = "24x7"
    confirmed_until: int | None = None   # bars >= this index are realtime (forming); None = all historical

    @property
    def size(self) -> int:
        return len(self.time)


# ---------------------------------------------------------------------------
# Series storage with rollback
# ---------------------------------------------------------------------------

class SeriesBuffer:
    """Values of one series, one per execution, tagged with the bar index."""

    __slots__ = ("bars", "values", "varip")

    def __init__(self, varip: bool = False):
        self.bars: list[int] = []
        self.values: list[Any] = []
        self.varip = varip

    def set(self, bar: int, value) -> None:
        if self.bars and self.bars[-1] == bar:
            self.values[-1] = value
        else:
            self.bars.append(bar)
            self.values.append(value)

    def current(self):
        return self.values[-1] if self.values else NA

    def last(self):
        return self.values[-1] if self.values else MISSING

    def back(self, n: int):
        index = len(self.values) - 1 - n
        return self.values[index] if 0 <= index < len(self.values) else NA

    def before(self, bar: int):
        """The latest value recorded on an earlier bar."""
        for index in range(len(self.bars) - 1, -1, -1):
            if self.bars[index] < bar:
                return self.values[index]
        return MISSING

    def window(self, n: int) -> list | None:
        """The last n values (oldest first), or None if fewer were recorded."""
        return self.values[-n:] if n > 0 and len(self.values) >= n else None

    def truncate(self, bar: int) -> None:
        while self.bars and self.bars[-1] >= bar:
            self.bars.pop()
            self.values.pop()


class CallSite:
    """Per-call-site state of a stateful built-in: named series plus nested sites."""

    __slots__ = ("buffers", "subs", "scratch")

    def __init__(self):
        self.buffers: dict[str, SeriesBuffer] = {}
        self.subs: dict[str, CallSite] = {}
        self.scratch: dict[str, Any] = {}

    def buf(self, name: str) -> SeriesBuffer:
        buffer = self.buffers.get(name)
        if buffer is None:
            buffer = self.buffers[name] = SeriesBuffer()
        return buffer

    def push(self, name: str, bar: int, value) -> SeriesBuffer:
        buffer = self.buf(name)
        buffer.set(bar, value)
        return buffer

    def sub(self, name: str) -> "CallSite":
        site = self.subs.get(name)
        if site is None:
            site = self.subs[name] = CallSite()
        return site

    def truncate(self, bar: int) -> None:
        for buffer in self.buffers.values():
            buffer.truncate(bar)
        for site in self.subs.values():
            site.truncate(bar)


class Scope:
    __slots__ = ("vars", "parent")

    def __init__(self, parent: "Scope | None" = None):
        self.vars: dict[str, SeriesBuffer] = {}
        self.parent = parent

    def lookup(self, name: str) -> SeriesBuffer | None:
        scope = self
        while scope is not None:
            buffer = scope.vars.get(name)
            if buffer is not None:
                return buffer
            scope = scope.parent
        return None


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------

class Runtime:
    def __init__(self, program, data: DataContext, input_values: dict[int, Any] | None = None):
        self.program = program
        self.data = data
        self.input_values = input_values or {}
        self.buffers: dict[tuple, SeriesBuffer] = {}
        self.sites: dict[tuple, CallSite] = {}
        self.outputs: dict[int, Any] = {}
        self.cache: dict[str, Any] = {}
        self.bar = -1
        self.last_bar = -1
        self.ctx_path: tuple = ()
        self.global_scope: Scope | None = None
        self.realtime_updates = 0
        self.bar_reruns = 0             # re-executions of the current bar (0 = its first tick: barstate.isnew)
        self._last_executed = -1        # unlike last_bar, never rewound by the engine's forming-bar rollback
        self.executed_bars = 0          # bar executions (incl. re-runs), for reporting
        self._colors: dict[int, Color] = {}
        # version-dependent semantics (TradingView's v5 -> v6 migration guide)
        version = program.script.version or 5
        self.lazy_bool = version >= 6            # v6 `and`/`or` short-circuit; v5 evaluates both sides
        self.dynamic_for_end = version >= 6      # v6 re-evaluates a `for` loop's end before every iteration
        self._eval = {
            A.Literal: self.eval_literal, A.Name: self.eval_name, A.Attribute: self.eval_name,
            A.Call: self.eval_call, A.History: self.eval_history, A.Unary: self.eval_unary,
            A.Binary: self.eval_binary, A.Ternary: self.eval_ternary, A.TupleExpr: self.eval_tuple,
            A.If: self.exec_if, A.Switch: self.exec_switch, A.ForRange: self.exec_for, A.While: self.exec_while,
        }
        self._exec = {
            A.VarDecl: self.exec_decl, A.TupleDecl: self.exec_tuple_decl, A.Assign: self.exec_assign,
            A.ExprStmt: lambda node, scope: self.eval(node.expr, scope), A.If: self.exec_if,
            A.Switch: self.exec_switch, A.ForRange: self.exec_for, A.While: self.exec_while,
            A.Break: self.exec_break, A.Continue: self.exec_continue,
            A.FunctionDef: lambda node, scope: NA, A.TypeDef: lambda node, scope: NA, A.Import: lambda node, scope: NA,
        }

    # -- driving --------------------------------------------------------------------------------
    def run(self, until: int | None = None) -> None:
        """Execute every bar after the last executed one, up to ``until`` (exclusive; default all).
        Re-running an already executed bar is the caller's decision (see ``rollback``)."""
        end = self.data.size if until is None else until
        for bar in range(self.last_bar + 1, end):
            self.execute_bar(bar)

    def execute_bar(self, bar: int) -> None:
        self.bar_reruns = self.bar_reruns + 1 if bar == self._last_executed else 0
        self._last_executed = bar
        if bar <= self.last_bar:
            self.rollback(bar)
        self.bar = bar
        self.ctx_path = ()
        scope = Scope()
        self.global_scope = scope
        try:
            self.exec_body(self.program.script.body, scope)
        except PineRuntimeError as exc:
            exc.bar_index = bar
            raise
        except (_Break, _Continue):
            raise PineRuntimeError("`break`/`continue` outside a loop.", 0, bar) from None
        except RecursionError:
            raise PineRuntimeError("Expression nesting is too deep.", 0, bar) from None
        self.last_bar = bar
        self.executed_bars += 1

    def rollback(self, bar: int) -> None:
        """Undo everything recorded on ``bar`` or later (varip series excepted)."""
        for buffer in self.buffers.values():
            if not buffer.varip:
                buffer.truncate(bar)
        for site in self.sites.values():
            site.truncate(bar)

    # -- helpers used by built-ins ------------------------------------------------------------------
    def site(self, node_id: int) -> CallSite:
        key = (self.ctx_path, node_id)
        site = self.sites.get(key)
        if site is None:
            site = self.sites[key] = CallSite()
        return site

    def buffer(self, key: tuple, varip: bool = False) -> SeriesBuffer:
        buffer = self.buffers.get(key)
        if buffer is None:
            buffer = self.buffers[key] = SeriesBuffer(varip=varip)
        return buffer

    def series_at(self, name: str, bar: int):
        """open/high/low/close/volume/time at a bar (na before the first bar)."""
        if bar < 0 or bar >= self.data.size:
            return NA
        value = getattr(self.data, name)[bar]
        if name == "time":
            return int(value)
        value = float(value)
        return NA if value != value else value

    def fail(self, message: str, node: A.Node | None = None):
        raise PineRuntimeError(message, node.line if node is not None else 0, self.bar)

    # -- statements ----------------------------------------------------------------------------------
    def exec_body(self, body, scope: Scope):
        value = NA
        execute = self._exec
        for statement in body:
            value = execute[type(statement)](statement, scope)
        return value

    def exec_block(self, block: A.Block, parent: Scope):
        return self.exec_body(block.body, Scope(parent))

    def exec_decl(self, node: A.VarDecl, scope: Scope):
        key = (self.ctx_path, node.id)
        buffer = self.buffers.get(key)
        if buffer is None:
            buffer = self.buffers[key] = SeriesBuffer(varip=node.mode == "varip")
        if node.mode is not None and (previous := buffer.last()) is not MISSING:
            value = previous                     # var/varip: initialised once, then carried
        else:
            value = self.coerce(node.type, self.eval(node.value, scope), node)
        buffer.set(self.bar, value)
        scope.vars[node.name] = buffer
        return value

    def exec_tuple_decl(self, node: A.TupleDecl, scope: Scope):
        value = self.eval(node.value, scope)
        if not isinstance(value, tuple) or len(value) != len(node.names):
            self.fail(f"The right side returns {len(value) if isinstance(value, tuple) else 1} value(s) but "
                      f"{len(node.names)} names are declared.", node)
        for index, (name, item) in enumerate(zip(node.names, value)):
            if name == "_":
                continue
            buffer = self.buffer((self.ctx_path, node.id, index))
            buffer.set(self.bar, item)
            scope.vars[name] = buffer
        return value

    def exec_assign(self, node: A.Assign, scope: Scope):
        buffer = scope.lookup(node.target.name)
        value = self.eval(node.value, scope)
        if node.op != ":=":
            current = buffer.current()
            value = {"+=": V.add, "-=": V.sub, "*=": V.mul, "/=": V.div, "%=": V.mod}[node.op](current, value)
        buffer.set(self.bar, value)
        return value

    def exec_if(self, node: A.If, scope: Scope):
        if truthy(self.eval(node.condition, scope)):
            return self.exec_block(node.body, scope)
        if node.orelse is not None:
            return self.exec_block(node.orelse, scope)
        return NA

    def exec_switch(self, node: A.Switch, scope: Scope):
        if node.subject is not None:
            subject = self.eval(node.subject, scope)
            for case in node.cases:
                if case.match is None or truthy(V.compare("==", subject, self.eval(case.match, scope))):
                    return self.exec_block(case.body, scope)
            return NA
        for case in node.cases:
            if case.match is None or truthy(self.eval(case.match, scope)):
                return self.exec_block(case.body, scope)
        return NA

    def exec_for(self, node: A.ForRange, scope: Scope):
        start, end = self.eval(node.start, scope), self.eval(node.end, scope)
        if is_na(start) or is_na(end):
            return NA
        step = 1 if node.step is None else self.eval(node.step, scope)
        if is_na(step) or step == 0:
            self.fail("A `for` loop step must be a non-zero number.", node)
        step = abs(step) if end >= start else -abs(step)
        loop_scope = Scope(scope)
        counter = self.buffer((self.ctx_path, node.id))
        loop_scope.vars[node.var] = counter
        value, i, count = NA, start, 0
        while (i <= end) if step > 0 else (i >= end):
            counter.set(self.bar, i)
            try:
                value = self.exec_block(node.body, loop_scope)
            except _Continue:
                pass
            except _Break:
                break
            i += step
            count += 1
            if count > MAX_LOOP_ITERATIONS:
                self.fail(f"Loop exceeded {MAX_LOOP_ITERATIONS:,} iterations on one bar.", node)
            if self.dynamic_for_end:             # the direction stays the one set before the first pass
                end = self.eval(node.end, loop_scope)
                if is_na(end):
                    break
        return value

    def exec_while(self, node: A.While, scope: Scope):
        value, count = NA, 0
        while truthy(self.eval(node.condition, scope)):
            try:
                value = self.exec_block(node.body, scope)
            except _Continue:
                pass
            except _Break:
                break
            count += 1
            if count > MAX_LOOP_ITERATIONS:
                self.fail(f"Loop exceeded {MAX_LOOP_ITERATIONS:,} iterations on one bar.", node)
        return value

    def exec_break(self, node, scope):
        raise _Break()

    def exec_continue(self, node, scope):
        raise _Continue()

    # -- expressions ------------------------------------------------------------------------------------
    def eval(self, node: A.Node, scope: Scope):
        return self._eval[type(node)](node, scope)

    def eval_literal(self, node: A.Literal, scope: Scope):
        if node.kind == "color":
            color = self._colors.get(node.id)
            if color is None:
                color = self._colors[node.id] = Color.from_hex(node.value)
            return color
        return node.value

    def eval_name(self, node, scope: Scope):
        kind, target = self.program.names[node.id]
        if kind == "user":
            return scope.lookup(target).current()
        if kind == "var":
            return target.impl(self, self.bar)
        return target                                # const

    def eval_history(self, node: A.History, scope: Scope):
        offset = self.eval(node.offset, scope)
        if is_na(offset):
            return NA
        if offset != int(offset) or offset < 0:
            self.fail("A history reference offset must be a non-negative integer.", node)
        n = int(offset)
        target = node.target
        resolved = self.program.names.get(target.id) if isinstance(target, (A.Name, A.Attribute)) else None
        if resolved is not None:
            kind, value = resolved
            if kind == "user":
                return scope.lookup(value).back(n)
            if kind == "var":
                return value.impl(self, self.bar - n) if self.bar - n >= 0 else NA
            return value
        buffer = self.buffer((self.ctx_path, node.id))
        buffer.set(self.bar, self.eval(target, scope))
        return buffer.back(n)

    def eval_unary(self, node: A.Unary, scope: Scope):
        value = self.eval(node.operand, scope)
        if node.op == "-":
            return V.neg(value)
        if node.op == "+":
            return value
        return NA if is_na(value) else not truthy(value)

    _BINARY = {"+": V.add, "-": V.sub, "*": V.mul, "/": V.div, "%": V.mod}

    def eval_binary(self, node: A.Binary, scope: Scope):
        op = node.op
        if op in ("and", "or"):
            left = truthy(self.eval(node.left, scope))
            if self.lazy_bool and left == (op == "or"):
                return left
            right = truthy(self.eval(node.right, scope))
            return (left and right) if op == "and" else (left or right)
        left, right = self.eval(node.left, scope), self.eval(node.right, scope)
        if op == "/" and node.id in self.program.int_division:
            return V.int_div(left, right)
        func = self._BINARY.get(op)
        try:
            return func(left, right) if func else V.compare(op, left, right)
        except TypeError as exc:
            self.fail(str(exc), node)

    def eval_ternary(self, node: A.Ternary, scope: Scope):
        return self.eval(node.then if truthy(self.eval(node.condition, scope)) else node.otherwise, scope)

    def eval_tuple(self, node: A.TupleExpr, scope: Scope):
        return tuple(self.eval(item, scope) for item in node.items)

    def eval_call(self, node: A.Call, scope: Scope):
        kind, target, binding = self.program.calls[node.id]
        if kind == "user":
            return self.call_user(node, target, binding, scope)
        if target.kind == "declaration":
            return NA
        if target.kind == "input":
            return target.impl(self, node, self.input_values.get(node.id, MISSING))
        args = {}
        for param in binding.params:
            arg = binding.nodes.get(param.name)
            args[param.name] = self.eval(arg, scope) if arg is not None else param.default
        if binding.extra:
            args["*"] = [self.eval(arg, scope) for arg in binding.extra]
        if target.kind == "output":
            return target.impl(self, node, args)
        site = self.site(node.id) if target.stateful else None
        try:
            return target.impl(self, site, args)
        except PineRuntimeError:
            raise
        except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            self.fail(f"`{target.name}()`: {exc}", node)

    def call_user(self, node: A.Call, fn: A.FunctionDef, binding: list, scope: Scope):
        path = self.ctx_path + (node.id,)
        if len(path) > MAX_CALL_DEPTH:
            self.fail("Function calls are nested too deeply.", node)
        values = [self.eval(arg, scope) if arg is not None else MISSING for _, arg in binding]
        saved = self.ctx_path
        self.ctx_path = path
        local = Scope(self.global_scope)
        try:
            for (param, _), value in zip(binding, values):
                if value is MISSING:
                    value = self.eval(param.default, local) if param.default is not None else NA
                buffer = self.buffer((path, param.id))
                buffer.set(self.bar, self.coerce(param.type, value, param))
                local.vars[param.name] = buffer
            return self.exec_body(fn.body.body, local)
        finally:
            self.ctx_path = saved

    # -- types ---------------------------------------------------------------------------------------------
    def coerce(self, type_ref: A.TypeRef | None, value, node):
        if type_ref is None or is_na(value):
            return value
        if type_ref.name == "float" and isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        if type_ref.name == "int" and isinstance(value, float):
            self.fail("Cannot assign a float value to an `int` variable (use int()).", node)
        return value


def float_or_na(value):
    if is_na(value):
        return NA
    value = float(value)
    return NA if math.isnan(value) or math.isinf(value) else value

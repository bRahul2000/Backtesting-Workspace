"""Security slices: the global statements a request.security() expression depends on (P2.1, conservative).

The requested context executes, on every requested bar, only the global statements that (transitively)
declare or reassign a variable the expression reads, in their original order, followed by the expression.
Accepted: variables, inputs, history, arithmetic/conditional logic, P1 ta.* state, tuples, user functions and
isolated scalar ``var`` / ``:=`` state. Rejected with a capability diagnostic (never approximated):

* an expression that reads local variables (P2.1 requests global expressions only);
* a request inside a user function whose expression depends on global variables;
* a dependency reassigned at or after the request.security() statement (execution order not provable);
* a dependency statement with side effects (plots, alerts, runtime.error, logs).

Arrays, maps, matrices, drawings and object mutation are already capability gaps of the whole script.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ast as A

SIDE_EFFECTS = {"alert", "alertcondition", "runtime.error"}


@dataclass
class SecurityCall:
    """A request.security() call as recorded by the analyzer."""

    node: A.Call
    expr: A.Node
    top_index: int | None                 # index of the global statement containing the call
    in_function: bool
    local_names: list[tuple[str, int]]    # (name, line) of local variables the expression reads
    symbol_literal: str | None
    timeframe_literal: str | None


@dataclass
class SecuritySpec:
    """What the runtime needs to execute a request.security() call in its requested context."""

    node_id: int
    line: int
    expr: A.Node
    body: tuple                           # slice statements + the expression statement
    slice_lines: tuple[int, ...]
    symbol_literal: str | None
    timeframe_literal: str | None
    tuple_size: int | None = None


@dataclass
class _StatementInfo:
    reads: set = field(default_factory=set)
    writes: set = field(default_factory=set)
    functions: set = field(default_factory=set)
    effects: list = field(default_factory=list)       # (construct, line)


def _info(node, names: dict, calls: dict, top_level: bool = True) -> _StatementInfo:
    info = _StatementInfo()
    if top_level and isinstance(node, A.VarDecl):
        info.writes.add(node.name)
    if top_level and isinstance(node, A.TupleDecl):
        info.writes.update(n for n in node.names if n != "_")
    for item in A.walk(node):
        if isinstance(item, A.Assign) and isinstance(item.target, A.Name):
            info.writes.add(item.target.name)
        elif isinstance(item, A.Name) and names.get(item.id, (None,))[0] == "user":
            info.reads.add(item.name)
        elif isinstance(item, A.Call) and item.id in calls:
            kind, target = calls[item.id][0], calls[item.id][1]
            if kind == "user":
                info.functions.add(target.name)
            elif target.kind == "output" or target.name in SIDE_EFFECTS or target.name.startswith("log."):
                info.effects.append((f"{target.name}()", item.line))
    return info


def _function_globals(functions: dict, names: dict, calls: dict) -> dict[str, set]:
    """Global variables each user function reads (transitively through the functions it calls)."""
    direct, callees = {}, {}
    for name, fn in functions.items():
        local = {p.name for p in fn.params}
        for item in A.walk(fn.body):
            if isinstance(item, A.VarDecl):
                local.add(item.name)
            elif isinstance(item, A.TupleDecl):
                local.update(item.names)
            elif isinstance(item, A.ForRange):
                local.add(item.var)
        info = _info(fn.body, names, calls, top_level=False)
        direct[name], callees[name] = info.reads - local, info.functions
    result = {}
    for name in functions:
        seen, stack, reads = set(), [name], set()
        while stack:
            current = stack.pop()
            if current in seen or current not in direct:
                continue
            seen.add(current)
            reads |= direct[current]
            stack.extend(callees[current])
        result[name] = reads
    return result


def build(script: A.Script, calls_recorded: list[SecurityCall], names: dict, calls: dict, functions: dict,
          gap) -> dict[int, SecuritySpec]:
    """SecuritySpec per request.security() call; ``gap(message, node)`` reports what cannot be sliced."""
    body = list(script.body)
    infos = [_info(statement, names, calls) for statement in body]
    fn_globals = _function_globals(functions, names, calls)
    specs: dict[int, SecuritySpec] = {}
    for call in calls_recorded:
        node, expr = call.node, call.expr
        if call.local_names:
            name, line = call.local_names[0]
            gap(f"request.security() on line {node.line}: the expression uses the local variable `{name}` (line "
                f"{line}); requesting expressions over local variables is not implemented yet.", node)
            continue
        expr_info = _info(expr, names, calls, top_level=False)
        need = set(expr_info.reads)
        for fn in expr_info.functions:
            need |= fn_globals.get(fn, set())
        if call.in_function or call.top_index is None:
            if need:
                gap(f"request.security() on line {node.line} inside a function depends on the global variable "
                    f"`{sorted(need)[0]}`; this is not implemented yet.", node)
                continue
            specs[node.id] = SecuritySpec(node.id, node.line, expr, (A.ExprStmt(expr.line, expr.col, expr=expr),), (),
                                          call.symbol_literal, call.timeframe_literal)
            continue
        position = call.top_index
        included: set[int] = set()
        changed = True
        while changed:
            changed = False
            for index in range(position):
                if index in included or not (infos[index].writes & need):
                    continue
                included.add(index)
                need |= infos[index].reads
                for fn in infos[index].functions:
                    need |= fn_globals.get(fn, set())
                changed = True
        problem = None
        for index in range(position, len(body)):
            late = infos[index].writes & need
            if late:
                problem = (f"request.security() on line {node.line}: `{sorted(late)[0]}` is reassigned on line "
                           f"{body[index].line}, at or after the request; this dependency order is not supported yet.")
                break
        if problem is None:
            for index in sorted(included):
                if infos[index].effects:
                    construct, line = infos[index].effects[0]
                    problem = (f"request.security() on line {node.line} depends on line {body[index].line}, which "
                               f"also calls `{construct}` (a side effect); this is not supported yet.")
                    break
        if problem is not None:
            gap(problem, node)
            continue
        statements = tuple(body[index] for index in sorted(included))
        specs[node.id] = SecuritySpec(
            node.id, node.line, expr, statements + (A.ExprStmt(expr.line, expr.col, expr=expr),),
            tuple(s.line for s in statements), call.symbol_literal, call.timeframe_literal)
    for item in A.walk(script):                          # `[a, b] = request.security(...)`: the tuple's size
        if isinstance(item, A.TupleDecl) and isinstance(item.value, A.Call) and item.value.id in specs:
            specs[item.value.id].tuple_size = len(item.names)
    for spec in specs.values():
        if spec.tuple_size is None and isinstance(spec.expr, A.TupleExpr):
            spec.tuple_size = len(spec.expr.items)
    return specs


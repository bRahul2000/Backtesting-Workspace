"""Pine AST. Every node carries its source position and a unique ``id``; the
runtime keys all per-call-site state (series history, built-in state, plot
outputs) by node id, so the tree itself stays immutable."""
from __future__ import annotations

from dataclasses import dataclass, field
import itertools

_ids = itertools.count(1)


@dataclass(eq=False)
class Node:
    line: int
    col: int
    id: int = field(default_factory=lambda: next(_ids), init=False, repr=False)


# ---- types ---------------------------------------------------------------------------

@dataclass(eq=False)
class TypeRef(Node):
    """A declared type: qualifier (const/input/simple/series) + name + generic args."""

    name: str = ""
    qualifier: str | None = None
    args: tuple["TypeRef", ...] = ()
    array_suffix: bool = False       # legacy ``float[]``


# ---- expressions ------------------------------------------------------------------------

@dataclass(eq=False)
class Literal(Node):
    value: object = None
    kind: str = ""                   # int | float | bool | string | color | na


@dataclass(eq=False)
class Name(Node):
    name: str = ""


@dataclass(eq=False)
class Attribute(Node):
    target: Node = None
    name: str = ""

    def dotted(self) -> str | None:
        """'ta.sma' for a pure dotted name, else None."""
        if isinstance(self.target, Name):
            return f"{self.target.name}.{self.name}"
        if isinstance(self.target, Attribute):
            base = self.target.dotted()
            return f"{base}.{self.name}" if base else None
        return None


@dataclass(eq=False)
class Argument(Node):
    value: Node = None
    name: str | None = None


@dataclass(eq=False)
class Call(Node):
    func: Node = None
    args: tuple[Argument, ...] = ()
    generic: tuple[TypeRef, ...] = ()


@dataclass(eq=False)
class History(Node):
    target: Node = None
    offset: Node = None


@dataclass(eq=False)
class Unary(Node):
    op: str = ""
    operand: Node = None


@dataclass(eq=False)
class Binary(Node):
    op: str = ""
    left: Node = None
    right: Node = None


@dataclass(eq=False)
class Ternary(Node):
    condition: Node = None
    then: Node = None
    otherwise: Node = None


@dataclass(eq=False)
class TupleExpr(Node):
    items: tuple[Node, ...] = ()


# ---- statements (some are also expressions: if/switch/for/while blocks) --------------------

@dataclass(eq=False)
class Block(Node):
    body: tuple[Node, ...] = ()


@dataclass(eq=False)
class VarDecl(Node):
    name: str = ""
    value: Node = None
    mode: str | None = None          # None | "var" | "varip"
    type: TypeRef | None = None


@dataclass(eq=False)
class TupleDecl(Node):
    names: tuple[str, ...] = ()
    value: Node = None


@dataclass(eq=False)
class Assign(Node):
    target: Node = None              # Name or Attribute (object field)
    op: str = ":="                   # := += -= *= /= %=
    value: Node = None


@dataclass(eq=False)
class If(Node):
    condition: Node = None
    body: Block = None
    orelse: Block | None = None      # an ``else if`` is an If inside a one-statement Block


@dataclass(eq=False)
class ForRange(Node):
    var: str = ""
    start: Node = None
    end: Node = None
    step: Node | None = None
    body: Block = None


@dataclass(eq=False)
class ForIn(Node):
    names: tuple[str, ...] = ()      # (item,) or (index, item)
    iterable: Node = None
    body: Block = None


@dataclass(eq=False)
class While(Node):
    condition: Node = None
    body: Block = None


@dataclass(eq=False)
class Case(Node):
    match: Node | None = None        # None = default branch
    body: Block = None


@dataclass(eq=False)
class Switch(Node):
    subject: Node | None = None
    cases: tuple[Case, ...] = ()


@dataclass(eq=False)
class Break(Node):
    pass


@dataclass(eq=False)
class Continue(Node):
    pass


@dataclass(eq=False)
class Param(Node):
    name: str = ""
    default: Node | None = None
    type: TypeRef | None = None


@dataclass(eq=False)
class FunctionDef(Node):
    name: str = ""
    params: tuple[Param, ...] = ()
    body: Block = None
    is_method: bool = False
    exported: bool = False


@dataclass(eq=False)
class TypeDef(Node):
    name: str = ""
    fields: tuple[VarDecl, ...] = ()
    exported: bool = False
    is_enum: bool = False


@dataclass(eq=False)
class Import(Node):
    path: str = ""
    alias: str | None = None


@dataclass(eq=False)
class ExprStmt(Node):
    expr: Node = None


@dataclass(eq=False)
class Script(Node):
    body: tuple[Node, ...] = ()
    annotations: dict = field(default_factory=dict)
    version: int | None = None


def walk(node):
    """Yield node and all descendants (depth first)."""
    stack = [node]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        yield current
        for value in vars(current).values():
            if isinstance(value, Node):
                stack.append(value)
            elif isinstance(value, (tuple, list)):
                stack.extend(item for item in reversed(value) if isinstance(item, Node))

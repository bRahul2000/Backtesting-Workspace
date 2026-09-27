"""Semantic analysis: scopes, name/call resolution, types and capability gaps.

The analyzer turns an AST into a ``Program`` the runtime can execute without
guessing: every name and call is resolved statically (user variable, built-in
variable/constant, built-in function binding or user-function binding).
Anything that is valid Pine but not implemented becomes a ``gap`` diagnostic
naming the feature and the line; anything that is not valid Pine becomes an
``error`` worded like Pine's own messages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import ast as A
from . import catalog, slicing
from .compat import FEATURES, feature_for_builtin
from .errors import ERROR, GAP, WARNING, Diagnostic
from .registry import CONSTANTS, FUNCTIONS, QUALIFIER_RANK, VARIABLES, Builtin, TypeSpec, bind, load_all
from .values import NA, Color

BASIC_TYPES = {"int", "float", "bool", "string", "color"}
NUMERIC = {"int", "float"}
DECLARATIONS = {"indicator", "strategy", "library"}
SOURCE_NAMES = ("open", "high", "low", "close", "volume", "hl2", "hlc3", "ohlc4", "hlcc4")
TYPE_GAPS = {"line": "drawing-objects", "label": "drawing-objects", "box": "drawing-objects", "table": "drawing-objects",
             "linefill": "drawing-objects", "polyline": "drawing-objects", "array": "arrays", "matrix": "matrices",
             "map": "maps", "chart.point": "drawing-objects"}


@dataclass
class InputDef:
    index: int
    node_id: int
    kind: str                     # int | float | bool | string | color | source | timeframe | price | text_area
    title: str
    defval: Any
    options: list | None = None
    minval: float | None = None
    maxval: float | None = None
    step: float | None = None
    tooltip: str | None = None
    group: str | None = None
    line: int = 0

    def as_dict(self) -> dict:
        defval = self.defval.css() if isinstance(self.defval, Color) else self.defval
        return {"index": self.index, "kind": self.kind, "title": self.title, "defval": defval, "options": self.options,
                "minval": self.minval, "maxval": self.maxval, "step": self.step, "tooltip": self.tooltip,
                "group": self.group, "line": self.line}


@dataclass
class Program:
    script: A.Script
    meta: dict
    functions: dict[str, A.FunctionDef]
    calls: dict[int, tuple]
    names: dict[int, tuple]
    inputs: list[InputDef]
    outputs: list[int]
    features: dict[str, list[int]] = field(default_factory=dict)
    builtins_used: dict[str, list[int]] = field(default_factory=dict)
    int_division: set[int] = field(default_factory=set)   # v5 `const int / const int` nodes (truncating)
    security: dict[int, Any] = field(default_factory=dict)  # request.security() node id -> slicing.SecuritySpec
    uses_arrays: bool = False     # the runtime snapshots arrays at the end of each execution only when True


@dataclass
class VarInfo:
    type: TypeSpec | None
    function_local: bool
    is_param: bool = False
    loop_item: bool = False      # a `for ... in` variable: read-only (TradingView CE10174)


class Analyzer:
    def __init__(self, script: A.Script):
        load_all()
        self.script = script
        self.diagnostics: list[Diagnostic] = []
        self.scopes: list[dict[str, VarInfo]] = [{}]
        self.functions: dict[str, A.FunctionDef] = {}
        self.defining: str | None = None
        self.function_depth = 0
        self.local_depth = 0
        self.loop_depth = 0
        self.calls: dict[int, tuple] = {}
        self.names: dict[int, tuple] = {}
        self.inputs: list[InputDef] = []
        self.outputs: list[int] = []
        self.features: dict[str, list[int]] = {}
        self.builtins_used: dict[str, list[int]] = {}
        self.int_division: set[int] = set()
        self.security_calls: list = []
        self.uses_arrays = False
        self.top_index: int | None = None
        self.meta: dict = {}

    # -- diagnostics --------------------------------------------------------------------------------
    def error(self, message: str, node: A.Node) -> None:
        self.diagnostics.append(Diagnostic(ERROR, message, node.line, node.col))

    def gap(self, feature: str, message: str, node: A.Node) -> None:
        self.feature(feature, node)
        self.diagnostics.append(Diagnostic(GAP, message, node.line, node.col, feature))

    def warn(self, message: str, node: A.Node) -> None:
        self.diagnostics.append(Diagnostic(WARNING, message, node.line, node.col))

    def feature(self, feature: str, node: A.Node) -> None:
        lines = self.features.setdefault(feature, [])
        if node.line not in lines:
            lines.append(node.line)

    # -- entry --------------------------------------------------------------------------------------
    def analyze(self) -> tuple[Program, list[Diagnostic]]:
        self.check_version()
        self.check_declaration()
        for index, statement in enumerate(self.script.body):
            self.top_index = index
            self.statement(statement)
        self.top_index = None
        security = slicing.build(self.script, self.security_calls, self.names, self.calls, self.functions,
                                 lambda message, node: self.gap("request", message, node))
        program = Program(self.script, self.meta, self.functions, self.calls, self.names, self.inputs, self.outputs,
                          self.features, self.builtins_used, self.int_division, security, self.uses_arrays)
        return program, sorted(self.diagnostics, key=lambda d: (d.line, d.col))

    def check_version(self) -> None:
        version = self.script.version
        if version is None:
            self.warn("No `//@version` annotation; the script is treated as Pine v5.", self.script)
        elif version < 5:
            self.gap("version", f"Pine v{version} scripts are not translated yet; convert the script to v5 or v6.", self.script)
        elif version > 6:
            self.gap("version", f"Pine v{version} is not known to this engine (v5 and v6 are).", self.script)
        self.feature("syntax", self.script)

    def check_declaration(self) -> None:
        declarations = [s for s in self.script.body if isinstance(s, A.ExprStmt) and isinstance(s.expr, A.Call)
                        and isinstance(s.expr.func, A.Name) and s.expr.func.name in DECLARATIONS]
        if not declarations:
            self.error("The script must declare its type with `indicator()`, `strategy()` or `library()`.", self.script)
            return
        if len(declarations) > 1:
            self.error("Only one declaration statement (`indicator()`/`strategy()`/`library()`) is allowed.", declarations[1])
        call = declarations[0].expr
        kind = call.func.name
        if kind == "strategy":
            self.gap("strategy", "`strategy()` scripts are not implemented yet (strategy.* order simulation); "
                                 "use `indicator()`.", call)
        elif kind == "library":
            self.gap("libraries", "`library()` scripts are not implemented yet.", call)
        positional = [a.value for a in call.args if a.name is None]
        named = {a.name: a.value for a in call.args if a.name is not None}
        order = ("title", "shorttitle", "overlay", "format", "precision", "scale", "max_bars_back")

        def arg(name, default=None):
            node = named.get(name)
            if node is None and name in order and order.index(name) < len(positional):
                node = positional[order.index(name)]
            return default if node is None else self.const_value(node, name)

        title = arg("title")
        if not isinstance(title, str) or not title:
            self.error(f"`{kind}()` needs a constant string title.", call)
            title = "Untitled"
        self.meta = {"kind": kind, "title": title, "shorttitle": arg("shorttitle") or title,
                     "overlay": bool(arg("overlay", False)), "precision": arg("precision"),
                     "format": arg("format"), "max_bars_back": arg("max_bars_back"), "version": self.script.version or 5}

    # -- scopes -----------------------------------------------------------------------------------------
    def lookup(self, name: str) -> tuple[VarInfo | None, int]:
        for depth in range(len(self.scopes) - 1, -1, -1):
            info = self.scopes[depth].get(name)
            if info is not None:
                return info, depth
        return None, -1

    def declare(self, name: str, info: VarInfo, node: A.Node) -> None:
        if name in self.scopes[-1]:
            self.error(f"`{name}` is already declared in this scope; use `:=` to reassign it.", node)
        self.scopes[-1][name] = info

    def in_scope(self, fn):
        self.scopes.append({})
        self.local_depth += 1
        try:
            return fn()
        finally:
            self.scopes.pop()
            self.local_depth -= 1

    # -- statements ---------------------------------------------------------------------------------------
    def statement(self, node: A.Node) -> TypeSpec | None:
        if isinstance(node, A.VarDecl):
            return self.var_decl(node)
        if isinstance(node, A.TupleDecl):
            self.feature("tuples", node)
            self.expr(node.value)
            for name in node.names:
                if name != "_":
                    self.declare(name, VarInfo(None, self.function_depth > 0), node)
            return None
        if isinstance(node, A.Assign):
            return self.assign(node)
        if isinstance(node, A.ExprStmt):
            return self.expr(node.expr)
        if isinstance(node, A.FunctionDef):
            return self.function_def(node)
        if isinstance(node, A.TypeDef):
            if node.is_enum:
                self.gap("enums", f"Enums (`enum {node.name}`) are not implemented yet.", node)
            else:
                self.gap("user-defined-types", f"User-defined types (`type {node.name}`) are not implemented yet.", node)
            return None
        if isinstance(node, A.Import):
            self.gap("libraries", f"Libraries (`import {node.path}`) are not implemented yet.", node)
            return None
        if isinstance(node, (A.Break, A.Continue)):
            self.feature("break-continue", node)
            if self.loop_depth == 0:
                self.error(f"`{'break' if isinstance(node, A.Break) else 'continue'}` can only be used inside a loop.", node)
            return None
        return self.expr(node)

    def var_decl(self, node: A.VarDecl) -> TypeSpec | None:
        self.feature("declarations", node)
        if node.mode:
            self.feature(node.mode, node)
        declared = self.type_ref(node.type) if node.type is not None else None
        value_type = self.expr(node.value)
        if declared is not None and value_type is not None and not self.assignable(value_type, declared):
            self.error(f"Cannot assign a value of type `{value_type.base}` to `{node.name}` declared as `{declared.base}`.", node)
        spec = declared or value_type
        if spec is not None and node.mode:
            spec = TypeSpec("series", spec.base)
        self.declare(node.name, VarInfo(spec, self.function_depth > 0), node)
        return spec

    def assign(self, node: A.Assign) -> TypeSpec | None:
        self.feature("reassignment", node)
        value_type = self.expr(node.value)
        if isinstance(node.target, A.Attribute):
            self.gap("user-defined-types", "Assigning to an object field (`obj.field := ...`) requires user-defined types, "
                                           "which are not implemented yet.", node)
            return None
        name = node.target.name
        info, depth = self.lookup(name)
        if info is None:
            self.error(f"Undeclared identifier `{name}`: declare it with `=` before reassigning it with `:=`.", node)
            return None
        if self.function_depth > 0 and not info.function_local:
            self.error(f"Cannot modify global variable `{name}` in a function.", node)
        if info.loop_item:
            # TradingView CE10174, observed for both `for [i, x] in` variables (q6c_i, q6c_x)
            self.error(f'Variable "{name}" cannot be mutable: `for ... in` loop variables are read-only.', node)
        if info.is_param and info.type is not None and info.type.base.startswith("array<"):
            # TradingView CE10175, observed for an array parameter (scalar parameters: not verified, unchanged)
            self.error(f"Function arguments cannot be mutable (`{name}`).", node)
        if info.type is not None and value_type is not None and not self.assignable(value_type, info.type):
            self.error(f"Cannot assign a value of type `{value_type.base}` to `{name}` of type `{info.type.base}`.", node)
        self.names[node.target.id] = ("user", name)
        return info.type

    def function_def(self, node: A.FunctionDef) -> None:
        if node.is_method:
            self.gap("methods", f"Methods (`method {node.name}`) are not implemented yet.", node)
            return None
        if self.local_depth > 0:
            self.error("Functions can only be declared in the global scope.", node)
            return None
        if node.name in self.functions:
            self.gap("function-overloads", f"Overloading the function `{node.name}` is not implemented yet.", node)
            return None
        if node.name in FUNCTIONS or catalog.is_known_function(node.name):
            self.warn(f"The function `{node.name}` shadows a built-in.", node)
        self.feature("functions", node)
        self.defining = node.name
        self.function_depth += 1

        def body():
            for param in node.params:
                if param.default is not None:
                    self.expr(param.default)
                spec = self.type_ref(param.type) if param.type is not None else None
                self.declare(param.name, VarInfo(spec, True, is_param=True), param)
            for statement in node.body.body:
                self.statement(statement)

        try:
            self.in_scope(body)
        finally:
            self.function_depth -= 1
            self.defining = None
        self.functions[node.name] = node
        return None

    def type_ref(self, ref: A.TypeRef) -> TypeSpec | None:
        array_type = self.array_type_ref(ref)
        if array_type is not False:
            return array_type
        name = "array" if ref.array_suffix else ref.name
        if ref.args or ref.array_suffix:
            self.gap("generics" if ref.args else "arrays", f"The type `{ref.name}{'[]' if ref.array_suffix else '<...>'}` "
                     f"is not implemented yet ({FEATURES[TYPE_GAPS.get(name, 'generics')].description}).", ref)
            return None
        if name in TYPE_GAPS:
            feature = TYPE_GAPS[name]
            self.gap(feature, f"Variables of type `{name}` are not implemented yet ({FEATURES[feature].description}).", ref)
            return None
        if name not in BASIC_TYPES:
            self.gap("user-defined-types", f"The type `{name}` needs user-defined types, which are not implemented yet.", ref)
            return None
        return TypeSpec(ref.qualifier or "series", name)

    def array_type_ref(self, ref: A.TypeRef):
        """`array<T>` / `T[]` for the A1 element types; False when `ref` is not an array type."""
        if ref.array_suffix and not ref.args:
            element = ref.name
        elif ref.name == "array" and len(ref.args) == 1 and not ref.array_suffix:
            inner = ref.args[0]
            if inner.args or inner.array_suffix:
                self.gap("arrays", "Arrays of arrays / nested collections are not implemented yet.", ref)
                return None
            element = inner.name
        elif ref.name == "array":
            self.gap("arrays", "`array` needs exactly one element type (`array<float>`).", ref)
            return None
        else:
            return False
        if element not in BASIC_TYPES:
            feature = TYPE_GAPS.get(element, "user-defined-types")
            self.gap(feature if feature != "arrays" else "arrays",
                     f"Arrays of `{element}` are not implemented yet ({FEATURES[feature].description}).", ref)
            return None
        self.uses_arrays = True
        self.feature("arrays", ref)
        return TypeSpec(ref.qualifier or "series", f"array<{element}>")

    # -- expressions -----------------------------------------------------------------------------------------
    def expr(self, node: A.Node) -> TypeSpec | None:
        if isinstance(node, A.Literal):
            if node.kind == "color":
                self.feature("color", node)
            return TypeSpec("const", node.kind) if node.kind != "na" else None
        if isinstance(node, (A.Name, A.Attribute)):
            return self.name(node)
        if isinstance(node, A.Call):
            return self.call(node)
        if isinstance(node, A.History):
            self.feature("history", node)
            target = self.expr(node.target)
            offset = self.expr(node.offset)
            if offset is not None and offset.base not in NUMERIC:
                self.error("A history reference offset must be an integer.", node.offset)
            if isinstance(node.offset, A.Unary) and node.offset.op == "-":
                self.error("A history reference offset cannot be negative.", node.offset)
            return TypeSpec("series", target.base) if target is not None else None
        if isinstance(node, A.Unary):
            operand = self.expr(node.operand)
            if operand is None:
                return None
            if node.op == "not":
                return TypeSpec(operand.qualifier, "bool")
            if operand.base not in NUMERIC:
                self.error(f"Operator `{node.op}` cannot be applied to a `{operand.base}`.", node)
            return operand
        if isinstance(node, A.Binary):
            return self.binary(node)
        if isinstance(node, A.Ternary):
            self.feature("ternary", node)
            condition = self.expr(node.condition)
            then, otherwise = self.expr(node.then), self.expr(node.otherwise)
            return self.merge(then, otherwise, condition)
        if isinstance(node, A.TupleExpr):
            self.feature("tuples", node)
            for item in node.items:
                self.expr(item)
            return None
        if isinstance(node, A.If):
            self.feature("if", node)
            self.expr(node.condition)
            result = self.in_scope(lambda: self.block(node.body))
            if node.orelse is not None:
                other = self.in_scope(lambda: self.block(node.orelse))
                return self.merge(result, other)
            return result
        if isinstance(node, A.Switch):
            self.feature("switch", node)
            if node.subject is not None:
                self.expr(node.subject)
            results = []
            for case in node.cases:
                if case.match is not None:
                    self.expr(case.match)
                results.append(self.in_scope(lambda case=case: self.block(case.body)))
            return results[0] if results and all(r == results[0] for r in results) else None
        if isinstance(node, A.ForRange):
            self.feature("for", node)
            for part in (node.start, node.end, node.step):
                if part is not None:
                    self.expr(part)
            return self.loop(node, lambda: self.declare(node.var, VarInfo(TypeSpec("series", "int"), self.function_depth > 0), node))
        if isinstance(node, A.While):
            self.feature("while", node)
            self.expr(node.condition)
            return self.loop(node, lambda: None)
        if isinstance(node, A.ForIn):
            return self.for_in(node)
        self.error(f"Unexpected `{type(node).__name__}` here.", node)
        return None

    def for_in(self, node: A.ForIn) -> None:
        """`for x in a` / `for [i, x] in a` over an array (P22_FORIN_EVIDENCE.md); maps and matrices are gaps."""
        self.feature("for-in", node)
        iterable = self.expr(node.iterable)
        element = None
        if iterable is not None:
            if iterable.base.startswith("array<"):
                element = TypeSpec("series", iterable.base[6:-1])
            elif iterable.base in NUMERIC or iterable.base in ("bool", "string", "color"):
                self.error(f"`for ... in` needs an array; `{iterable.base}` cannot be iterated.", node.iterable)
            else:
                self.gap("for-in", f"`for ... in` over `{iterable.base}` is not implemented yet (arrays only).", node)
        local = self.function_depth > 0

        def declare():
            types = (TypeSpec("series", "int"), element) if len(node.names) == 2 else (element,)
            for name, spec in zip(node.names, types):
                if name != "_":
                    self.declare(name, VarInfo(spec, local, loop_item=True), node)

        return self.loop(node, declare)

    def loop(self, node, declare) -> None:
        self.loop_depth += 1

        def body():
            declare()
            return self.block(node.body)

        try:
            self.in_scope(body)
        finally:
            self.loop_depth -= 1
        return None

    def block(self, block: A.Block) -> TypeSpec | None:
        result = None
        for statement in block.body:
            result = self.statement(statement)
        return result

    def binary(self, node: A.Binary) -> TypeSpec | None:
        left, right = self.expr(node.left), self.expr(node.right)
        qualifier = self.max_qualifier(left, right)
        if node.op in ("and", "or"):
            return TypeSpec(qualifier, "bool")
        if node.op in ("==", "!=") and any(t is not None and t.base.startswith("array<") for t in (left, right)):
            self.error(f"Cannot compare arrays with `{node.op}`: array operands are not supported by this operator.",
                       node)
            return TypeSpec(qualifier, "bool")
        if node.op in ("==", "!=", "<", ">", "<=", ">="):
            if node.op not in ("==", "!=") and left is not None and right is not None and (
                    left.base not in NUMERIC or right.base not in NUMERIC):
                self.error(f"Cannot compare `{left.base}` and `{right.base}` with `{node.op}`.", node)
            return TypeSpec(qualifier, "bool")
        if left is None or right is None:
            return None
        if node.op == "+" and (left.base == "string" or right.base == "string"):
            if left.base != right.base:
                self.error(f"Cannot add `{left.base}` and `{right.base}` (convert with str.tostring()).", node)
            return TypeSpec(qualifier, "string")
        if left.base not in NUMERIC or right.base not in NUMERIC:
            self.error(f"Operator `{node.op}` cannot be applied to `{left.base}` and `{right.base}`.", node)
            return None
        if node.op == "/" and left.base == right.base == "int":
            # v5 divides two `const int` values with truncation; v6 always keeps the fraction
            if (self.script.version or 5) < 6 and left.qualifier == right.qualifier == "const":
                self.int_division.add(node.id)
                return TypeSpec(qualifier, "int")
            return TypeSpec(qualifier, "float")
        base = "int" if left.base == right.base == "int" else "float"
        return TypeSpec(qualifier, base)

    def name(self, node) -> TypeSpec | None:
        if isinstance(node, A.Name):
            info, _ = self.lookup(node.name)
            if info is not None:
                self.names[node.id] = ("user", node.name)
                return info.type
            return self.builtin_name(node, node.name)
        if isinstance(node.target, A.Name) and self.lookup(node.target.name)[0] is not None:
            self.gap("user-defined-types", f"Field access `{node.target.name}.{node.name}` requires user-defined types, "
                                           "which are not implemented yet.", node)
            return None
        dotted = node.dotted()
        if dotted is None:
            self.expr(node.target)
            self.gap("user-defined-types", f"Field access `.{node.name}` requires user-defined types, which are not "
                                           "implemented yet.", node)
            return None
        return self.builtin_name(node, dotted)

    def builtin_name(self, node, name: str) -> TypeSpec | None:
        if name in VARIABLES:
            variable = VARIABLES[name]
            self.names[node.id] = ("var", variable)
            self.builtins_used.setdefault(name, []).append(node.line)
            self.feature(feature_for_builtin(name) if "." in name else "declarations", node)
            return TypeSpec.parse(variable.returns)
        if name in CONSTANTS:
            value, type_ = CONSTANTS[name]
            self.names[node.id] = ("const", value)
            if value is NA:
                return None
            return TypeSpec.parse(type_)
        if catalog.is_known_variable(name):
            feature = feature_for_builtin(name)
            self.gap(feature, f"`{name}` is not implemented yet.", node)
            return None
        if name in FUNCTIONS or name in self.functions or catalog.is_known_function(name):
            self.error(f"`{name}` is a function; call it with `{name}(...)`.", node)
            return None
        if name == self.defining:
            self.error(f"`{name}` cannot reference itself.", node)
            return None
        namespace = catalog.namespace_of(name)
        if namespace and (namespace in catalog.CONSTANT_NAMESPACES or any(k.startswith(namespace + ".") for k in catalog.KNOWN_FUNCTIONS)):
            self.error(f"Could not find `{name}` (no such member of `{namespace}`).", node)
        else:
            self.error(f"Undeclared identifier `{name}`.", node)
        return None

    def call(self, node: A.Call) -> TypeSpec | None:
        func = node.func
        if isinstance(func, A.Attribute) and (
                not isinstance(func.target, (A.Name, A.Attribute))
                or isinstance(func.target, A.Name) and self.lookup(func.target.name)[0] is not None):
            return self.method_call(node, func)
        name = func.name if isinstance(func, A.Name) else func.dotted() if isinstance(func, A.Attribute) else None
        if name is None:
            self.error("Only functions can be called.", node)
            return None
        positional = [a.value for a in node.args if a.name is None]
        named = {a.name: a.value for a in node.args if a.name is not None}
        seen_named = False
        for argument in node.args:
            if argument.name is not None:
                seen_named = True
            elif seen_named:
                self.error("Positional arguments cannot follow named arguments.", argument)
        if isinstance(func, A.Name) and name in self.functions:
            return self.user_call(node, self.functions[name], positional, named)
        if isinstance(func, A.Name) and name == self.defining:
            self.error(f"Recursive calls are not allowed (`{name}` calls itself).", node)
            return None
        if node.generic:
            element = node.generic[0].name if len(node.generic) == 1 and not node.generic[0].args \
                and not node.generic[0].array_suffix else None
            if name == "array.new" and element in BASIC_TYPES:
                name = f"array.new_{element}"              # array.new<float>() is array.new_float()
            elif name == "array.new" and element is not None and element in TYPE_GAPS:
                feature = TYPE_GAPS[element]
                self.gap(feature, f"Arrays of `{element}` are not implemented yet ({FEATURES[feature].description}).",
                         node)
                for argument in node.args:
                    self.expr(argument.value)
                return None
            else:
                self.gap("generics", f"Generic calls (`{name}<...>()`) are not implemented yet.", node)
        builtin_ = FUNCTIONS.get(name)
        if builtin_ is None:
            for argument in node.args:
                self.expr(argument.value)
            if name in DECLARATIONS:
                return None
            if catalog.is_known_function(name):
                feature = feature_for_builtin(name)
                self.gap(feature, gap_message(name, feature), node)
            else:
                self.error(f"Could not find function or function reference `{name}`.", node)
            return None
        return self.builtin_call(node, builtin_, positional, named)

    def method_call(self, node: A.Call, func: A.Attribute) -> TypeSpec | None:
        """Built-in method syntax: `a.push(x)` is `array.push(a, x)` (Pine docs: the two forms are equivalent). The
        receiver becomes the builtin's first argument, so the call reuses the namespace builtin unchanged."""
        receiver = self.expr(func.target)
        base = receiver.base if receiver is not None else None
        inner = self.calls.get(func.target.id) if isinstance(func.target, A.Call) else None
        if inner is not None and inner[0] == "builtin" and inner[1].returns == "void":
            for argument in node.args:
                self.expr(argument.value)
            self.error(f"Cannot call method `{func.name}()`: `{inner[1].name}()` does not return a value.", node)
            return None
        if base is not None and base in NUMERIC | {"bool", "string", "color"}:
            for argument in node.args:
                self.expr(argument.value)
            self.error(f"Could not find method `{func.name}()` for a `{base}` value.", node)
            return None
        if base is not None and not base.startswith("array"):
            for argument in node.args:
                self.expr(argument.value)
            self.gap("methods", f"Method calls on `{base}` values (`.{func.name}()`) are not implemented yet.", node)
            return None
        # arrays are the only values with built-in methods in this engine; a receiver of unknown type (a user
        # function's result, an untyped parameter) is dispatched to `array.*` and checked at run time
        name = f"array.{func.name}"
        builtin_ = FUNCTIONS.get(name)
        if builtin_ is None:
            for argument in node.args:
                self.expr(argument.value)
            if catalog.is_known_function(name):
                feature = feature_for_builtin(name)
                self.gap(feature, gap_message(name, feature), node)
            else:
                self.error(f"Could not find method `{func.name}()` for arrays.", node)
            return None
        self.feature("builtin-methods", node)
        positional = [func.target] + [a.value for a in node.args if a.name is None]
        named = {a.name: a.value for a in node.args if a.name is not None}
        return self.builtin_call(node, builtin_, positional, named, receiver=(func.target, receiver))

    def user_call(self, node: A.Call, fn: A.FunctionDef, positional: list, named: dict) -> TypeSpec | None:
        params = fn.params
        if len(positional) > len(params):
            self.error(f"Too many arguments for `{fn.name}` ({len(positional)} given, {len(params)} expected).", node)
        binding = []
        for index, param in enumerate(params):
            arg = positional[index] if index < len(positional) else named.get(param.name)
            if arg is None and param.default is None:
                self.error(f"Missing argument `{param.name}` for `{fn.name}`.", node)
            binding.append((param, arg))
        for name in named:
            if name not in {p.name for p in params}:
                self.error(f"`{fn.name}` has no parameter `{name}`.", node)
        for argument in node.args:
            self.expr(argument.value)
        self.calls[node.id] = ("user", fn, binding)
        return None

    def builtin_call(self, node: A.Call, builtin_: Builtin, positional: list, named: dict,
                     receiver: tuple | None = None) -> TypeSpec | None:
        self.builtins_used.setdefault(builtin_.name, []).append(node.line)
        self.feature(self.builtin_feature(builtin_), node)
        arg_types = {id(a.value): self.expr(a.value) for a in node.args}
        if receiver is not None:                  # method syntax: the receiver is the first argument, already typed
            arg_types[id(receiver[0])] = receiver[1]
        binding, problem = bind(builtin_, positional, named,
                                lambda param, node: self.fits(param, arg_types.get(id(node))))
        if binding is None:
            self.error(f"Cannot call `{builtin_.name}`: {problem}.", node)
            return None
        if builtin_.kind in ("output", "input") and (self.local_depth > 0 or self.function_depth > 0):
            self.error(f"Cannot use `{builtin_.name}` in local scope.", node)
        for param in binding.params:
            arg = binding.nodes.get(param.name)
            if arg is not None:
                self.check_argument(builtin_, param, arg, arg_types.get(id(arg)))
        self.calls[node.id] = ("builtin", builtin_, binding)
        if builtin_.kind == "security":
            return self.security_call(node, binding, arg_types)
        if builtin_.kind == "output":
            self.outputs.append(node.id)
        elif builtin_.kind == "input":
            self.input_def(node, builtin_, binding)
        if builtin_.note:
            self.warn(f"`{builtin_.name}`: {builtin_.note}", node)
        if builtin_.name.startswith("array."):
            self.uses_arrays = True
            return self.array_result(builtin_, binding, arg_types)
        return TypeSpec.parse(builtin_.returns) if builtin_.returns not in ("void", "tuple") else None

    def security_call(self, node: A.Call, binding, arg_types: dict) -> TypeSpec | None:
        """request.security(): record the call for slicing; validate literal timeframes now."""
        from .security import LIMIT, SecurityDataError, parse_timeframe

        expr = binding.nodes.get("expression")
        local = []
        for item in A.walk(expr):
            if isinstance(item, A.Name) and self.names.get(item.id, (None,))[0] == "user":
                info, depth = self.lookup(item.name)
                if info is not None and depth != 0:
                    local.append((item.name, item.line))

        def literal(name):
            value = binding.nodes.get(name)
            return value.value if isinstance(value, A.Literal) and value.kind == "string" else None

        timeframe = literal("timeframe")
        if timeframe is not None and timeframe != "":
            try:
                parse_timeframe(timeframe)
            except SecurityDataError as exc:
                if exc.message.startswith(LIMIT):
                    self.gap("request", f"request.security(): {exc.message}", binding.nodes["timeframe"])
                else:
                    self.error(f"request.security(): {exc.message}", binding.nodes["timeframe"])
        self.security_calls.append(slicing.SecurityCall(node, expr, self.top_index, self.function_depth > 0, local,
                                                        literal("symbol"), timeframe))
        result = arg_types.get(id(expr))
        return TypeSpec("series", result.base) if result is not None else None

    def array_result(self, builtin_: Builtin, binding, arg_types: dict) -> TypeSpec | None:
        """Result type of an array builtin (element / same array / array.from), plus the element check."""
        def arg_type(name):
            node = binding.nodes.get(name)
            return arg_types.get(id(node)) if node is not None else None

        array_type = arg_type("id")
        element = array_type.base[6:-1] if array_type is not None and array_type.base.startswith("array<") else None
        value_type = arg_type("value")
        if element is not None and value_type is not None and not self.assignable(value_type, TypeSpec("series", element)):
            self.error(f"Cannot call `{builtin_.name}` with argument `value`: a `{value_type.base}` was used but the "
                       f"array holds `{element}`.", binding.nodes["value"])
        returns = builtin_.returns
        if returns == "element":
            return TypeSpec("series", element) if element is not None else None
        if returns == "same_array":
            return TypeSpec("series", array_type.base) if array_type is not None else None
        if returns == "array_from":
            types = [arg_type("value0")] + [arg_types.get(id(n)) for n in binding.extra]
            bases = {t.base for t in types if t is not None}
            if not bases:
                return None
            if bases <= NUMERIC:
                return TypeSpec("series", "array<int>" if bases == {"int"} else "array<float>")
            if len(bases) == 1 and next(iter(bases)) in BASIC_TYPES:
                return TypeSpec("series", f"array<{next(iter(bases))}>")
            self.error("`array.from()` needs values of one type.", binding.nodes.get("value0"))
            return None
        return TypeSpec.parse(returns) if returns not in ("void", "tuple") else None

    def builtin_feature(self, builtin_: Builtin) -> str:
        if builtin_.kind == "output":
            return {"plot": "plot", "plotshape": "plotshape", "plotchar": "plotchar", "hline": "hline", "fill": "fill",
                    "bgcolor": "bgcolor", "barcolor": "barcolor"}.get(builtin_.name, "plot")
        if builtin_.name in ("alert", "alertcondition"):
            return "alerts"
        if builtin_.name.startswith("color.") or builtin_.name == "color":
            return "color"
        if builtin_.name in ("time", "timestamp", "year", "month", "weekofyear", "dayofmonth", "dayofweek", "hour",
                             "minute", "second", "time_close"):
            return "time"
        feature = feature_for_builtin(builtin_.name)
        return feature if feature in FEATURES else "declarations"

    @staticmethod
    def fits(param, actual: TypeSpec | None) -> bool:
        """Base-type compatibility only (qualifiers are checked after binding)."""
        expected = param.spec
        if actual is None or expected.base in ("any", "plot", "hline", "tuple"):
            return True
        if expected.base in NUMERIC:
            return actual.base in NUMERIC
        if expected.base == "bool":
            return actual.base in ("bool", "int", "float")
        if expected.base == "array":                       # any array<T>
            return actual.base.startswith("array<")
        return actual.base == expected.base

    def check_argument(self, builtin_: Builtin, param, arg: A.Node, actual: TypeSpec | None) -> None:
        """Pine-style type and qualifier checks, only where the argument type is known."""
        expected = param.spec
        if actual is None or expected.base in ("any", "plot", "hline", "tuple"):
            return
        mismatch = not self.fits(param, actual)
        too_variable = QUALIFIER_RANK.get(actual.qualifier, 3) > QUALIFIER_RANK.get(expected.qualifier, 3)
        if mismatch or too_variable:
            self.error(f"Cannot call `{builtin_.name}` with argument `{param.name}`: a `{actual.qualifier} {actual.base}` "
                       f"was used but a `{expected}` is expected.", arg)

    # -- inputs -------------------------------------------------------------------------------------------
    def input_def(self, node: A.Call, builtin_: Builtin, binding) -> None:
        kind = builtin_.name.split(".")[1] if "." in builtin_.name else None
        get = lambda name: binding.nodes.get(name)  # noqa: E731
        defval_node = get("defval")
        if kind == "source":
            defval = self.source_name(defval_node) if defval_node is not None else "close"
        else:
            defval = self.const_value(defval_node, "defval") if defval_node is not None else None
        if kind is None:  # plain input(): type from the default value
            if isinstance(defval_node, (A.Name, A.Attribute)) and self.source_name(defval_node, quiet=True):
                kind, defval = "source", self.source_name(defval_node)
            else:
                kind = ("bool" if isinstance(defval, bool) else "int" if isinstance(defval, int) else
                        "float" if isinstance(defval, float) else "color" if isinstance(defval, Color) else "string")
        options_node = get("options")
        options = None
        if options_node is not None:
            if not isinstance(options_node, A.TupleExpr):
                self.error("`options` must be a list like `[1, 2, 3]`.", options_node)
            else:
                options = [self.const_value(item, "options") for item in options_node.items]
        title = self.const_value(get("title"), "title") if get("title") is not None else None
        self.feature("inputs", node)
        self.inputs.append(InputDef(
            index=len(self.inputs), node_id=node.id, kind=kind, title=title or f"Input {len(self.inputs) + 1}",
            defval=defval, options=options,
            minval=self.const_value(get("minval"), "minval") if get("minval") is not None else None,
            maxval=self.const_value(get("maxval"), "maxval") if get("maxval") is not None else None,
            step=self.const_value(get("step"), "step") if get("step") is not None else None,
            tooltip=self.const_value(get("tooltip"), "tooltip") if get("tooltip") is not None else None,
            group=self.const_value(get("group"), "group") if get("group") is not None else None, line=node.line))

    def source_name(self, node, quiet: bool = False) -> str | None:
        if isinstance(node, A.Name) and node.name in SOURCE_NAMES:
            return node.name
        if not quiet:
            self.error("An `input.source()` default must be a built-in price series such as `close` or `hl2`.", node)
        return None

    def const_value(self, node: A.Node, what: str):
        """Compile-time value of a const expression (literals, constants, simple arithmetic, color.new/rgb)."""
        if isinstance(node, A.Literal):
            if node.kind == "color":
                return Color.from_hex(node.value)
            return node.value
        if isinstance(node, A.Unary) and node.op in ("-", "+"):
            value = self.const_value(node.operand, what)
            return -value if node.op == "-" and isinstance(value, (int, float)) else value
        if isinstance(node, (A.Name, A.Attribute)):
            name = node.name if isinstance(node, A.Name) else node.dotted()
            if name in CONSTANTS:
                return CONSTANTS[name][0]
            if name == "na":
                return NA
        if isinstance(node, A.Binary) and node.op in ("+", "-", "*", "/"):
            left, right = self.const_value(node.left, what), self.const_value(node.right, what)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                return {"+": left + right, "-": left - right, "*": left * right,
                        "/": left / right if right else NA}[node.op]
            if node.op == "+" and isinstance(left, str) and isinstance(right, str):
                return left + right
        if isinstance(node, A.Call) and isinstance(node.func, A.Attribute) and node.func.dotted() in ("color.new", "color.rgb"):
            builtin_ = FUNCTIONS[node.func.dotted()]
            args = {p.name: p.default for p in builtin_.params}
            positional = [a for a in node.args if a.name is None]
            for param, argument in zip(builtin_.params, positional):
                args[param.name] = self.const_value(argument.value, what)
            for argument in node.args:
                if argument.name is not None:
                    args[argument.name] = self.const_value(argument.value, what)
            return builtin_.impl(None, None, args)
        self.error(f"`{what}` must be a constant value here.", node)
        return None

    # -- types -----------------------------------------------------------------------------------------------
    @staticmethod
    def max_qualifier(*specs: TypeSpec | None) -> str:
        known = [s.qualifier for s in specs if s is not None]
        if len(known) < len([s for s in specs]):
            return "series"
        return max(known, key=lambda q: QUALIFIER_RANK.get(q, 3)) if known else "series"

    def merge(self, a: TypeSpec | None, b: TypeSpec | None, condition: TypeSpec | None = None) -> TypeSpec | None:
        if a is None or b is None:
            return a or b
        base = a.base if a.base == b.base else "float" if {a.base, b.base} <= NUMERIC else None
        if base is None:
            return None
        return TypeSpec(self.max_qualifier(a, b, condition) if condition is not None else self.max_qualifier(a, b), base)

    @staticmethod
    def assignable(value: TypeSpec, target: TypeSpec) -> bool:
        if value.base == target.base or target.base == "any" or value.base == "any":
            return True
        return value.base == "int" and target.base == "float"


def gap_message(name: str, feature: str) -> str:
    """"`request.security()` is not implemented yet (data requests)." - the feature's short name, once."""
    short = FEATURES[feature].description.split(" (")[0]
    suffix = "" if short.rstrip("()") in name or short in (f"{name}()",) else f" ({short})"
    return f"`{name}()` is not implemented yet{suffix}."


def analyze(script: A.Script) -> tuple[Program, list[Diagnostic]]:
    return Analyzer(script).analyze()

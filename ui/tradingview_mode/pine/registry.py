"""Built-in registries: functions, variables and constants by Pine name.

Adding a Pine built-in = registering it here (from a module in ``builtins/``);
the lexer, parser and analyzer never change. Each function declares typed
parameters (``qualifier base``, e.g. ``simple int``), optional overloads, a
return type and its kind:

* ``function``    - ordinary (stateless or per-call-site stateful) built-in
* ``output``      - plot family; global scope only; writes chart outputs
* ``input``       - input.*; value fixed for the run, overridable by the user
* ``declaration`` - indicator()/strategy()/library(); read by the analyzer
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

REQUIRED = object()
QUALIFIER_RANK = {"const": 0, "input": 1, "simple": 2, "series": 3}


@dataclass(frozen=True)
class TypeSpec:
    qualifier: str      # const | input | simple | series
    base: str           # int | float | bool | string | color | any | tuple | plot | ...

    @classmethod
    def parse(cls, text: str) -> "TypeSpec":
        parts = text.split()
        if len(parts) == 1:
            return cls("series", parts[0])
        return cls(parts[0], parts[1])

    def __str__(self) -> str:
        return f"{self.qualifier} {self.base}"


@dataclass(frozen=True)
class Param:
    name: str
    type: str = "series float"
    default: Any = REQUIRED

    @property
    def spec(self) -> TypeSpec:
        return TypeSpec.parse(self.type)

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


@dataclass
class Builtin:
    name: str
    params: tuple[Param, ...]
    impl: Callable
    returns: str = "series float"
    kind: str = "function"
    stateful: bool = False
    variadic: str | None = None           # name of a trailing *args parameter
    overloads: tuple[tuple[Param, ...], ...] = ()
    note: str = ""

    def signatures(self) -> tuple[tuple[Param, ...], ...]:
        return (self.params, *self.overloads)


@dataclass
class BuiltinVariable:
    name: str
    impl: Callable                          # impl(rt, bar_index) -> value
    returns: str = "series float"
    note: str = ""


FUNCTIONS: dict[str, Builtin] = {}
VARIABLES: dict[str, BuiltinVariable] = {}
CONSTANTS: dict[str, tuple[Any, str]] = {}     # name -> (value, "const type")


def builtin(name: str, *params: Param, returns: str = "series float", kind: str = "function", stateful: bool = False,
            variadic: str | None = None, overloads: tuple = (), note: str = ""):
    def register(fn: Callable) -> Callable:
        if name in FUNCTIONS:
            raise ValueError(f"duplicate built-in {name}")
        FUNCTIONS[name] = Builtin(name, tuple(params), fn, returns, kind, stateful, variadic, tuple(overloads), note)
        return fn
    return register


def variable(name: str, returns: str = "series float", note: str = ""):
    def register(fn: Callable) -> Callable:
        VARIABLES[name] = BuiltinVariable(name, fn, returns, note)
        return fn
    return register


def constant(name: str, value: Any, type_: str) -> None:
    CONSTANTS[name] = (value, f"const {type_}")


@dataclass
class Binding:
    """Arguments of one call matched to a signature: param name -> argument node (or None)."""

    params: tuple[Param, ...]
    nodes: dict[str, Any] = field(default_factory=dict)
    extra: tuple = ()                        # variadic argument nodes


def bind(builtin_: Builtin, positional: list, named: dict,
         compatible: Callable[[Param, Any], bool] | None = None) -> tuple[Binding | None, str | None]:
    """Match call arguments to the first fitting signature. ``compatible(param,
    node)`` lets the caller skip a signature whose parameter type clearly does
    not fit a known argument type (overload resolution). Returns (binding, error)."""
    errors = []
    for params in builtin_.signatures():
        names = [p.name for p in params]
        if builtin_.variadic is None and len(positional) > len(params):
            errors.append(f"too many arguments ({len(positional)} given, at most {len(params)})")
            continue
        binding = Binding(params)
        fixed = positional if builtin_.variadic is None else positional[:len(params)]
        for param, node in zip(params, fixed):
            binding.nodes[param.name] = node
        if builtin_.variadic is not None:
            binding.extra = tuple(positional[len(params):])
        unknown = [name for name in named if name not in names]
        if unknown:
            errors.append(f"unknown argument `{unknown[0]}` (valid: {', '.join(names) or 'none'})")
            continue
        clash = [name for name in named if name in binding.nodes]
        if clash:
            errors.append(f"argument `{clash[0]}` given twice")
            continue
        binding.nodes.update(named)
        missing = [p.name for p in params if p.required and p.name not in binding.nodes]
        if missing:
            errors.append(f"missing required argument `{missing[0]}`")
            continue
        if compatible is not None and len(builtin_.signatures()) > 1:
            misfit = next((p.name for p in params if p.name in binding.nodes and not compatible(p, binding.nodes[p.name])), None)
            if misfit is not None:
                errors.append(f"argument `{misfit}` has the wrong type")
                continue
        return binding, None
    return None, errors[0] if errors else "no matching signature"


def load_all() -> None:
    """Import every built-in module (each registers itself)."""
    from .builtins import arrays, core, color, drawings, inputs, math_, outputs, request, strings, ta, time_  # noqa: F401

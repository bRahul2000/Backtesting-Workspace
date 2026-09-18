from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import inspect
import json
from typing import Any, Callable, Mapping

from strategies.base import Strategy


class StrategyStatus(str, Enum):
    RESEARCH = "RESEARCH"
    CANDIDATE = "CANDIDATE"
    FORWARD_VALIDATED = "FORWARD_VALIDATED"
    FROZEN = "FROZEN"
    DEMO = "DEMO"
    LIVE = "LIVE"
    REJECTED = "REJECTED"


class ParameterType(str, Enum):
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ENUM = "enum"
    TIMEFRAME = "timeframe"
    SESSION = "session"
    PERCENTAGE = "percentage"
    ATR_MULTIPLE = "atr_multiple"
    STRING = "string"


@dataclass(frozen=True)
class StrategyParameter:
    name: str
    parameter_type: ParameterType
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    step: float | int | None = None
    description: str = ""
    optimization_allowed: bool = True
    frozen: bool = False
    choices: tuple[Any, ...] = ()

    def validate(self, value: Any) -> Any:
        if self.frozen and value != self.default:
            raise ValueError(f"Frozen parameter {self.name} cannot be changed.")
        if self.choices and value not in self.choices:
            raise ValueError(f"{self.name} must be one of {self.choices!r}.")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.name} must be >= {self.minimum}.")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.name} must be <= {self.maximum}.")
        return value


@dataclass(frozen=True)
class StrategyMetadata:
    strategy_id: str
    name: str
    version: str
    status: StrategyStatus
    category: str
    supported_instruments: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    description: str
    created_date: str
    strategy_fingerprint: str


def fingerprint_strategy_class(cls: type) -> str:
    try:
        source = inspect.getsource(cls)
    except (OSError, TypeError):
        source = f"{cls.__module__}.{cls.__qualname__}"
    return sha256(source.encode("utf-8")).hexdigest()


def parameter_fingerprint(values: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(values), sort_keys=True, default=str, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


class BaseStrategy(Strategy, ABC):
    """Universal strategy contract layered on top of the audited Strategy interface.

    Existing frozen strategies do not need to inherit this class. They are bridged by
    AuditedStrategyAdapter so no validated execution behavior is rewritten.
    """

    metadata: StrategyMetadata
    parameters: tuple[StrategyParameter, ...] = ()
    required_indicators: tuple[str, ...] = ()
    required_timeframes: tuple[str, ...] = ("15m",)

    def update_state(self, *args, **kwargs) -> None:
        return None

    def generate_signal(self, *args, **kwargs):
        return None

    def create_order(self, *args, **kwargs):
        return None

    def cancel_rule(self, *args, **kwargs):
        return None

    def on_fill(self, *args, **kwargs) -> None:
        return None

    def on_exit(self, *args, **kwargs) -> None:
        return None


@dataclass(frozen=True)
class StrategyDescriptor:
    metadata: StrategyMetadata
    factory: Callable[[], Strategy]
    parameters: tuple[StrategyParameter, ...] = field(default_factory=tuple)
    required_indicators: tuple[str, ...] = field(default_factory=tuple)
    required_timeframes: tuple[str, ...] = ("15m",)
    warmup_resolver: Callable[[Any], Any] | None = None
    parameterized_factory: Callable[[Mapping[str, Any]], Strategy] | None = None
    execution_profile: str = "AUDITED_NATIVE"

    def create(self, overrides: Mapping[str, Any] | None = None) -> Strategy:
        overrides = dict(overrides or {})
        known = {p.name: p for p in self.parameters}
        unknown = set(overrides) - set(known)
        if unknown:
            raise ValueError(f"Unknown strategy parameter(s): {sorted(unknown)}")
        for name, value in overrides.items():
            known[name].validate(value)
        if overrides:
            if self.parameterized_factory is None:
                raise ValueError(
                    "This descriptor does not expose constructor overrides; frozen strategies are read-only."
                )
            return self.parameterized_factory(overrides)
        return self.factory()


class AuditedStrategyAdapter:
    """Universal facade for an existing audited Strategy implementation."""

    def __init__(self, descriptor: StrategyDescriptor):
        self.descriptor = descriptor

    @property
    def metadata(self) -> StrategyMetadata:
        return self.descriptor.metadata

    @property
    def parameters(self) -> tuple[StrategyParameter, ...]:
        return self.descriptor.parameters

    def create_legacy_strategy(self, overrides: Mapping[str, Any] | None = None) -> Strategy:
        return self.descriptor.create(overrides)

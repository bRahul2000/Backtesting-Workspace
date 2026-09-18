from __future__ import annotations

from collections import OrderedDict
from typing import Callable

from strategies.base_strategy import StrategyDescriptor


class StrategyRegistry:
    def __init__(self) -> None:
        self._items: OrderedDict[str, StrategyDescriptor] = OrderedDict()

    def register(self, descriptor: StrategyDescriptor) -> StrategyDescriptor:
        sid = descriptor.metadata.strategy_id
        if sid in self._items:
            raise ValueError(f"Strategy already registered: {sid}")
        self._items[sid] = descriptor
        return descriptor

    def get(self, strategy_id: str) -> StrategyDescriptor:
        try:
            return self._items[strategy_id]
        except KeyError as exc:
            raise KeyError(f"Unknown strategy id: {strategy_id}") from exc

    def all(self) -> tuple[StrategyDescriptor, ...]:
        return tuple(self._items.values())

    def for_instrument(self, instrument: str) -> tuple[StrategyDescriptor, ...]:
        symbol = instrument.upper()
        return tuple(
            item for item in self._items.values()
            if symbol in {value.upper() for value in item.metadata.supported_instruments}
        )

    def by_name(self, name: str) -> StrategyDescriptor:
        for item in self._items.values():
            if item.metadata.name == name:
                return item
        raise KeyError(name)


REGISTRY = StrategyRegistry()
_DISCOVERED = False


def register_strategy(descriptor: StrategyDescriptor) -> StrategyDescriptor:
    return REGISTRY.register(descriptor)


def strategy_registration(factory: Callable[[], StrategyDescriptor]):
    descriptor = factory()
    REGISTRY.register(descriptor)
    return factory


def discover_builtin_strategies() -> StrategyRegistry:
    global _DISCOVERED
    if not _DISCOVERED:
        import strategies.universal_catalog  # noqa: F401
        _DISCOVERED = True
    return REGISTRY

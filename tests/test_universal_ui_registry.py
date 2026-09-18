from types import SimpleNamespace

from strategies.registry import discover_builtin_strategies
from ui import backtest_dashboard, universal_controls


class FakeStreamlit:
    def __init__(self):
        self.calls = []

    def number_input(self, label, **kwargs):
        self.calls.append((label, kwargs))
        return kwargs["value"]

    def checkbox(self, label, **kwargs):
        self.calls.append((label, kwargs))
        return kwargs["value"]

    def selectbox(self, label, choices, **kwargs):
        self.calls.append((label, kwargs))
        return choices[kwargs.get("index", 0)]

    def caption(self, *args, **kwargs):
        return None


def test_main_dropdown_sources_universal_names_from_registry():
    names = {item.metadata.name for item in discover_builtin_strategies().all()
             if item.metadata.status.value != "REJECTED"}
    assert names.issubset(set(backtest_dashboard.BACKTEST_STRATEGY_OPTIONS))


def test_dynamic_frozen_parameters_render_read_only(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(universal_controls, "st", fake)
    descriptor = discover_builtin_strategies().get("BTC_V3_A4_PULLBACK_LONG_FROZEN")
    values = universal_controls.render_dynamic_parameters(descriptor)
    assert values["confirmation_min_body_percent"] == 0.70
    assert fake.calls
    assert all(kwargs.get("disabled") is True for _, kwargs in fake.calls)

"""TradingView Mode is the React + Lightweight Charts terminal only."""
import ast
from pathlib import Path

from streamlit.testing.v1 import AppTest

import ui.tradingview_mode.page as page
import ui.tradingview_mode.workspace as workspace

PAGE_SOURCE = Path(page.__file__).read_text()


def _code_identifiers_and_strings(source: str) -> tuple[set[str], list[str]]:
    """Names used by the page's code and its string literals, excluding docstrings."""
    tree = ast.parse(source)
    docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.FunctionDef)) and ast.get_docstring(node)}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in node.names}
    strings = [node.value for node in ast.walk(tree)
               if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]
    return names, strings


def _script():
    from ui.tradingview_mode.page import render_tradingview_mode

    render_tradingview_mode()


def run() -> AppTest:
    app = AppTest.from_function(_script, default_timeout=60)
    app.run()
    assert not app.exception
    return app


def test_page_has_no_renderer_toggle_or_legacy_routing():
    names, strings = _code_identifiers_and_strings(PAGE_SOURCE)
    for forbidden in ("toggle", "render_workspace_panels", "render_top_toolbar", "render_tradingview_chart",
                      "render_legacy_workspace", "plotly_chart"):
        assert forbidden not in names
    for label in ("Prototype", "Legacy", "Plotly", "Custom"):
        assert not [text for text in strings if label in text]


def test_only_the_terminal_renders(monkeypatch):
    calls = []

    def forbidden(*args, **kwargs):
        calls.append("legacy")
        raise AssertionError("legacy workspace must not be reached")

    monkeypatch.setattr(workspace, "render_top_toolbar", forbidden)
    monkeypatch.setattr(workspace, "render_workspace_panels", forbidden)
    app = run()
    assert not calls
    assert not app.get("toggle") and not app.get("plotly_chart")
    assert not app.get("popover") and not app.get("expander") and not app.get("date_input")
    assert not [m for m in app.markdown if "### TradingView Mode" in m.value]


def test_terminal_failure_shows_error_and_nothing_else(monkeypatch):
    import ui.tradingview_mode.component.terminal as terminal

    def broken():
        raise RuntimeError("component exploded")

    monkeypatch.setattr(terminal, "render_custom_terminal", broken)
    app = run()
    assert any("TradingView Mode failed to load" in e.value and "component exploded" in e.value for e in app.error)
    assert not app.get("plotly_chart") and not app.get("toggle")


def test_unbuilt_frontend_shows_error_not_another_renderer(monkeypatch):
    import ui.tradingview_mode.component as component

    monkeypatch.setattr(component, "_component", None)
    app = run()
    assert any("TradingView Mode frontend is unavailable" in e.value for e in app.error)
    assert not app.get("plotly_chart")


def test_no_prototype_language_in_user_facing_sources():
    root = Path(page.__file__).parent / "component"
    sources = [root / "__init__.py", root / "terminal.py"] + list((root / "frontend" / "src").rglob("*.js*"))
    for path in sources:
        text = path.read_text()
        for label in ("Prototype", "prototype", "Legacy Plotly", "Custom Chart", "Custom Terminal"):
            assert label not in text, f"{label!r} in {path.name}"

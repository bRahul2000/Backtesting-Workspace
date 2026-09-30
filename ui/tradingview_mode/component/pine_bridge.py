"""TradingView Mode <-> Pine engine: editor events, script instances, execution.

* Compiled programs are cached by source hash (process-wide, bounded).
* Each script instance keeps one ``PineExecution`` per session, reused across
  reruns: an unchanged chart re-executes nothing, a live forming bar or a
  replay step executes one bar, anything else recompiles/re-runs from bar 0.
* Scripts run on the bars the chart shows (historical window, revealed replay
  bars, or the live provider's bars) - never on data the chart does not have.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from functools import lru_cache

import pandas as pd

from ..pine import PineExecution, compile_script, run_script
from ..pine.compat import matrix
from ..pine.engine import CompileResult, data_context, resolve_inputs, source_hash
from ..pine.examples import EXAMPLES
from ..pine.security import LIMIT, MAX_CONTEXTS_PER_CHART as MAX_CHART_CONTEXTS, SecurityDataError
from . import tester_export
from .protocol import PINE_EVENTS  # noqa: F401  (re-exported for terminal.py)
from .replay import parse_utc
from .state import LogEntry, PineInstance, TerminalState
MAX_SCRIPTS = 8
MAX_PINE_BARS = 20_000       # TradingView Premium's chart bar limit; Pine calculates on at most this many bars
EDITOR_KEY = "tv_terminal_pine_editor"
EXEC_KEY = "tv_terminal_pine_exec"
EXPORT_KEY = "tv_terminal_pine_export"      # a requested trade-list export, built once on the next payload
_COMPILED: "OrderedDict[str, CompileResult]" = OrderedDict()
_COMPILED_LIMIT = 64


def compiled(source: str) -> CompileResult:
    digest = source_hash(source)
    result = _COMPILED.get(digest)
    if result is None:
        result = compile_script(source)
        _COMPILED[digest] = result
        while len(_COMPILED) > _COMPILED_LIMIT:
            _COMPILED.popitem(last=False)
    else:
        _COMPILED.move_to_end(digest)
    return result


def _first_problem(result: CompileResult) -> str:
    problem = result.errors[0]
    return f"Line {problem.line}: {problem.message}"


def _find(state: TerminalState, script_id: str) -> PineInstance | None:
    return next((item for item in state.pine if item.id == script_id), None)


def _replace(state: TerminalState, updated: PineInstance) -> TerminalState:
    return replace(state, pine=tuple(updated if item.id == updated.id else item for item in state.pine))


def handle_pine_event(event, state: TerminalState, session) -> tuple[TerminalState, LogEntry]:
    """Apply one Pine editor event. Compilation results go to the editor panel."""
    kind, data = event.type, event.data
    if kind in ("pine_compile", "pine_add", "pine_update"):
        result = compiled(data["source"])
        target = data.get("id")
        session[EDITOR_KEY] = {"event": event.id, "action": kind, "target": target, "source_hash": result.source_hash,
                               **result.summary()}
        if kind == "pine_compile":
            level = "info" if result.ok else "warning"
            text = (f"Compiled `{result.meta.get('title')}`: ready to add." if result.ok
                    else f"Compile: {len(result.errors)} problem(s). {_first_problem(result)}")
            return state, LogEntry(level, f"Pine {text}")
        if not result.ok:
            return state, LogEntry("error", f"Rejected: Pine script not added. {_first_problem(result)}")
        if kind == "pine_add":
            if len(state.pine) >= MAX_SCRIPTS:
                return state, LogEntry("error", f"Rejected: at most {MAX_SCRIPTS} Pine scripts can be on the chart.")
            twin = next((item for item in state.pine if source_hash(item.source) == result.source_hash
                         and not item.inputs), None)
            if twin is not None and not data.get("another"):
                # an identical compiled script with identical (default) inputs is already on the chart
                session[EDITOR_KEY]["duplicate_of"] = twin.id
                return state, LogEntry("warning", f"`{twin.title}` is already on the chart ({twin.id}) with the same "
                                                  "inputs. Not added again; use Add another instance for a second copy.")
            instance = PineInstance(f"pine-{state.next_pine}", data["source"], result.meta["title"])
            new = replace(state, pine=state.pine + (instance,), next_pine=state.next_pine + 1)
            return new, LogEntry("info", f"Added Pine script `{instance.title}` ({instance.id}).")
        current = _find(state, target)
        if current is None:
            return state, LogEntry("error", f"Rejected: no Pine script {target!r} on the chart.")
        updated = PineInstance(current.id, data["source"], result.meta["title"], current.enabled, (),
                               current.test_range)
        return _replace(state, updated), LogEntry("info", f"Updated Pine script `{updated.title}` ({updated.id}); inputs reset.")
    current = _find(state, data["id"])
    if current is None:
        return state, LogEntry("error", f"Rejected: no Pine script {data['id']!r} on the chart.")
    if kind == "pine_remove":
        session.get(EXEC_KEY, {}).pop(current.id, None)
        return (replace(state, pine=tuple(item for item in state.pine if item.id != current.id)),
                LogEntry("info", f"Removed Pine script `{current.title}` ({current.id})."))
    if kind == "pine_set_range":
        start, end = data["start"], data["end"]
        if (start is None) != (end is None):
            return state, LogEntry("error", "Rejected: a custom test range needs both a start and an end.")
        if start is None:
            return (_replace(state, replace(current, test_range=None)),
                    LogEntry("info", f"`{current.title}` test range: full available history."))
        start_s, end_s = parse_utc(start), parse_utc(end)
        if start_s > end_s:
            return state, LogEntry("error", f"Rejected: test range start {start} is after its end {end}.")
        clean = (_utc_text(start_s), _utc_text(end_s))
        return (_replace(state, replace(current, test_range=clean)),
                LogEntry("info", f"`{current.title}` test range: {clean[0]} → {clean[1]} UTC."))
    if kind == "pine_export":
        session[EXPORT_KEY] = {"event": event.id, "id": current.id}
        return state, LogEntry("info", f"Exporting the trade list of `{current.title}`.")
    if kind == "pine_toggle":
        return (_replace(state, replace(current, enabled=data["enabled"])),
                LogEntry("info", f"Pine script `{current.title}` {'shown' if data['enabled'] else 'hidden'}."))
    # pine_set_input
    result = compiled(current.source)
    index, value = data["index"], data["value"]
    if result.program is None or not 0 <= index < len(result.inputs):
        return state, LogEntry("error", f"Rejected: `{current.title}` has no input #{index}.")
    values, problems = resolve_inputs(result.program, {**dict(current.inputs), index: value})
    if problems:
        return state, LogEntry("error", f"Rejected: {problems[0]}.")
    inputs = tuple(sorted({**dict(current.inputs), index: value}.items()))
    return (_replace(state, replace(current, inputs=inputs)),
            LogEntry("info", f"`{current.title}` input `{result.inputs[index].title}` = {value!r}."))


def _input_rows(result: CompileResult, instance: PineInstance) -> list[dict]:
    overrides = dict(instance.inputs)
    rows = []
    for definition in result.inputs:
        row = definition.as_dict()
        value = overrides.get(definition.index, row["defval"])
        row["value"] = value.css() if hasattr(value, "css") else value
        rows.append(row)
    return rows


def _contexts(run_contexts: list[dict]) -> list[dict]:
    """request.security() provenance for the payload (plain JSON; times in epoch seconds)."""
    out = []
    for c in run_contexts:
        max_source = c.get("max_source_time")
        out.append({"provider_family": c["provider_family"], "provider": c["provider"], "symbol": c["symbol"],
                    "timeframe": c["timeframe"], "native": bool(c["native"]), "aggregation_base": c["aggregation_base"],
                    "bar_count": int(c["bar_count"]), "max_source_time": None if max_source is None else int(max_source) // 1000,
                    "data_identity": c["data_identity"], "fingerprint": c["fingerprint"], "depth": int(c["depth"]),
                    "line": int(c["line"]), "forming": bool(c["forming"])})
    return out


def _literal_problem(result: CompileResult, provider) -> dict | None:
    """A literal request.security() / request.security_lower_tf() symbol from another data source is refused before
    anything runs."""
    for spec in result.program.security.values():
        if spec.symbol_literal:
            try:
                provider.check_symbol(spec.symbol_literal)
            except SecurityDataError as exc:
                label = "request.security_lower_tf()" if getattr(spec, "lower", False) else "request.security()"
                return {"message": f"Line {spec.line}: {label}: {exc.message}", "line": spec.line, "bar_index": None}
    return None


def _rendered(outputs: list[dict], display_from: int | None, display_to: int | None = None) -> list[dict]:
    """Chart outputs restricted to the rendered bars (the calculation may start earlier and, for a strategy tested
    over its own range, end later than the chart window)."""
    if display_from is None and display_to is None:
        return outputs
    low = display_from if display_from is not None else -float("inf")
    high = display_to if display_to is not None else float("inf")
    return [{**o, "data": [p for p in o["data"] if p.get("time") is None or low <= p["time"] <= high]}
            if isinstance(o.get("data"), list) else o for o in outputs]


def _utc_text(epoch: int) -> str:
    return pd.Timestamp(epoch, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M")


def _epochs(frame) -> "pd.Series":
    return (frame["timestamp"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)


def strategy_frame(full, test_range: tuple[str, str] | None):
    """A strategy's evaluation bars: the full available history, or exactly the bars whose OPEN time lies inside the
    test range (both ends inclusive). Nothing before the range is visible to the strategy."""
    if test_range is None or full is None or not len(full):
        return full
    stamps = _epochs(full)
    keep = (stamps >= parse_utc(test_range[0])) & (stamps <= parse_utc(test_range[1]))
    return full[keep.to_numpy()].reset_index(drop=True)


def pine_payload(state: TerminalState, frame, session, *, identity: tuple, timeframe_seconds: int, ticker: str,
                 tickerid: str, mintick: float, forming_last: bool = False, kind: str = "crypto",
                 currency: str = "USD", chart_family: str | None = None, mode: str = "historical",
                 knowable_until: int | None = None, provider=None, display_from: int | None = None,
                 display_to: int | None = None, display_times=None, full_frame=None,
                 export_meta: dict | None = None) -> dict:
    """Run every enabled script on ``frame`` and build the payload section.

    Historical mode calculates on more history than the chart shows: ``frame`` is the calculation range (from the
    first available bar to the end of the chart's date range) and ``display_from`` (epoch seconds) the first bar the
    chart renders. Plots, shapes and colors are sent for the rendered bars only; drawings keep their Pine
    coordinates (mapped with ``first_bar_index``); the strategy report covers the whole calculation range.

    request.security(): ``provider`` serves the chart's source family only; Replay and Live run in knowable
    mode (only information knowable per bar, cut at ``knowable_until``), Historical reproduces TradingView's
    historical semantics."""
    executions = session.setdefault(EXEC_KEY, {})
    for stale in set(executions) - {item.id for item in state.pine}:
        executions.pop(stale)
    knowable = mode in ("replay", "live")
    contexts_by_frame: dict = {}

    def prepared(calc):
        """(view, truncated, first_bar_index, data context) for one calculation frame (shared per frame)."""
        key = id(calc)
        if key not in contexts_by_frame:
            truncated = max(0, len(calc) - MAX_PINE_BARS)
            view = calc.iloc[truncated:].reset_index(drop=True) if truncated else calc
            first_bar_index = 0
            if len(view):
                first = int(_epochs(view.iloc[:1]).iloc[0])
                if display_from is not None and first < display_from:
                    first_bar_index = -int((_epochs(view) < display_from).sum())   # bars before the chart's first
                elif display_times is not None:
                    first_bar_index = int(sum(1 for t in display_times if t < first))  # starts inside the window
            data = data_context(view, timeframe_seconds=timeframe_seconds, ticker=ticker, tickerid=tickerid,
                                mintick=mintick, forming_last=forming_last, kind=kind, currency=currency,
                                knowable=knowable, knowable_until=knowable_until) if len(view) else None
            contexts_by_frame[key] = (calc, view, truncated, first_bar_index, data)
        return contexts_by_frame[key][1:]

    export_request = session.pop(EXPORT_KEY, None)
    scripts, total_contexts = [], 0
    for instance in state.pine:
        result = compiled(instance.source)
        is_strategy = (result.meta.get("kind") or "indicator") == "strategy"
        ranged = is_strategy and mode == "historical" and full_frame is not None
        calc = strategy_frame(full_frame, instance.test_range) if ranged else frame
        view, truncated, first_bar_index, data = prepared(calc)
        test_range = None
        if ranged:
            test_range = {"mode": "custom" if instance.test_range else "full",
                          "start": instance.test_range[0] if instance.test_range else None,
                          "end": instance.test_range[1] if instance.test_range else None,
                          "first_time": int(_epochs(view.iloc[:1]).iloc[0]) if len(view) else None,
                          "last_time": int(_epochs(view.iloc[-1:]).iloc[0]) if len(view) else None,
                          "bars": len(view)}
        entry = {"id": instance.id, "title": instance.title, "enabled": instance.enabled, "source": instance.source,
                 "source_hash": result.source_hash, "overlay": bool(result.meta.get("overlay")),
                 "shorttitle": result.meta.get("shorttitle") or instance.title, "inputs": _input_rows(result, instance),
                 "outputs": [], "error": None, "runtime_ms": 0.0, "bars": 0, "executed": 0, "incremental": False,
                 "truncated_bars": truncated, "contexts": [], "drawings": None,
                 "kind": result.meta.get("kind") or "indicator", "strategy": None, "calc_bars": 0,
                 "display_from": display_from, "test_range": test_range}
        if not result.ok:
            entry["error"] = {"message": _first_problem(result), "line": result.errors[0].line, "bar_index": None}
        elif result.program.security and provider is not None and (problem := _literal_problem(result, provider)):
            entry["error"] = problem
        elif ranged and not len(view):
            entry["error"] = {"message": "The test range contains no bars of this dataset.", "line": None,
                              "bar_index": None}
        elif instance.enabled and data is not None:
            values, _ = resolve_inputs(result.program, dict(instance.inputs))
            key = (result.source_hash, tuple(sorted((k, repr(v)) for k, v in values.items())), chart_family,
                   instance.test_range if ranged else None)
            cached = executions.get(instance.id)
            if cached is None or cached[0] != key:
                cached = executions[instance.id] = (key, PineExecution(result.program, values))
            run_identity = identity + (chart_family, mode) + ((("range",) + tuple(instance.test_range or ("full",)))
                                                              if ranged else ())
            run = run_script(cached[1], data, run_identity, instance.id, provider)
            entry.update(outputs=_rendered(run.outputs, display_from, display_to), error=run.error,
                         runtime_ms=round(run.runtime_ms, 1), bars=run.bars,
                         executed=run.executed, incremental=run.incremental, contexts=_contexts(run.contexts),
                         drawings=None if run.drawings is None else {**run.drawings,
                                                                     "first_bar_index": first_bar_index},
                         strategy=run.strategy, calc_bars=len(view), display_from=display_from)
            total_contexts += len(entry["contexts"])
            if total_contexts > MAX_CHART_CONTEXTS:
                total_contexts -= len(entry["contexts"])
                entry.update(outputs=[], contexts=[], drawings=None, strategy=None, error={
                    "message": f"{LIMIT}: at most {MAX_CHART_CONTEXTS} requested contexts across the chart.",
                    "line": None, "bar_index": None})
        scripts.append(entry)
    export = None
    if export_request is not None:
        script = next((s for s in scripts if s["id"] == export_request["id"]), None)
        if script is not None and script.get("strategy"):
            meta = export_meta or {}
            name, content = tester_export.pine_trades_csv(
                strategy=script["title"], symbol=meta.get("symbol", ""), timeframe=meta.get("timeframe", ""),
                provider=meta.get("provider", ""), report=script["strategy"],
                test_range=script.get("test_range") or {"mode": mode,
                                                        **script["strategy"].get("calc_range", {})})
            export = {"id": export_request["event"], "filename": name, "mime": "text/csv;charset=utf-8",
                      "content": content}
    editor = session.get(EDITOR_KEY)
    counts = compat_summary()
    return {
        "scripts": scripts,
        "export": export,
        "chart_family": chart_family,
        "mode": mode,
        "editor": editor,
        "examples": [{"name": name, "source": source} for name, source in EXAMPLES.items()],
        "compat": counts,
        "limits": {"max_scripts": MAX_SCRIPTS, "max_bars": MAX_PINE_BARS, "max_chart_contexts": MAX_CHART_CONTEXTS},
    }


@lru_cache(maxsize=1)
def compat_summary() -> dict:
    """Feature-by-feature coverage for the editor (static for a given engine build)."""
    m = matrix()
    return {"counts": m["counts"], "functions": m["builtins"]["functions"], "variables": m["builtins"]["variables"],
            "features": [{**f, "category": category} for category, group in m["features"].items() for f in group]}

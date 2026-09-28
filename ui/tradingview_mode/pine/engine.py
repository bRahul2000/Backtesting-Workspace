"""Public API of the Pine engine: compile, report, execute (incrementally)."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import time
from typing import Any

import numpy as np

from . import ast as A
from .analyzer import InputDef, Program, analyze
from .builtins.inputs import coerce_input
from .compat import FEATURES
from .errors import ERROR, GAP, WARNING, Diagnostic, PineError, PineRuntimeError
from .outputs import render, render_drawings
from .parser import parse
from .registry import load_all
from .runtime import DataContext, Runtime
from .security import SecurityManager

MISSING_PROVIDER = object()

MAX_SOURCE_CHARS = 100_000


@dataclass
class CompileResult:
    ok: bool
    diagnostics: list[Diagnostic]
    program: Program | None
    meta: dict
    inputs: list[InputDef]
    report: dict
    source_hash: str

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.kind in (ERROR, GAP)]

    def summary(self) -> dict:
        return {"ok": self.ok, "diagnostics": [d.as_dict() for d in self.diagnostics], "meta": self.meta,
                "inputs": [i.as_dict() for i in self.inputs], "report": self.report}


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def compile_script(source: str) -> CompileResult:
    """Parse + analyze. ``ok`` is False when there is any error or capability gap."""
    load_all()
    digest = source_hash(source)
    if len(source) > MAX_SOURCE_CHARS:
        diag = Diagnostic(ERROR, f"The script is longer than {MAX_SOURCE_CHARS:,} characters.", 1, 1)
        return CompileResult(False, [diag], None, {}, [], script_report(None, [diag]), digest)
    try:
        script = parse(source)
    except PineError as exc:
        diagnostics = [exc.diagnostic]
        return CompileResult(False, diagnostics, None, {}, [], script_report(None, diagnostics), digest)
    program, diagnostics = analyze(script)
    program.input_by_node = {definition.node_id: definition for definition in program.inputs}
    ok = not any(d.kind in (ERROR, GAP) for d in diagnostics)
    return CompileResult(ok, diagnostics, program if ok else None, program.meta, program.inputs,
                         script_report(program, diagnostics), digest)


def script_report(program: Program | None, diagnostics: list[Diagnostic]) -> dict:
    """What this script needs, feature by feature (supported vs gap)."""
    used = []
    if program is not None:
        for feature_id, lines in sorted(program.features.items()):
            feature = FEATURES.get(feature_id)
            if feature is None:
                continue
            used.append({"feature": feature_id, "category": feature.category, "status": feature.status,
                         "description": feature.description, "lines": sorted(lines)})
    gaps = [d.as_dict() for d in diagnostics if d.kind == GAP]
    return {
        "features": used,
        "gaps": gaps,
        "builtins": sorted(program.builtins_used) if program is not None else [],
        "errors": sum(1 for d in diagnostics if d.kind == ERROR),
        "warnings": sum(1 for d in diagnostics if d.kind == WARNING),
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    outputs: list[dict]
    error: dict | None
    runtime_ms: float
    bars: int
    executed: int
    incremental: bool
    contexts: list = field(default_factory=list)      # request.security() provenance, one entry per context
    drawings: dict | None = None                       # P2.3a live drawing objects (outputs.render_drawings)


def resolve_inputs(program: Program, overrides: dict[int, Any]) -> tuple[dict[int, Any], list[str]]:
    """Map input index -> value (validated); returns node-id keyed values and problems."""
    values, problems = {}, []
    for definition in program.inputs:
        if definition.index in overrides:
            try:
                values[definition.node_id] = coerce_input(definition, overrides[definition.index])
            except ValueError as exc:
                problems.append(f"{definition.title}: {exc}")
    return values, problems


def data_context(frame, *, timeframe_seconds: int, ticker: str, tickerid: str, mintick: float, currency: str = "USD",
                 basecurrency: str = "", kind: str = "crypto", description: str = "", forming_last: bool = False,
                 knowable: bool = False, knowable_until: int | None = None) -> DataContext:
    """A DataContext from an OHLCV frame (UTC ``timestamp`` column)."""
    times = (frame["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ms]")
             .astype(np.int64))
    size = len(times)
    return DataContext(
        time=times, open=frame["open"].to_numpy(dtype=float), high=frame["high"].to_numpy(dtype=float),
        low=frame["low"].to_numpy(dtype=float), close=frame["close"].to_numpy(dtype=float),
        volume=frame["volume"].to_numpy(dtype=float) if "volume" in frame else np.zeros(size),
        timeframe_seconds=timeframe_seconds, ticker=ticker, tickerid=tickerid, mintick=mintick, currency=currency,
        basecurrency=basecurrency, type=kind, description=description,
        confirmed_until=size - 1 if forming_last and size else None, knowable=knowable, knowable_until=knowable_until)


class PineExecution:
    """One compiled script bound to one data stream, reused across reruns.

    Appended bars and a changed forming (last) bar are executed incrementally
    (rollback + re-run of the last bar); any change to earlier bars, the
    inputs or the stream identity rebuilds the runtime from the first bar."""

    def __init__(self, program: Program, inputs: dict[int, Any], provider=None):
        self.program, self.inputs = program, inputs
        self.provider = provider                      # request.security() data source (see security.py)
        self.runtime: Runtime | None = None
        self.snapshot: np.ndarray | None = None      # OHLCV + time of the bars already executed
        self.identity: tuple | None = None

    def _matrix(self, data: DataContext) -> np.ndarray:
        return np.vstack([data.time.astype(float), data.open, data.high, data.low, data.close, data.volume])

    def run(self, data: DataContext, identity: tuple, provider=MISSING_PROVIDER) -> tuple[Runtime, bool]:
        if provider is not MISSING_PROVIDER:
            self.provider = provider
        matrix = self._matrix(data)
        previous = self.snapshot
        incremental = (self.runtime is not None and self.identity == identity and previous is not None
                       and previous.shape[1] >= 1 and matrix.shape[1] >= previous.shape[1]
                       and np.array_equal(previous[:, :-1], matrix[:, :previous.shape[1] - 1], equal_nan=True))
        if incremental:
            last = previous.shape[1] - 1
            if not np.array_equal(previous[:, last], matrix[:, last], equal_nan=True):
                # The previously last (forming) bar changed: roll back to its start and re-run it.
                self.runtime.rollback(last)
                self.runtime.last_bar = last - 1
                self.runtime.realtime_updates += 1
        else:
            self.runtime = Runtime(self.program, data, self.inputs,
                                   security=SecurityManager(self.provider) if self.program.security else None)
        if self.runtime.security is not None:
            self.runtime.security.set_provider(self.provider)
        self.runtime.data = data
        self.runtime.run()
        self.snapshot, self.identity = matrix, identity
        return self.runtime, incremental


def run_script(execution: PineExecution, data: DataContext, identity: tuple, prefix: str,
               provider=MISSING_PROVIDER) -> RunResult:
    started = time.perf_counter()
    try:
        before = execution.runtime.executed_bars if execution.runtime is not None else 0
        runtime, incremental = execution.run(data, identity, provider)
    except PineRuntimeError as exc:
        execution.runtime = None
        return RunResult([], {"message": exc.message, "line": exc.line, "bar_index": exc.bar_index},
                         (time.perf_counter() - started) * 1000, data.size, 0, False)
    outputs = [runtime.outputs[node_id] for node_id in execution.program.outputs if node_id in runtime.outputs]
    times = (data.time // 1000).astype(int).tolist()
    rendered = render(outputs, times, prefix)
    executed = runtime.executed_bars - (before if incremental else 0)
    contexts = [c.provenance() for c in runtime.security.all_contexts()] if runtime.security is not None else []
    drawings = render_drawings(runtime.drawings, prefix) if runtime.drawings.live else None
    return RunResult(rendered, None, (time.perf_counter() - started) * 1000, data.size, executed, incremental, contexts,
                     drawings)

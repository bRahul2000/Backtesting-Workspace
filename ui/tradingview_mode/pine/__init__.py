"""A language-driven Pine Script engine for TradingView Mode.

Pipeline (nothing here is specific to any indicator):

    Pine source -> lexer -> parser -> AST -> analyzer (scopes, qualifiers,
    capability check) -> bar-by-bar runtime (series, call-site state, rollback)
    -> built-in registries (ta.*, math.*, input.*, color.*, str.*, ...)
    -> outputs (plot family now; drawing objects later) -> render protocol.

A script that uses a Pine feature the engine does not implement yet fails
with the exact feature and line (a capability gap), never "indicator
unsupported". See ``compat.py`` for the feature-by-feature coverage.

The engine only executes source code it is given; it never fetches or
reproduces protected or invite-only scripts.
"""

from .engine import CompileResult, PineExecution, compile_script, run_script  # noqa: E402

__all__ = ["CompileResult", "PineExecution", "compile_script", "run_script"]

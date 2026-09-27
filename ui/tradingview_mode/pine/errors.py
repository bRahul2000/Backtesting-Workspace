"""Diagnostics shared by every stage of the Pine engine."""
from __future__ import annotations

from dataclasses import dataclass

#: Diagnostic kinds. ``gap`` = valid Pine that this engine does not implement yet.
ERROR, GAP, WARNING = "error", "gap", "warning"


@dataclass(frozen=True)
class Diagnostic:
    kind: str            # error | gap | warning
    message: str
    line: int            # 1-based
    col: int             # 1-based
    feature: str | None = None   # compatibility feature id for gaps

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "line": self.line, "col": self.col, "feature": self.feature}

    def text(self) -> str:
        return f"Line {self.line}: {self.message}"


class PineError(Exception):
    """A diagnostic raised as an exception (stops the current stage)."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.text())
        self.diagnostic = diagnostic


def error(message: str, line: int, col: int = 1) -> PineError:
    return PineError(Diagnostic(ERROR, message, line, col))


def gap(message: str, line: int, col: int = 1, feature: str | None = None) -> PineError:
    return PineError(Diagnostic(GAP, message, line, col, feature))


class PineRuntimeError(Exception):
    """An error while executing a bar (reported with the line and bar)."""

    def __init__(self, message: str, line: int, bar_index: int | None = None):
        super().__init__(message)
        self.message, self.line, self.bar_index = message, line, bar_index

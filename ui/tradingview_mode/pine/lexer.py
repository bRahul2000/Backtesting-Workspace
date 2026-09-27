"""Pine Script lexer (v5/v6 layout rules).

* Blocks are indented by 4 spaces or a tab (one level = 4 columns).
* A line indented by a number of spaces that is NOT a multiple of 4 continues
  the previous line (Pine's line-wrapping rule).
* Newlines inside ( ) or [ ] never end a statement.
* ``//`` comments are dropped; ``//@name value`` annotations are kept.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .errors import error

KEYWORDS = {
    "and", "or", "not", "if", "else", "for", "to", "by", "in", "while", "switch", "var", "varip",
    "true", "false", "import", "export", "method", "type", "enum", "as", "break", "continue",
}
# Longest first.
OPERATORS = (":=", "=>", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=",
             "+", "-", "*", "/", "%", "<", ">", "=", "?", ":", ",", ".", "(", ")", "[", "]")

NAME, INT, FLOAT, STRING, COLOR, OP, KEYWORD, NEWLINE, INDENT, DEDENT, EOF = (
    "NAME", "INT", "FLOAT", "STRING", "COLOR", "OP", "KEYWORD", "NEWLINE", "INDENT", "DEDENT", "EOF")

_NUMBER = re.compile(r"(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COLOR = re.compile(r"#([0-9A-Fa-f]{8}|[0-9A-Fa-f]{6})(?![0-9A-Za-z_])")
_ANNOTATION = re.compile(r"//@(\w+)\s*(?:=\s*)?(.*)")
_ESCAPES = {"n": "\n", "t": "\t", "\\": "\\", "\"": "\"", "'": "'"}


@dataclass(frozen=True)
class Token:
    kind: str
    value: object
    line: int
    col: int

    def is_op(self, *values: str) -> bool:
        return self.kind == OP and self.value in values

    def is_kw(self, *values: str) -> bool:
        return self.kind == KEYWORD and self.value in values


@dataclass(frozen=True)
class LexResult:
    tokens: list[Token]
    annotations: dict[str, str]    # e.g. {"version": "5"}


def _indent_width(line: str) -> int:
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4
        else:
            break
    return width


def tokenize(source: str) -> LexResult:
    tokens: list[Token] = []
    annotations: dict[str, str] = {}
    indents = [0]
    openers: list[tuple[str, int, int]] = []   # unclosed ( [ with their position
    started = False        # a logical line is open
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, text in enumerate(lines, start=1):
        stripped = text.strip()
        annotation = _ANNOTATION.match(stripped)
        if annotation:
            annotations[annotation.group(1)] = annotation.group(2).strip()
        if not stripped or stripped.startswith("//"):
            continue
        width = _indent_width(text)
        continuation = started and (bool(openers) or width % 4 != 0)
        if not continuation:
            if started:
                tokens.append(Token(NEWLINE, None, number - 1, 1))
            if width % 4:
                raise error("Indentation must be a multiple of 4 spaces (or tabs) for a new statement.", number, width + 1)
            level = width
            if level > indents[-1]:
                if level != indents[-1] + 4:
                    raise error("A block may only be indented one level (4 spaces) deeper.", number, width + 1)
                indents.append(level)
                tokens.append(Token(INDENT, None, number, 1))
            while level < indents[-1]:
                indents.pop()
                tokens.append(Token(DEDENT, None, number, 1))
            if level != indents[-1]:
                raise error("Inconsistent dedent.", number, width + 1)
            started = True
        position = len(text) - len(text.lstrip(" \t"))
        while position < len(text):
            char = text[position]
            col = position + 1
            if char in " \t":
                position += 1
                continue
            if text.startswith("//", position):
                break
            if char in "\"'":
                value, position = _string(text, position, number)
                tokens.append(Token(STRING, value, number, col))
                continue
            if char == "#":
                match = _COLOR.match(text, position)
                if not match:
                    raise error("Invalid color literal (use #RRGGBB or #RRGGBBAA).", number, col)
                tokens.append(Token(COLOR, match.group(1).upper(), number, col))
                position = match.end()
                continue
            if char.isdigit() or (char == "." and position + 1 < len(text) and text[position + 1].isdigit()):
                match = _NUMBER.match(text, position)
                raw = match.group(0)
                is_float = "." in raw or "e" in raw.lower()
                tokens.append(Token(FLOAT if is_float else INT, float(raw) if is_float else int(raw), number, col))
                position = match.end()
                continue
            match = _NAME.match(text, position)
            if match:
                word = match.group(0)
                tokens.append(Token(KEYWORD if word in KEYWORDS else NAME, word, number, col))
                position = match.end()
                continue
            for op in OPERATORS:
                if text.startswith(op, position):
                    if op in "([":
                        openers.append((op, number, col))
                    elif op in ")]":
                        expected = "(" if op == ")" else "["
                        if not openers or openers[-1][0] != expected:
                            raise error(f"Unexpected `{op}` (no matching `{expected}`).", number, col)
                        openers.pop()
                    tokens.append(Token(OP, op, number, col))
                    position += len(op)
                    break
            else:
                raise error(f"Unexpected character {char!r}.", number, col)
    last = len(lines)
    if openers:
        op, line, col = openers[-1]
        raise error(f"`{op}` is never closed.", line, col)
    if started:
        tokens.append(Token(NEWLINE, None, last, 1))
    while len(indents) > 1:
        indents.pop()
        tokens.append(Token(DEDENT, None, last, 1))
    tokens.append(Token(EOF, None, last + 1, 1))
    return LexResult(tokens, annotations)


def _string(text: str, start: int, line: int) -> tuple[str, int]:
    quote = text[start]
    out = []
    position = start + 1
    while position < len(text):
        char = text[position]
        if char == "\\" and position + 1 < len(text):
            nxt = text[position + 1]
            out.append(_ESCAPES.get(nxt, "\\" + nxt))
            position += 2
            continue
        if char == quote:
            return "".join(out), position + 1
        out.append(char)
        position += 1
    raise error("Unterminated string literal.", line, start + 1)

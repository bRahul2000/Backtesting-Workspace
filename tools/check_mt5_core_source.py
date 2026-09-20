"""Static checks on mt5/BTC_V3_Core_V1.mq5 that do not need MetaEditor.

MetaEditor is unavailable on this machine, so compilation cannot be claimed.
These checks catch the failures that are actually likely in a hand-written
MQL5 port: a log row that does not match its header, a drifted column
contract, an unbalanced block, or an accidental order-sending call.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "mt5" / "BTC_V3_Core_V1.mq5"

#: MQL5 calls that transmit an order. None may appear in this EA.
FORBIDDEN_CALLS = (
    "OrderSend", "OrderSendAsync", "PositionClose", "PositionOpen",
    "OrderModify", "OrderDelete", "CTrade", "trade.Buy", "trade.Sell",
)


def strip_comments_and_strings(source: str) -> str:
    """Code only: a forbidden call named in a comment is documentation, not a
    transmission path, and must not be reported as one."""
    out, index, length = [], 0, len(source)
    while index < length:
        pair = source[index:index + 2]
        if pair == "//":
            index = source.find("\n", index)
            if index == -1:
                break
            continue
        if pair == "/*":
            end = source.find("*/", index + 2)
            index = length if end == -1 else end + 2
            continue
        char = source[index]
        if char == '"':
            index += 1
            while index < length and source[index] != '"':
                index += 2 if source[index] == "\\" else 1
            index += 1
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _split_top_level(text: str) -> list[str]:
    """Split a call's argument list on commas that are not nested or quoted."""
    parts, depth, current, in_string = [], 0, [], False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            if char == "\\":
                current.append(char)
                index += 1
                if index < len(text):
                    current.append(text[index])
                index += 1
                continue
            if char == '"':
                in_string = False
            current.append(char)
        elif char == '"':
            in_string = True
            current.append(char)
        elif char in "([":
            depth += 1
            current.append(char)
        elif char in ")]":
            depth -= 1
            current.append(char)
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    if current:
        parts.append("".join(current).strip())
    return [part for part in parts if part]


def file_write_calls(source: str) -> list[list[str]]:
    """Every FileWrite(g_file, ...) argument list, minus the handle.

    Retained for diagnostics. The EA no longer uses FileWrite for audit rows:
    MQL5 caps a function at 64 parameters and the schema has 76 columns, so
    rows are serialized by WriteAuditRow instead.
    """
    calls = []
    for match in re.finditer(r"FileWrite\s*\(", source):
        start = match.end()
        depth, index, in_string = 1, start, False
        while index < len(source) and depth:
            char = source[index]
            if in_string:
                if char == "\\":
                    index += 2
                    continue
                if char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            index += 1
        arguments = _split_top_level(source[start:index - 1])
        if arguments and arguments[0] == "g_file":
            calls.append(arguments[1:])
    return calls


def _function_body(source: str, signature: str) -> str:
    """Source text of one function, from its signature to its closing brace."""
    start = source.index(signature)
    open_brace = source.index("{", start)
    depth, index = 0, open_brace
    while index < len(source):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[open_brace:index + 1]
        index += 1
    raise ValueError(f"Unbalanced body for {signature!r}")


FIELD_ASSIGNMENT = re.compile(r"fields\[n\+\+\]\s*=\s*(.+?);\s*(?:\n|$)", re.S)


def field_assignments(source: str, signature: str) -> list[str]:
    """Ordered `fields[n++] = ...;` expressions inside one function."""
    body = _function_body(source, signature)
    return [re.sub(r"\s+", " ", match.group(1)).strip()
            for match in FIELD_ASSIGNMENT.finditer(body)]


def header_column_names(source: str) -> list[str]:
    """Header literals in emission order, unquoted."""
    names = []
    for expression in field_assignments(source, "bool WriteAuditHeader()"):
        if expression.startswith('"') and expression.endswith('"'):
            names.append(expression[1:-1])
        else:
            names.append(expression)
    return names


def check(source_path: Path = SOURCE) -> dict[str, object]:
    source = source_path.read_text(encoding="utf-8")
    code = strip_comments_and_strings(source)
    header = header_column_names(source)
    row = field_assignments(source, "void ProcessClosedBar(const int shift)")

    from tools.core_audit_schema import AUDIT_COLUMNS

    report: dict[str, object] = {
        "braces_balanced": source.count("{") == source.count("}"),
        "parens_balanced": source.count("(") == source.count(")"),
        "header_columns": len(header),
        "row_columns": len(row),
        "row_columns_match_header": len(header) == len(row) > 0,
        "header_matches_python_schema": header == AUDIT_COLUMNS,
        "declares_audit_column_count": f"#define AUDIT_COLUMN_COUNT {len(AUDIT_COLUMNS)}" in source,
        # MQL5 caps a function at 64 parameters; no call may pass the schema.
        "no_oversized_file_write": all(len(call) <= 60 for call in file_write_calls(source)),
        "uses_string_serialization": "FileWriteString(g_file,CsvJoin(fields)" in code.replace(" ", ""),
        "has_csv_escape": "string CsvEscape(" in source,
        "has_csv_join": "string CsvJoin(" in source,
        "has_write_audit_header": "bool WriteAuditHeader()" in source,
        "has_write_audit_row": "bool WriteAuditRow(" in source,
        "single_row_terminator": code.count("CsvJoin(fields)") == 1,
        "forbidden_calls": sorted(
            name for name in FORBIDDEN_CALLS
            if re.search(rf"\b{re.escape(name)}\b", code)),
        "has_execution_guard": "SendOrderGuard" in source,
        "default_mode_is_audit_only": bool(
            re.search(r"input\s+ExecutionMode\s+InpMode\s*=\s*AUDIT_ONLY", source)),
        "declares_audit_only_status": "AUDIT ONLY — NO ORDERS" in source,
        "core_fingerprint_present": "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd" in source,
        "evaluates_only_closed_bars": "ProcessClosedBar(1)" in source,
    }
    return report


def main() -> int:
    report = check()
    ok = True
    for key, value in report.items():
        flag = value if isinstance(value, bool) else (value == [] if key == "forbidden_calls" else True)
        ok &= bool(flag)
        print(f"{'OK  ' if flag else 'FAIL'} {key}: {value}")
    print("\nStatic checks:", "PASS" if ok else "FAIL")
    print("NOTE: this is not a compile. MetaEditor F7 is still required.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

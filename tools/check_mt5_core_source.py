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
    """Every FileWrite(g_file, ...) argument list, minus the handle."""
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


def check(source_path: Path = SOURCE) -> dict[str, object]:
    source = source_path.read_text(encoding="utf-8")
    calls = file_write_calls(source)
    header = next((call for call in calls if call and call[0] == '"bar_time_utc"'), None)
    rows = [call for call in calls if call is not header]
    report: dict[str, object] = {
        "braces_balanced": source.count("{") == source.count("}"),
        "parens_balanced": source.count("(") == source.count(")"),
        "header_columns": len(header) if header else 0,
        "row_column_counts": [len(call) for call in rows],
        "forbidden_calls": sorted(
            name for name in FORBIDDEN_CALLS
            if re.search(rf"\b{re.escape(name)}\b", strip_comments_and_strings(source))),
        "has_execution_guard": "SendOrderGuard" in source,
        "default_mode_is_audit_only": bool(
            re.search(r"input\s+ExecutionMode\s+InpMode\s*=\s*AUDIT_ONLY", source)),
        "declares_audit_only_status": "AUDIT ONLY — NO ORDERS" in source,
        "core_fingerprint_present": "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd" in source,
        "evaluates_only_closed_bars": "ProcessClosedBar(1)" in source,
    }
    report["row_columns_match_header"] = bool(
        header and rows and all(count == len(header) for count in report["row_column_counts"]))
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

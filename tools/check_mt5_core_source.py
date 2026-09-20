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


def defines(source: str) -> dict[str, int]:
    """Integer #define values declared by the EA."""
    return {name: int(value) for name, value in
            re.findall(r"^#define\s+([A-Z0-9_]+)\s+(\d+)\s*$", source, re.M)}


def warmup_m15_bars(source: str) -> int:
    """CoreWarmupM15Bars() evaluated from the EA's own constants."""
    d = defines(source)
    shared = max(d["A4_EMA_SLOW"], d["A4_ATR_LENGTH"], d["A4_RSI_LENGTH"] + 1,
                 d["A4_DI_LENGTH"] + d["A4_ADX_SMOOTHING"])
    a4 = max(shared, d["A4_STRUCTURE_LOOKBACK"] + 1)
    t3 = max(shared, d["T3_STRUCTURE_LOOKBACK"] + 1,
             d["T3_RANGE_SWEEP_LOOKBACK"] + 1, d["T3_STOP_LOOKBACK"])
    return max(a4, t3)


def warmup_h1_bars(source: str) -> int:
    d = defines(source)
    return max(d["A4_H1_SLOW"] + d["A4_H1_SLOPE_LOOKBACK"], d["A4_H1_ATR"])


#: Reject codes are audit metadata, but a code only one side can emit makes the
#: comparator report a mismatch on every bar that reaches it. Both vocabularies
#: must be identical, so a new branch on either side is a visible failure.
CODE_PATTERN = re.compile(r'"([AT][43]_[A-Z0-9_]+)"')


def reject_codes(text: str) -> set[str]:
    return {code for code in CODE_PATTERN.findall(text) if not code.endswith("_")}


def python_reject_codes() -> set[str]:
    exporter = (ROOT / "tools/export_python_core_audit.py").read_text(encoding="utf-8")
    codes = reject_codes(exporter)
    # A4_CONTEXT_OK is an internal sentinel: it is always replaced by a
    # pullback-stage code before it can reach a row.
    return codes - {"A4_CONTEXT_OK"}


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
        # The twin must not search before the frozen descriptor's warmup
        # resolver says the Python side would.
        "honours_warmup_window": all(
            token in code for token in ("CoreFirstSearchTime", "CoreWarmupH1Bars",
                                        "CoreWarmupM15Bars")),
        "warmup_m15_bars": warmup_m15_bars(source),
        "warmup_h1_bars": warmup_h1_bars(source),
        "emits_before_window_codes": all(
            f'"{code}"' in source for code in ("A4_BEFORE_WINDOW", "T3_BEFORE_WINDOW")),
        # btc_v3_l2_trend_pullback_long.on_candle clears the pullback on both of
        # these branches; forgetting either carries stale state across a day.
        "resets_pullback_out_of_session": bool(re.search(
            r"if\(!bar\.in_session\)\s*\{?\s*ResetPullback\(false\);", code)),
        "resets_pullback_at_daily_cap": bool(re.search(
            r"trades_today>=MAX_TRADES_PER_DAY\)\s*\{?\s*ResetPullback\(false\);", code)),
        # +DI/-DI are published as soon as the DI RMAs seed, before ADX does.
        "publishes_di_before_adx": "bar.has_di" in code and code.count("bar.has_di") >= 3,
        # Position.initial_risk is the risk budget and survives the leverage cap.
        "planned_risk_is_budget": bool(re.search(r"planned_risk\s*=\s*budget\s*;", code)),
        "reject_codes_match_python": reject_codes(source) == python_reject_codes(),
        # The frozen children cancel their own pending order before any other
        # decision; a twin that only lets orders expire can fill one the frozen
        # strategy had already withdrawn.
        "implements_pending_cancellation": all(
            token in code for token in ("ShouldCancelPending", "A4ContextValid",
                                        "A4MaterialBelowEma50")),
        # Only the child that owns the order may cancel it, and it reads that
        # child's own trade counter.
        "cancellation_respects_order_ownership": bool(re.search(
            r"is_a4\s*=\s*\(\s*g_order\.setup_id\s*==\s*A4_SETUP_ID\s*\)", code)
            and re.search(r"is_a4\s*\?\s*g_a4\.trades_today\s*:\s*g_t3\.trades_today", code)),
        # A4 cancels on invalidated context, T3 does not. The asymmetry is real.
        "only_a4_cancels_on_context": bool(re.search(
            r"is_a4\s*&&\s*\(!A4ContextValid\(bar\)\s*\|\|\s*A4MaterialBelowEma50\(bar\)\)",
            code)),
        "emits_cancelled_status": '"CANCELLED"' in source,
        # --- Stage 3 live-forward runtime -------------------------------
        # Only closed bars are ever evaluated. shift 0 is the forming bar and
        # must never reach ProcessClosedBar.
        "never_processes_forming_bar": "ProcessClosedBar(0)" not in code,
        "closed_bar_scheduler_present": "ProcessPendingBars" in code,
        # Every pending closed bar is consumed oldest-first, so a bar that
        # closed while the terminal was down is back-filled rather than lost.
        "backfills_missed_bars": bool(re.search(
            r"for\(int s=shift-1; s>=1; s--\)\s*ProcessClosedBar\(s\);", code)),
        "rejects_duplicate_bar": bool(re.search(
            r"bar\.time==g_last_processed", code)) and "g_duplicate_bars++" in code,
        "rejects_time_reversal": bool(re.search(
            r"bar\.time<g_last_processed", code)) and "g_reversed_bars++" in code,
        # Emission is exactly-once: a replayed bar rebuilds state silently.
        "exactly_once_emission": bool(re.search(
            r"g_last_logged==0 \|\| bar\.time>g_last_logged", code)),
        # Recovery is replay from a fixed anchor, never a deserialised state.
        "replays_from_fixed_anchor": all(t in code for t in ("g_anchor", "ReadSessionFile",
                                                             "WriteSessionFile")),
        "halts_if_anchor_unreachable": "ANCHOR_UNREACHABLE" in source,
        # A live restart must never truncate forward evidence.
        "live_run_appends_audit": bool(re.search(
            r"bool append = InpAppendLog \|\| !IsTesterRun\(\);", code)),
        # Stage 2 tester semantics must stay reachable and unchanged.
        "tester_path_preserved": bool(re.search(
            r"else if\(g_last_bar_time!=0\)\s*ProcessClosedBar\(1\);", code)),
        "records_run_identity": all(t in source for t in (
            "session_id", "twin_build", "compiled_utc", "core_fingerprint",
            "a4_fingerprint", "t3_fingerprint", "anchor_utc", "restarts",
            "reconnects", "server_utc_offset_secs", "tick_size")),
        "tracks_connectivity": all(t in code for t in ("PollConnectivity",
                                                       "TERMINAL_CONNECTED", "g_reconnects")),
        "logs_operational_events": all(f'"{k}"' in source for k in (
            "SESSION_START", "RESTART", "RECONNECT", "DISCONNECT", "TICK_OUTAGE",
            "DATA_GAP", "BACKFILL", "DUPLICATE_BAR", "TIME_REVERSAL", "DEINIT")),
        # A datetime assigned into a string is an implicit cast and a compiler
        # warning. Print() is variadic and formats its own arguments, so only
        # assignment contexts are checked here.
        # The anchor bar must be reachable AND replayed. Anchoring at the cap
        # with a strictly-older test made every first start halt.
        "anchor_bar_is_reachable": bool(re.search(
            r"while\(shift <= InpMaxReplayBars\)", code))
            and bool(re.search(r"stamp==g_anchor\)\s*\{ reached=true; break; \}", code)),
        # A new session anchors at warmup depth, never at the safety cap.
        "anchor_depth_is_warmup_based": "InpAnchorWarmupBars" in code
            and "CoreWarmupH1Bars()*4" in code,
        # A failed bring-up must not persist its anchor.
        # ProcessPendingBars() must be followed by a halt check that returns
        # before WriteSessionFile(), so a failed bring-up cannot persist its
        # anchor and be resurrected by a plain restart.
        "halted_bringup_is_not_persisted": bool(re.search(
            r"ProcessPendingBars\(\);\s*if\(g_halted\)\s*\{[^}]*?return INIT_SUCCEEDED;\s*\}",
            code, re.S)),
        # A fresh session preserves the previous one's evidence by renaming it.
        "fresh_session_rotates_not_deletes": all(t in code for t in (
            "RotateStageFile", "RotateSessionEvidence", "FileMove", "InpNewSession"))
            and "FileDelete" not in code,
        "no_implicit_datetime_to_string": not re.search(
            r"=\s*__DATETIME__\s*;", code),
        "stage3_files_separate_from_audit_schema": all(t in source for t in (
            "InpSessionFile", "InpEventFile", "SESSION_SCHEMA_VERSION",
            "EVENT_SCHEMA_VERSION")),
    }
    report["reject_codes_only_in_mt5"] = sorted(reject_codes(source) - python_reject_codes())
    report["reject_codes_only_in_python"] = sorted(python_reject_codes() - reject_codes(source))
    return report


LIST_CHECKS = ("forbidden_calls", "reject_codes_only_in_mt5", "reject_codes_only_in_python")


def main() -> int:
    report = check()
    ok = True
    for key, value in report.items():
        flag = value if isinstance(value, bool) else (value == [] if key in LIST_CHECKS else True)
        ok &= bool(flag)
        print(f"{'OK  ' if flag else 'FAIL'} {key}: {value}")
    print("\nStatic checks:", "PASS" if ok else "FAIL")
    print("NOTE: this is not a compile. MetaEditor F7 is still required.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""R4 Stage 2 — compare the Python and MT5 BTC Core audit streams.

Both sides emit the schema in tools/core_audit_schema.py, one row per closed
M15 bar. This module aligns them on the bar's UTC open time and reports the
FIRST divergence for each affected bar, signal and trade, so a cascade is
diagnosed at its cause rather than at its symptoms.

A missing MT5 record is never a match. Tolerances are explicit and tight; a
price difference of one point or less is still reported, as ROUNDING_MISMATCH.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.core_audit_schema import (                                     # noqa: E402
    AUDIT_COLUMNS, EXACT_TOLERANCE, INDICATOR_TOLERANCE, KEY, LEVEL_COLUMNS,
    ROUNDING_TOLERANCE, STATE_COLUMNS,
)

#: Divergence classes, checked in causal order: the first one that fires is the
#: reported cause, because everything after it is downstream of it.
CLASSES = [
    "DATA_MISMATCH",
    "SPREAD_MISMATCH",
    "TIMESTAMP_ALIGNMENT",
    "H1_ALIGNMENT",
    "INDICATOR_MISMATCH",
    "STATE_MISMATCH",
    "CONTEXT_MISMATCH",
    "LEVEL_MISMATCH",
    "SIGNAL_MISMATCH",
    "PENDING_STATE_MISMATCH",
    "ENTRY_PRICE_MISMATCH",
    "SL_MISMATCH",
    "TP_MISMATCH",
    "EXIT_MISMATCH",
    "ROUNDING_MISMATCH",
    "WINDOW_BOUNDARY",
    "UNKNOWN",
]

#: Columns that make a bar a decision. A bar carrying any of them can never be
#: written off as a boundary artefact.
DECISION_COLUMNS = ["signal_side", "signal_setup_id", "a4_signal_pass",
                    "t3_signal_pass", "pending_status", "entry_time_utc",
                    "exit_time_utc"]


def _is_decision_free(row: pd.Series) -> bool:
    return all(row[column] in ("", "0") for column in DECISION_COLUMNS)

#: (class, columns, tolerance) in the order they are evaluated.
CHECKS: list[tuple[str, list[str], float]] = [
    ("DATA_MISMATCH", ["open", "high", "low", "close", "tick_volume"], EXACT_TOLERANCE),
    ("SPREAD_MISMATCH", ["spread_points", "spread_price"], EXACT_TOLERANCE),
    ("H1_ALIGNMENT", ["h1_open", "h1_high", "h1_low", "h1_close"], EXACT_TOLERANCE),
    ("INDICATOR_MISMATCH",
     ["ema20", "ema50", "atr", "rsi", "adx", "plus_di", "minus_di", "body_percent",
      "h1_ema50", "h1_ema200", "h1_ema200_past", "h1_atr", "h1_slope", "h1_slope_atr",
      "h1_separation_atr"], INDICATOR_TOLERANCE),
    # Carried state before the codes it explains: a pullback that only one side
    # thinks is active shows up here, on the bar it actually diverged, instead
    # of surfacing bars later as an unexplained reject-code difference.
    ("STATE_MISMATCH", STATE_COLUMNS, INDICATOR_TOLERANCE),
    ("CONTEXT_MISMATCH",
     ["a4_context_pass", "a4_reject_code", "t3_context_pass", "t3_reject_code",
      "t3_regime", "a4_in_session"], 0.0),
    ("LEVEL_MISMATCH", LEVEL_COLUMNS, INDICATOR_TOLERANCE),
    ("SIGNAL_MISMATCH",
     ["a4_signal_pass", "t3_signal_pass", "signal_side", "signal_setup_id",
      "signal_time_utc"], 0.0),
    # Derived prices are compared exactly. ROUNDING_TOLERANCE below is a
    # labelling threshold, not an equality allowance: a sub-point difference is
    # still reported, as ROUNDING_MISMATCH, never silently treated as equal.
    ("PENDING_STATE_MISMATCH",
     ["pending_status", "pending_trigger", "pending_stop", "pending_expiry_utc"],
     EXACT_TOLERANCE),
    ("ENTRY_PRICE_MISMATCH", ["entry_time_utc", "entry_price"], EXACT_TOLERANCE),
    ("SL_MISMATCH", ["entry_stop"], EXACT_TOLERANCE),
    ("TP_MISMATCH", ["entry_target"], EXACT_TOLERANCE),
    ("EXIT_MISMATCH",
     ["exit_time_utc", "exit_price", "exit_reason", "realized_r"], EXACT_TOLERANCE),
]

#: Parity is also reported per dimension, so a single stubborn column cannot be
#: hidden inside an overall percentage.
DIMENSIONS: list[tuple[str, list[str]]] = [
    ("ohlc", ["open", "high", "low", "close"]),
    ("volume_and_spread", ["tick_volume", "spread_points", "spread_price"]),
    ("h1_context", ["h1_time_utc", "h1_open", "h1_high", "h1_low", "h1_close",
                    "h1_ema50", "h1_ema200", "h1_ema200_past", "h1_atr",
                    "h1_slope", "h1_slope_atr", "h1_separation_atr"]),
    ("indicators", ["ema20", "ema50", "atr", "rsi", "adx", "plus_di",
                    "minus_di", "body_percent"]),
    ("carried_state", STATE_COLUMNS),
    ("a4_context", ["a4_context_pass", "a4_reject_code", "a4_in_session"]),
    ("a4_signal", ["a4_signal_pass", "a4_trigger", "a4_stop", "a4_stop_atr"]),
    ("t3_context", ["t3_context_pass", "t3_reject_code", "t3_regime"]),
    ("t3_signal", ["t3_signal_pass", "t3_trigger", "t3_stop", "t3_stop_atr"]),
    ("signal", ["signal_side", "signal_setup_id", "signal_time_utc"]),
    ("pending", ["pending_status", "pending_trigger", "pending_stop",
                 "pending_expiry_utc"]),
    ("entry", ["entry_time_utc", "entry_price"]),
    ("stop_and_target", ["entry_stop", "entry_target"]),
    ("exit", ["exit_time_utc", "exit_price", "exit_reason", "realized_r"]),
]

ENTRY_FIELDS = ["entry_time_utc", "entry_price", "entry_stop", "entry_target"]
EXIT_FIELDS = ["exit_time_utc", "exit_price", "exit_reason", "realized_r"]


def _trade_table(frame: pd.DataFrame) -> tuple[list[tuple], int]:
    """Whole trades in bar order: each entry paired with the exit that closes it.

    Entries and exits must NOT be zipped positionally. A segment reset abandons
    the open position, leaving an entry with no exit, and from then on index i
    of one list is a different trade from index i of the other. Only one
    position exists at a time, so walking the bars and closing the currently
    open trade is both correct and unambiguous.
    """
    trades: list[tuple] = []
    unmatched_exits = 0
    open_entry: tuple | None = None
    blank = (None,) * len(EXIT_FIELDS)
    for row in frame.itertuples(index=False):
        if row.entry_time_utc != "":
            if open_entry is not None:
                # A new entry while one is still open means the previous
                # position was abandoned — a segment reset drops it. Record it
                # as unclosed rather than letting it vanish.
                trades.append(open_entry + blank)
            open_entry = tuple(getattr(row, field) for field in ENTRY_FIELDS)
        if row.exit_time_utc != "":
            if open_entry is None:
                unmatched_exits += 1
                continue
            trades.append(open_entry + tuple(getattr(row, field) for field in EXIT_FIELDS))
            open_entry = None
    if open_entry is not None:
        trades.append(open_entry + blank)
    return trades, unmatched_exits


#: Timestamp columns whose disagreement is an alignment problem, not a value one.
H1_TIME_COLUMN = "h1_time_utc"


def load_audit(path: str | Path, *, label: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in AUDIT_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} audit is missing columns: {missing}")
    frame = frame[AUDIT_COLUMNS].copy()
    collapsed = 0
    if frame[KEY].duplicated().any():
        # An EA rerun that appends into an existing log writes every bar again.
        # Identical repeats are recoverable and collapsing them is lossless, so
        # do it here — inside the tool, with the count reported — rather than
        # leaving an untracked manual edit in the evidence chain. Repeats that
        # actually disagree are two different runs and are still refused.
        deduped = frame.drop_duplicates(subset=AUDIT_COLUMNS)
        if deduped[KEY].duplicated().any():
            conflict = deduped.loc[deduped[KEY].duplicated(), KEY].iloc[0]
            raise ValueError(
                f"{label} audit has conflicting rows for the same {KEY}, first at "
                f"{conflict}. Two different runs are mixed in one file.")
        collapsed = len(frame) - len(deduped)
        print(f"{label} audit: collapsed {collapsed:,} identical repeated bars "
              f"(an appended rerun); {len(deduped):,} distinct bars remain.")
        frame = deduped
    frame = frame.sort_values(KEY).reset_index(drop=True)
    frame.attrs["duplicates_collapsed"] = collapsed
    return frame


def _numeric(value: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _differs(left: str, right: str, tolerance: float) -> tuple[bool, float | None]:
    """Compare one cell. Returns (differs, absolute numeric delta if numeric)."""
    if left == right:
        return False, 0.0
    a, b = _numeric(left), _numeric(right)
    if a is None or b is None:
        # One side blank or non-numeric and they are not equal as text.
        return True, None
    delta = abs(a - b)
    if tolerance > 0 and delta <= tolerance:
        return False, delta
    # Relative allowance for indicator-scale values.
    if tolerance == INDICATOR_TOLERANCE:
        scale = max(abs(a), abs(b), 1.0)
        if delta / scale <= tolerance:
            return False, delta
    return True, delta


def classify_row(python_row: pd.Series, mt5_row: pd.Series) -> dict | None:
    """First divergence for one aligned bar, or None when the bar matches."""
    if python_row[H1_TIME_COLUMN] != mt5_row[H1_TIME_COLUMN]:
        return {"classification": "H1_ALIGNMENT", "column": H1_TIME_COLUMN,
                "python": python_row[H1_TIME_COLUMN], "mt5": mt5_row[H1_TIME_COLUMN],
                "delta": None}
    for label, columns, tolerance in CHECKS:
        for column in columns:
            differs, delta = _differs(python_row[column], mt5_row[column], tolerance)
            if not differs:
                continue
            classification = label
            # A derived price within one point is a rounding artefact, and is
            # reported as such rather than hidden or over-stated.
            # Only *derived* prices may be reclassified. Raw broker data and
            # H1 aggregates must be bit-identical, so a difference there is a
            # data problem however small it is.
            # The boundary is widened by EXACT_TOLERANCE so that a difference of
            # exactly one point, which in float64 is 0.010000000000005, still
            # lands in the rounding bucket instead of looking structural.
            if (delta is not None and 0 < delta <= ROUNDING_TOLERANCE + EXACT_TOLERANCE
                    and label in ("PENDING_STATE_MISMATCH", "ENTRY_PRICE_MISMATCH",
                                  "SL_MISMATCH", "TP_MISMATCH", "EXIT_MISMATCH")):
                classification = "ROUNDING_MISMATCH"
            return {"classification": classification, "column": column,
                    "python": python_row[column], "mt5": mt5_row[column], "delta": delta}
    return None


def compare(python_audit: pd.DataFrame, mt5_audit: pd.DataFrame) -> dict:
    left = python_audit.set_index(KEY)
    right = mt5_audit.set_index(KEY)
    common = left.index.intersection(right.index)
    only_python = sorted(set(left.index) - set(right.index))
    only_mt5 = sorted(set(right.index) - set(left.index))

    rows: list[dict] = []
    for stamp in sorted(common):
        divergence = classify_row(left.loc[stamp], right.loc[stamp])
        if divergence is not None:
            rows.append({KEY: stamp, **divergence})

    # A bar present on one side only is never a match.
    mismatched_common = len({row[KEY] for row in rows})

    # The EA evaluates ProcessClosedBar(1), the just-closed bar — the safeguard
    # that stops it reading a forming bar. A run therefore can never log the
    # final bar of its own range, so a Python audit run to the same end date
    # always carries a short decision-free tail past the last MT5 bar.
    #
    # That tail is a window boundary, not a parity failure. The allowance is
    # deliberately narrow: it applies only to bars strictly after the last MT5
    # bar, and only while they carry no signal, pending order, entry or exit. A
    # Python-only bar INSIDE the MT5 range, any MT5-only bar, and any trailing
    # bar holding a decision all stay hard failures.
    last_mt5 = max(right.index) if len(right.index) else None
    trailing = [s for s in only_python if last_mt5 is not None and s > last_mt5]
    trailing_inert = [s for s in trailing if _is_decision_free(left.loc[s])]
    boundary = set(trailing_inert)
    unresolved_python = [s for s in only_python if s not in boundary]

    for stamp in only_python:
        if stamp in boundary:
            rows.append({KEY: stamp, "classification": "WINDOW_BOUNDARY", "column": KEY,
                         "python": "present", "mt5": "after the last logged bar",
                         "delta": None})
        else:
            rows.append({KEY: stamp, "classification": "TIMESTAMP_ALIGNMENT",
                         "column": KEY, "python": "present", "mt5": "MISSING",
                         "delta": None})
    for stamp in only_mt5:
        rows.append({KEY: stamp, "classification": "TIMESTAMP_ALIGNMENT",
                     "column": KEY, "python": "MISSING", "mt5": "present", "delta": None})

    detail = pd.DataFrame(rows, columns=[KEY, "classification", "column",
                                         "python", "mt5", "delta"])
    if not detail.empty:
        detail = detail.sort_values(KEY).reset_index(drop=True)

    compared = len(common)
    counts = detail.classification.value_counts().to_dict() if not detail.empty else {}
    mismatched_bars = mismatched_common

    def _agree(columns: list[str]) -> int:
        if compared == 0:
            return 0
        agree = 0
        for stamp in common:
            if all(not _differs(left.loc[stamp, column], right.loc[stamp, column],
                                EXACT_TOLERANCE if column in ("open", "high", "low", "close")
                                else INDICATOR_TOLERANCE)[0] for column in columns):
                agree += 1
        return agree

    worst: list[dict] = []
    if not detail.empty:
        numeric = detail.loc[detail.delta.notna() & (detail.delta > 0)]
        if not numeric.empty:
            worst = (numeric.sort_values("delta", ascending=False)
                     .head(10)[[KEY, "classification", "column", "python", "mt5", "delta"]]
                     .to_dict("records"))

    dimensions = {name: {"matching": _agree(columns),
                         "of": compared,
                         "percent": (round(100 * _agree(columns) / compared, 6)
                                     if compared else None)}
                  for name, columns in DIMENSIONS}

    # Full-trade parity over whole trades, including any left unclosed.
    py_trades, py_orphan_exits = _trade_table(python_audit)
    mt_trades, mt_orphan_exits = _trade_table(mt5_audit)
    full_trades = sum(1 for a, b in zip(py_trades, mt_trades) if a == b)
    py_unclosed = sum(1 for t in py_trades if t[-1] is None)
    mt_unclosed = sum(1 for t in mt_trades if t[-1] is None)

    signal_rows = left.loc[left.signal_side != ""]
    trade_rows = left.loc[left.entry_time_utc != ""]
    exit_rows = left.loc[left.exit_time_utc != ""]
    mismatched = set(detail[KEY]) if not detail.empty else set()

    return {
        "python_duplicate_bars_collapsed": int(python_audit.attrs.get("duplicates_collapsed", 0)),
        "mt5_duplicate_bars_collapsed": int(mt5_audit.attrs.get("duplicates_collapsed", 0)),
        "bars_compared": compared,
        "bars_only_in_python": len(only_python),
        "bars_only_in_mt5": len(only_mt5),
        "last_mt5_bar": last_mt5,
        "window_boundary_bars": sorted(boundary),
        "unresolved_one_sided_bars": sorted(unresolved_python) + sorted(only_mt5),
        "bars_matching": compared - mismatched_common,
        "bars_mismatching": mismatched_common,
        "decision_parity_percent": (float(100 * (compared - mismatched_common) / compared)
                                    if compared else None),
        "exact_ohlc_matches": _agree(["open", "high", "low", "close"]),
        "indicator_matches": _agree(["ema20", "ema50", "atr", "rsi", "adx"]),
        "a4_decision_matches": _agree(["a4_context_pass", "a4_signal_pass", "a4_reject_code"]),
        "t3_decision_matches": _agree(["t3_context_pass", "t3_signal_pass", "t3_reject_code"]),
        "signal_matches": _agree(["signal_side", "signal_setup_id", "signal_time_utc"]),
        "pending_matches": _agree(["pending_status", "pending_trigger", "pending_stop"]),
        "entry_matches": _agree(["entry_time_utc", "entry_price", "entry_stop", "entry_target"]),
        "exit_matches": _agree(["exit_time_utc", "exit_price", "exit_reason", "realized_r"]),
        "python_signals": int(len(signal_rows)),
        "python_entries": int(len(trade_rows)),
        "python_exits": int(len(exit_rows)),
        "signals_with_a_divergence": int(sum(1 for stamp in signal_rows.index if stamp in mismatched)),
        "trades_with_a_divergence": int(sum(1 for stamp in trade_rows.index if stamp in mismatched)),
        "dimensions": dimensions,
        "python_trades": len(py_trades),
        "mt5_trades": len(mt_trades),
        "python_unclosed_trades": py_unclosed,
        "mt5_unclosed_trades": mt_unclosed,
        "python_unmatched_exits": py_orphan_exits,
        "mt5_unmatched_exits": mt_orphan_exits,
        "full_trade_matches": full_trades,
        "full_trade_parity": (bool(full_trades == len(py_trades) == len(mt_trades))
                              if py_trades or mt_trades else None),
        "mismatch_counts": counts,
        "first_mismatch": (detail.iloc[0].to_dict() if not detail.empty else None),
        "first_20_mismatches": (detail.head(20).to_dict("records") if not detail.empty else []),
        "worst_numeric_differences": worst,
        "full_parity": bool(compared > 0 and mismatched_common == 0
                            and not unresolved_python and not only_mt5),
        "acceptance_criterion": (
            "100% strategy decision parity over every compared bar; no MT5-only "
            "bar; no Python-only bar inside the MT5 range; and any Python bars "
            "past the last logged MT5 bar must carry no signal, pending order, "
            "entry or exit."),
        "_detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-audit", type=Path, required=True)
    parser.add_argument("--mt5-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/validation/mt5_core_parity.json")
    parser.add_argument("--detail", type=Path,
                        default=ROOT / "reports/validation/mt5_core_parity_detail.csv")
    args = parser.parse_args()

    python_audit = load_audit(args.python_audit, label="Python")
    mt5_audit = load_audit(args.mt5_audit, label="MT5")
    report = compare(python_audit, mt5_audit)
    detail = report.pop("_detail")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    detail.to_csv(args.detail, index=False)

    print(f"bars compared        : {report['bars_compared']:,}")
    print(f"python-only / mt5-only: {report['bars_only_in_python']} / {report['bars_only_in_mt5']}"
          f"   (decision-free tail past {report['last_mt5_bar']}: "
          f"{len(report['window_boundary_bars'])})")
    if report["unresolved_one_sided_bars"]:
        print(f"UNRESOLVED one-sided  : {report['unresolved_one_sided_bars'][:5]}")
    print(f"decision parity      : {report['decision_parity_percent']}%")
    print(f"trades py / mt5      : {report['python_trades']} / {report['mt5_trades']}"
          f"   fully matching: {report['full_trade_matches']}"
          f"   unclosed: {report['python_unclosed_trades']}/{report['mt5_unclosed_trades']}")
    for name, stat in report["dimensions"].items():
        print(f"  {name:20} {stat['matching']:>6}/{stat['of']:<6} {stat['percent']}%")
    print(f"mismatch counts      : {report['mismatch_counts']}")
    if report["first_mismatch"]:
        print(f"first divergence     : {report['first_mismatch']}")
    print(f"FULL PARITY          : {report['full_parity']}")
    return 0 if report["full_parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

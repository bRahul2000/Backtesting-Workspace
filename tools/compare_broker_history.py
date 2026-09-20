"""Compare a fresh broker history export against the validated R1 export.

Answers one question: has the broker revised bars we already certified against?

Read-only on both inputs. It never edits, patches or reconciles broker data —
a difference is reported, never repaired.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Fields compared on every bar the two exports share.
FIELDS = ["open", "high", "low", "close", "tick_volume", "spread", "real_volume"]

#: Windows whose parity has already been certified, plus the one under review.
#: A revised bar inside a certified window invalidates that certificate.
CERTIFIED_WINDOWS = {
    "window1 (certified)": ("2026-01-01", "2026-03-01"),
    "window2 (certified)": ("2025-09-01", "2025-12-01"),
    "window3 (daily cap)": ("2026-03-01", "2026-05-10"),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> pd.DataFrame:
    """Raw exporter layout, timestamps parsed but values kept as text.

    Values stay as strings so a comparison is byte-exact and cannot be blurred
    by float parsing.
    """
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    stamp = "timestamp" if "timestamp" in frame.columns else frame.columns[0]
    frame["_t"] = pd.to_datetime(frame[stamp], format="%Y.%m.%d %H:%M:%S",
                                 utc=True, errors="coerce")
    if frame["_t"].isna().any():
        frame["_t"] = pd.to_datetime(frame[stamp], utc=True, errors="coerce")
    if frame["_t"].isna().any():
        raise ValueError(f"{path}: unparsable timestamps")
    if frame["_t"].duplicated().any():
        first = frame.loc[frame["_t"].duplicated(), "_t"].iloc[0]
        raise ValueError(f"{path}: duplicate bar at {first}")
    return frame.set_index("_t").sort_index()


def segments(index: pd.DatetimeIndex, step_seconds: int) -> list[tuple]:
    step = pd.Timedelta(seconds=step_seconds)
    return [(str(index[i - 1]), str(index[i]))
            for i in range(1, len(index)) if index[i] - index[i - 1] != step]


def compare(old: pd.DataFrame, new: pd.DataFrame, step_seconds: int) -> dict:
    common = old.index.intersection(new.index)
    only_old = old.index.difference(new.index)
    only_new = new.index.difference(old.index)

    changes: list[dict] = []
    for field in FIELDS:
        if field not in old.columns or field not in new.columns:
            continue
        differs = old.loc[common, field].ne(new.loc[common, field])
        for stamp in common[differs.values]:
            before, after = old.at[stamp, field], new.at[stamp, field]
            # Text-exact comparison catches everything, but the same value
            # re-formatted ("100.1" vs "100.10") is not a revision. Flag it so a
            # formatting change is visible as one instead of inflating the count.
            try:
                same_number = float(before) == float(after)
            except ValueError:
                same_number = False
            changes.append({"bar_time_utc": str(stamp), "field": field,
                            "old": before, "new": after,
                            "numeric_equal": same_number})
    changes.sort(key=lambda row: (row["bar_time_utc"], row["field"]))

    # A revision is a change of value. Reformatting is reported separately.
    revisions = [row for row in changes if not row["numeric_equal"]]
    reformats = [row for row in changes if row["numeric_equal"]]
    per_field: dict[str, int] = {}
    for row in revisions:
        per_field[row["field"]] = per_field.get(row["field"], 0) + 1

    windows = {}
    for name, (start, end) in CERTIFIED_WINDOWS.items():
        lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        inside = [row for row in revisions if lo <= pd.Timestamp(row["bar_time_utc"]) <= hi]
        added = [str(s) for s in only_new if lo <= s <= hi]
        removed = [str(s) for s in only_old if lo <= s <= hi]
        windows[name] = {
            "range": [start, end],
            "revised_bars": len({row["bar_time_utc"] for row in inside}),
            "revised_fields": sorted({row["field"] for row in inside}),
            "bars_added": len(added), "bars_removed": len(removed),
            "clean": not inside and not added and not removed,
            "examples": inside[:10],
        }

    old_gaps, new_gaps = segments(old.index, step_seconds), segments(new.index, step_seconds)
    return {
        "bars_old": len(old), "bars_new": len(new), "bars_common": len(common),
        "bars_only_in_old": [str(s) for s in only_old[:50]],
        "bars_only_in_new": [str(s) for s in only_new[:50]],
        "bars_only_in_old_count": len(only_old),
        "bars_only_in_new_count": len(only_new),
        "changed_bars": len({row["bar_time_utc"] for row in revisions}),
        "changed_fields_total": len(revisions),
        "changes_per_field": per_field,
        "reformatted_only_fields": len(reformats),
        "price_fields_changed": sorted(
            set(per_field) & {"open", "high", "low", "close"}),
        "gaps_old": len(old_gaps), "gaps_new": len(new_gaps),
        "gaps_added": [g for g in new_gaps if g not in old_gaps],
        "gaps_removed": [g for g in old_gaps if g not in new_gaps],
        "windows": windows,
        "identical": not revisions and not len(only_old) and not len(only_new),
        "_changes": changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--step-seconds", type=int, default=900)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/validation/broker_history_provenance.json")
    parser.add_argument("--detail", type=Path,
                        default=ROOT / "reports/validation/broker_history_provenance_changes.csv")
    args = parser.parse_args()

    report = compare(load(args.old), load(args.new), args.step_seconds)
    changes = report.pop("_changes")
    report["old_file"] = {"path": str(args.old), "sha256": sha256(args.old)}
    report["new_file"] = {"path": str(args.new), "sha256": sha256(args.new)}

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str) + "\n")
    pd.DataFrame(changes, columns=["bar_time_utc", "field", "old", "new"]).to_csv(
        args.detail, index=False)

    print(f"old {report['bars_old']:,} bars   new {report['bars_new']:,} bars   "
          f"common {report['bars_common']:,}")
    print(f"only in old: {report['bars_only_in_old_count']}   "
          f"only in new: {report['bars_only_in_new_count']}")
    print(f"revised bars: {report['changed_bars']}   fields: {report['changes_per_field']}"
          f"   (reformatted only: {report['reformatted_only_fields']})")
    if report["price_fields_changed"]:
        print(f"*** PRICE FIELDS REVISED: {report['price_fields_changed']} ***")
    print(f"gaps old/new: {report['gaps_old']}/{report['gaps_new']}"
          f"   added {report['gaps_added']}   removed {report['gaps_removed']}")
    for name, stat in report["windows"].items():
        verdict = "CLEAN" if stat["clean"] else "*** AFFECTED ***"
        print(f"  {name:22} {verdict}  revised {stat['revised_bars']} "
              f"{stat['revised_fields']}  +{stat['bars_added']}/-{stat['bars_removed']}")
    print("IDENTICAL:", report["identical"])
    return 0 if report["identical"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

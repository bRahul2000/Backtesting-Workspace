"""14-day live-validation tracker: which days qualified, how many in a row, and when Stage 1 can be done.

A day qualifies only with a PASS reconciliation. A completed day without any reconciliation result is shown as
MISSED - the daily job did not run (or could not) - and breaks the run of qualifying days just like a FAIL. For 48
hours after it ends, a day that is still INCOMPLETE or unreconciled is shown as PENDING: it neither counts nor breaks
the run yet (its broker export may simply not have arrived). A day that
was reconciled after its due time is marked late, so a caught-up job is visible too.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

from .reconcile import completed_days

TARGET_DAYS = 14
PENDING_FOR = timedelta(hours=48)      # a just-finished day may wait this long for its export before it breaks a run


def load_validation(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"validation_start": None, "target_days": TARGET_DAYS}


def start_validation(path: Path, start: date) -> dict:
    config = load_validation(path)
    if config.get("validation_start"):
        raise ValueError(f"live validation already started on {config['validation_start']}")
    config = {"validation_start": start.isoformat(), "target_days": TARGET_DAYS,
              "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def _runs(results_dir: Path) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    path = results_dir / "runs.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                run = json.loads(line)
                runs.setdefault(run["date"], []).append(run)
    return runs


def summarise(results_dir: Path, validation: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    target = int(validation.get("target_days") or TARGET_DAYS)
    start = validation.get("validation_start")
    summary = {"validation_start": start, "target_days": target, "days": [], "qualifying_streak": 0,
               "longest_streak": 0, "status": "NOT STARTED", "target_completion_date": None,
               "last_reconciliation_run_utc": None, "daily_job_overdue": False}
    runs = _runs(results_dir)
    all_runs = sorted((r for rs in runs.values() for r in rs), key=lambda r: r["run_utc"])
    if all_runs:
        summary["last_reconciliation_run_utc"] = all_runs[-1]["run_utc"]
        last = datetime.fromisoformat(all_runs[-1]["run_utc"].replace("Z", "+00:00"))
        summary["daily_job_overdue"] = now - last > timedelta(hours=26)
    if not start:
        return summary
    streak = longest = 0
    for number, day in enumerate(completed_days(date.fromisoformat(start), now), start=1):
        path = results_dir / f"{day}.json"
        if path.exists():
            result = json.loads(path.read_text(encoding="utf-8"))
            status = result["status"]
            reasons = sorted({r for s in result.get("strategies", []) for r in s.get("reasons", [])} |
                             set(result.get("reasons", [])))
        else:
            status, reasons = "MISSED", ["no reconciliation result - the daily job did not run for this day"]
        late = bool(runs.get(day)) and runs[day][0].get("late", False)
        day_end = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
        if status in ("INCOMPLETE", "MISSED") and now < day_end + PENDING_FOR:
            status = "PENDING"                   # recent day still waiting for its export / run: neither counts
            summary["days"].append({"day": number, "date": day, "status": status, "late": late, "reasons": reasons})
            continue
        streak = streak + 1 if status == "PASS" else 0
        longest = max(longest, streak)
        summary["days"].append({"day": number, "date": day, "status": status, "late": late, "reasons": reasons})
    summary["qualifying_streak"], summary["longest_streak"] = streak, longest
    settled = [d for d in summary["days"] if d["status"] != "PENDING"]
    base = date.fromisoformat(settled[-1]["date"]) if settled else date.fromisoformat(start) - timedelta(days=1)
    summary["target_completion_date"] = (base + timedelta(days=max(0, target - streak))).isoformat()
    summary["status"] = "DONE" if streak >= target else "COLLECTING"
    return summary


def render(summary: dict) -> str:
    lines = ["# Telemetry V1 - live validation", ""]
    if not summary["validation_start"]:
        lines += ["Status: NOT STARTED (no live validation start date recorded yet)", ""]
    else:
        lines += [f"Validation start: {summary['validation_start']}", ""]
        for item in summary["days"]:
            flag = "  (reconciled late)" if item["late"] else ""
            why = f"  - {'; '.join(item['reasons'])}" if item["status"] != "PASS" and item["reasons"] else ""
            lines.append(f"Day {item['day']:<3} {item['date']}  {item['status']}{flag}{why}")
        lines += ["", f"Qualifying: {summary['qualifying_streak']} / {summary['target_days']} consecutive days",
                  f"Longest run: {summary['longest_streak']}",
                  f"Target completion (if every remaining day passes): {summary['target_completion_date']}",
                  f"Status: {summary['status']}", ""]
    lines.append(f"Last reconciliation run: {summary['last_reconciliation_run_utc'] or 'never'}"
                 + ("  **OVERDUE - the daily job has not run for more than 26 hours**"
                    if summary["daily_job_overdue"] else ""))
    return "\n".join(lines) + "\n"


def write_summary(results_dir: Path, summary: dict) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (results_dir / "SUMMARY.md").write_text(render(summary), encoding="utf-8")

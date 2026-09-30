"""Small read-only Telemetry V1 panel for the Diagnostics page. It opens nothing for writing (the store is opened
read-only, the spool is only tailed) and offers no controls: it is not the Algo Control Center."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import streamlit as st

from services.telemetry import paths, tracker, watchdog


def _read_only_store():
    path = paths.store_path()
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def telemetry_overview(now: datetime | None = None) -> pd.DataFrame:
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    health = watchdog.check(paths.spool_root(), now)
    rows = {w["strategy_id"] or w["writer_id"]: {
        "strategy": w["strategy_id"] or w["writer_id"], "writer": w["writer_id"], "state": w["state"],
        "last heartbeat (UTC)": w["last_heartbeat_utc"], "last event": w["last_event_type"],
        "last event (UTC)": w["last_event_utc"], "MT5 connected": w["terminal_connected"],
        "events today": None, "reconciliation": None} for w in health["writers"]}
    db = _read_only_store()
    if db is not None:
        try:
            for strategy, count in db.execute("SELECT strategy_id, COUNT(*) FROM events WHERE day=? GROUP BY strategy_id",
                                              (today,)):
                rows.setdefault(strategy, {"strategy": strategy})["events today"] = count
        finally:
            db.close()
    results = sorted(paths.reconciliation_dir().glob("????-??-??.json")) if paths.reconciliation_dir().exists() else []
    if results:
        latest = json.loads(results[-1].read_text(encoding="utf-8"))
        for item in latest.get("strategies", []):
            rows.setdefault(item["strategy"], {"strategy": item["strategy"]})["reconciliation"] = \
                f"{latest['date']} {item['status']}"
    return pd.DataFrame(list(rows.values()))


def render_telemetry_diagnostics() -> None:
    st.subheader("Live algo telemetry (V1, read-only)")
    frame = telemetry_overview()
    if frame.empty:
        st.info("No telemetry yet. Attach ZoneflowTelemetryObserver in MT5 to start collecting "
                "(services/telemetry/README.md).")
    else:
        st.dataframe(frame, hide_index=True, use_container_width=True)
    summary = tracker.summarise(paths.reconciliation_dir(), tracker.load_validation(paths.telemetry_root() / "validation.json"))
    if summary["validation_start"]:
        st.caption(f"14-day validation: {summary['qualifying_streak']} / {summary['target_days']} qualifying days "
                   f"({summary['status']}); target {summary['target_completion_date']}")
    else:
        st.caption("14-day validation: not started")
    if summary["daily_job_overdue"]:
        st.warning("The daily reconciliation has not run for more than 26 hours.")

"""Where telemetry lives.

    spool  (written by MT5, read-only for Zoneflow):  <MT5 Common Files>/Zoneflow/telemetry/spool/<writer_id>/<YYYY-MM-DD>.jsonl
    broker (daily MT5 history export by the observer): <MT5 Common Files>/Zoneflow/telemetry/broker/<account_ref>/<YYYY-MM-DD>.json
    store  (Zoneflow's own, outside Git):               $ZONEFLOW_TELEMETRY_ROOT  (default data/telemetry)
        store/telemetry.sqlite3            ingested raw events, defects, corrections, annotations (append-only)
        strategies.json                    which magic numbers / symbols belong to which strategy
        validation.json                    live-validation start date (set when collection begins)
        reconciliation/<YYYY-MM-DD>.json   one daily result (all strategies), reruns are byte-identical
        reconciliation/runs.jsonl          every reconciliation run (time, day, result hash, late or not)
        reconciliation/SUMMARY.md|json     the 14-day tracker
        watchdog/status.json, events.jsonl observer-only health
"""
from __future__ import annotations

import os
from pathlib import Path

from services.market_datasets import ROOT

TELEMETRY_ENV = "ZONEFLOW_TELEMETRY_ROOT"
SPOOL_ENV = "ZONEFLOW_TELEMETRY_SPOOL"       # override the MT5-side folder (tests, non-default installs)


def telemetry_root() -> Path:
    return Path(os.environ.get(TELEMETRY_ENV) or ROOT / "data" / "telemetry")


def mt5_telemetry_dir() -> Path:
    if os.environ.get(SPOOL_ENV):
        return Path(os.environ[SPOOL_ENV])
    from ui.tradingview_mode.component.live import common_files_dir
    return common_files_dir() / "Zoneflow" / "telemetry"


def spool_root() -> Path:
    return mt5_telemetry_dir() / "spool"


def broker_root() -> Path:
    return mt5_telemetry_dir() / "broker"


def store_path() -> Path:
    return telemetry_root() / "store" / "telemetry.sqlite3"


def reconciliation_dir() -> Path:
    return telemetry_root() / "reconciliation"


def watchdog_dir() -> Path:
    return telemetry_root() / "watchdog"

"""Zoneflow Telemetry V1 - raw, append-only facts about live algo runs, reconciled daily against MT5 broker history.

    MT5 terminal                                   Zoneflow (same machine)
    ------------                                   -----------------------
    strategy EA  --(ZoneflowTelemetry.mqh)--+      ingest.py     spool -> store (SQLite, append-only, idempotent)
    observer EA  --(OnTradeTransaction,     +-->   reconcile.py  store vs broker export -> daily result + corrections
                    heartbeat, connection)  |      tracker.py    14-day validation progress
                    daily broker export   --+      watchdog.py   stale heartbeat / MT5 connection (observe only)

The EA side stays dumb: it writes one self-checking JSON line per fact to a local spool (MT5 Common Files) and never
waits for Zoneflow. Everything interpretive (regimes, MFE/MAE, R-multiples ...) is derived later, outside this package.
Nothing here can place, modify or close an order.
"""

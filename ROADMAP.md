# Zoneflow roadmap

A stage is DONE only when its evidence exists, not when its code does. Decisions behind this order: [DECISIONS.md](DECISIONS.md).

## Stage 1 — Live Algo Telemetry

| | |
|---|---|
| Status | **Implemented — live validation not started** |
| Implementation date | 2026-09-30 |
| Live validation start | not started (recorded with `python -m services.telemetry start-validation --date YYYY-MM-DD`) |
| Qualifying days | 0 / 14 |
| Target completion | start date + 13 days, if every day passes (the tracker recomputes it daily) |

DONE only after 14 consecutive calendar days of live telemetry, each reconciled against MT5 broker history with:

- the same relevant trade/deal count
- the same entry fills and exit fills (price, volume, time, side, factual exit reason)
- no unexplained missing events, duplicates or telemetry gaps

Current progress: `C:\ZoneflowData\telemetry\reconciliation\SUMMARY.md` (and the Diagnostics page). How it works: [services/telemetry/README.md](services/telemetry/README.md).

## Stage 2 — Private Beta

Status: **not started** (login and deployment are built; the server deployment is waiting for server access and a domain).

DONE only after:

- Zoneflow is privately deployed
- Rahul uses it remotely for at least 7 days
- the top 10 actual usability and reliability issues are documented in [beta/PRIVATE_BETA_LOG.md](beta/PRIVATE_BETA_LOG.md)

## Stage 3 — Market Data Provider Validation

Status: **not started**.

DONE only after all of the following:

- at least 7 days of real provider data
- latency measured
- reliability and reconnects tested
- historical behaviour tested
- XAU compared against Exness
- cost documented
- usage and licensing terms documented
- availability for Rahul verified
- a written provider decision recorded in DECISIONS.md

## Later stages (in this order unless a decision changes it)

1. Data Layer V1
2. Research Harness
3. Algo Monitoring
4. Advanced Market Tools
5. Strategy Discovery
6. Champion/Challenger
7. Frontend migration, when actually necessary (see D013)

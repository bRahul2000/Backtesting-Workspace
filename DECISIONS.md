# Zoneflow decisions

Short, dated and permanent. A decision is changed only by a new, later entry that names the one it replaces.

| ID | Date | Decision |
|---|---|---|
| D001 | 2026-09-30 | TradingView feature parity is not the goal. Build only the charting features Zoneflow actually needs. |
| D002 | 2026-09-30 | Pine is a compatibility layer. Its expansion is frozen around the subset our actual strategies require. New research is Python-first. |
| D003 | 2026-09-30 | Zoneflow may generate and test challengers but may never silently replace a production strategy. Production changes require human approval. |
| D004 | 2026-09-30 | The market-data provider and the execution provider are separate systems. |
| D005 | 2026-09-30 | MT5/Exness remains valuable for broker fills, spread, slippage, execution and validation, but the future Zoneflow market-data system must not permanently depend on MT5. |
| D006 | 2026-09-30 | Raw data is immutable. Derived data is kept separately. |
| D007 | 2026-09-30 | Every research result identifies its code version, data snapshot and parameters. |
| D008 | 2026-09-30 | Every experiment counts, including failures. |
| D009 | 2026-09-30 | Holdout access is logged. Once outcomes influence development, that holdout is considered consumed. |
| D010 | 2026-09-30 | Live forward data is the renewable, final validation source. |
| D011 | 2026-09-30 | Telemetry stores raw facts. Regime, volatility, session, MFE, MAE, R-multiple and similar interpretations are derived later from immutable market data and timestamps. |
| D012 | 2026-09-30 | L2/order-book storage is deferred until we have a real L2 feed. |
| D013 | 2026-09-30 | Streamlit is the current UI shell, not a permanent architecture constraint. |
| D014 | 2026-09-30 | Risk controls cannot depend solely on strategy code. |
| D015 | 2026-09-30 | Production changes must remain auditable and reversible. |

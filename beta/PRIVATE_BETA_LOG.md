# Zoneflow private beta log

Stage 2 of [ROADMAP.md](../ROADMAP.md). Record only what actually happened while using Zoneflow remotely. Never write
passwords, secrets or account numbers here.

Deployment date: live at https://zoneflow.in by 2026-10-01 (exact first day to be filled in by Rahul)

Severity: **S1** blocks use · **S2** major (a workaround exists) · **S3** minor · **S4** cosmetic

## Daily use

| Day | Date | Used for (what you tried to do) | Minutes | Worked? |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |
| 6 | | | | |
| 7 | | | | |

## Issues

| # | Date | Issue (what happened, what you expected) | Severity | Workaround | Status |
|---|---|---|---|---|---|
| PB-001 | 2026-10-01 | Streamlit's top-right "RUNNING… / Stop" overlay appears again and again while simply using TradingView Mode. | S2 | none | see below |
| PB-002 | 2026-10-01 | Charts and indicators are too slow to load; indicator coverage/behaviour is inconsistent. | S2 | none | see below |
| PB-003 | 2026-10-01 | Visible whole-app flicker/rerender, most obvious at the bottom-left logged-in user / Log out control. | S3 | none | see below |
| PB-004 | 2026-10-01 | Indicators cannot be hidden or removed directly from the chart (only from another panel). | S3 | dock Indicators tab | see below |
| PB-005 | 2026-10-01 | Strategy Tester layout/UX is not good enough (dense, debug-like). | S3 | none | see below |
| PB-006 | 2026-10-01 | Strategy tests lack an obvious custom date-range workflow and a trade-list CSV export. | S2 | none | see below |

Source: two screen recordings from Rahul's deployed beta (reproducible). Resolution details, evidence and commits:
[Round 1 corrections](#round-1-corrections-pb-001-pb-006).

## TOP 10 PROBLEMS

Filled in after Day 7, from the issues above only.

| Rank | Issue # | Problem | Severity | Status |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |
| 6 | | | | |
| 7 | | | | |
| 8 | | | | |
| 9 | | | | |
| 10 | | | | |

## Round 1 corrections (PB-001 … PB-006)

Fixed in the "Private Beta round 1" commit on `feature/tradingview-mode` (2026-10-01).

Evidence comes from browser acceptance on the deployed-style shell: Streamlit 1.37.1 behind the production chain (Caddy with `deployment/Caddyfile`, the login service and proxy auth mode). The same checks were also run on Streamlit 1.64.0. The acceptance tests are in `tests/tradingview_mode/test_browser_beta_round1.py`.

**Status for all six:** resolved in code, and deployed-style acceptance passed. They go live on zoneflow.in after the VPS update (`deployment/windows/Update-Zoneflow.ps1`).

| # | Root cause | Fix | Acceptance evidence |
|---|---|---|---|
| PB-001 | In Live mode the terminal sends `live_poll` once a second. Each event re-ran the whole Streamlit app, so Streamlit showed "Running… / Stop" every second. Idle Historical mode caused no reruns. | The terminal now runs in an `st.fragment`, so an event reruns only the terminal. The login is re-checked on every terminal run. The page CSS never shows Streamlit's status widget over the terminal. | Live, idle 60 s: full-app reruns went from 60 to **0**. The status widget appeared 61 times before and **0** after; it is not even created for a fragment run. Historical, idle 60 s: 0 runs of anything. |
| PB-002 | Every event re-sent the entire payload: 0.2–0.6 MB normally and 4–6 MB with 20k bars. That included a tab change (429 KB) and each live poll (342 KB with a Pine strategy on the chart). Indicators were hard-coded, VWAP ran on tick volume without saying so, and hidden indicators were not computed. | Large arrays now travel once, as content-addressed files that the browser keeps. Only small state is sent per event. WebSocket compression is on in production. A generic indicator engine was added (see [capability matrix](../docs/INDICATOR_CAPABILITY_MATRIX.json)): 13 indicators, every listed one working or honestly limited. | Tab change: 429 KB → about 41 KB. EMA on 20k bars: 4.9 MB → 43 KB. Live poll with a strategy: about 342 KB → about 33 KB per second. All 13 indicators draw on BTC, Gold and synthetic data (tested). |
| PB-003 | Same cause as PB-001. Each full-app rerun rebuilt the sidebar and the account control and dimmed the page while it ran. | The fragment rerun, plus CSS that never dims the terminal. | 60 s Live and 60 s Historical: the account control was replaced 0 times and hidden 0 times, the sidebar moved 0 times, the terminal iframe was recreated 0 times and it was dimmed 0 times. |
| PB-004 | The only indicator controls were in the dock's Indicators table. | The chart legend (overlays) and each pane header now have eye, gear and X controls. Hide and show act immediately and keep the instance. Remove gives the pane space back. The gear opens a typed settings editor. | Real-click test: EMA, RSI, MACD and Bollinger Bands placed correctly; each hidden and shown; EMA 20→50 changed from the gear; RSI removed with its pane reclaimed; the chart rectangle stayed the same throughout (90/90 checks). |
| PB-005 | The tester was dense and debug-like: one metric grid and no header. | New header (strategy, symbol, timeframe, status, test range, Export), with Overview (metric cards plus equity and drawdown), Performance (grouped), List of Trades (sortable) and Properties. | Gold Range Hunter: tabs keep the chart rectangle and the test range; sorting by P&L works; selecting a row highlights it and navigates the chart. |
| PB-006 | A Pine strategy always ran over the whole history up to the chart's last visible bar, so the test was tied to the chart window. There was no range control and no Pine CSV. | Per-strategy test range (Full / Custom UTC from–to) that changes what is evaluated. It is independent of the chart window. Export Trades CSV produces raw values with a deterministic filename. | Custom range 2026-01-01 → 2026-03-31: the trade count changed (155 → 93) and every trade lies in range. The downloaded CSV was parsed and matches the tester's data field by field. |

### Before / after timings (Streamlit 1.37.1, through Caddy and login, local machine)

- **Time (ms):** from the event to "idle and painted".
- **Sent:** WebSocket bytes before compression, plus data-file bytes fetched (gzip over Caddy).
- **Local machine:** a click completes in about 100 ms either way. The size column is what makes the difference on zoneflow.in.

| Action | Before: ms / sent | After: ms / sent |
|---|---|---|
| TradingView Mode initial load (cold) | 4,344 / full payload | 4,089 / small payload plus files |
| BTC 15m load | 256 / 324 KB | 261 / 38 KB + 67 KB of files (once) |
| XAU 15m load | 167 / 245 KB | 158 / 38 KB + 48 KB of files (once) |
| BTC → XAU switch (warm) | 116 / 245 KB | 116 / 39 KB |
| Timeframe 15m → 1h | 117 / 183 KB | 116 / 39 KB + 35 KB of files |
| EMA add | 116 / 337 KB | 116 / 40 KB + 25 KB |
| RSI add | 116 / 429 KB | 117 / 41 KB + 27 KB |
| Dock tab change | 116 / 429 KB | 116 / 41 KB |
| 20k-bar range (BTC 15m) | 333 / 3.97 MB | 466 / 42 KB + 1.0 MB (once) |
| EMA add on 20k bars | 383 / 4.9 MB | 416 / 43 KB |
| RSI add on 20k bars | 449 / 5.85 MB | 467 / 44 KB |
| Gold Range Hunter add (strategy calculation) | 8,831 / 1.92 MB (full history to 2026-09) | 5,350 / 25 KB + 109 KB (test range to 2026-06-02, 10,355 bars) |
| Tester tab change (strategy on the chart) | 266 / 1.92 MB | 216–249 / 25 KB + 10 KB |
| Live: each poll | 60 full-app reruns/min · 342 KB each | 0 full-app reruns · about 33 KB each |

**Remaining bottlenecks:**

- **Pine engine calculation:** Gold Range Hunter takes about 5–9 s for 10–17k bars. This is not changed in this round.
- **First load of long ranges:** loading a long range (20k bars, 1 MB of files) costs time once.
- **Streamlit start-up:** about 4 s cold.
- **Server CPU:** the zoneflow.in server's CPU was not measured. There was no server access from here, so it remains unknown whether the server is slower than this Mac.

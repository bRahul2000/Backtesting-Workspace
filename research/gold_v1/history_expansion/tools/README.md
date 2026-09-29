# Load_XAUUSD_History — history-only MT5 helper

This one-off script asks the MT5 terminal to download and build older **XAUUSDm M15 and H1** history from the
Exness server. Exporting stays with the **unchanged** `mt5/Export_XAUUSD_History` and `mt5/Export_XAUUSD_Spec`.
Nothing in `mt5/` is modified.

| file | SHA-256 |
|---|---|
| `Load_XAUUSD_History.mq5` | `4f91f5c1ef1723a9443740e66437e7541a910e4cb874a2a74f02d79d7e510d07` |
| `Load_XAUUSD_History.ex5` (compiled here, 0 errors / 0 warnings, `compile.log`) | `9e3da862281ab80cde6280d946286d6f90407e9fe599369f1531cba3918a85ac` |

## How it works (documented MQL5 behaviour)

- **Download trigger.** In a script, a `Copy*` request for bars the terminal does not hold starts a download from the
  server, or a rebuild of the timeseries. The call may return partial data, or −1, after an internal wait while the
  download continues. Later calls return more. This is the pattern of MetaQuotes' "Organizing Data Access" /
  `CheckLoadHistory` example.
- **The loop.** Each round the loader:
  1. calls `CopyTime(symbol, tf, Bars(symbol, tf), 2000, …)`, which asks for the 2,000 bars *older* than the oldest
     local bar;
  2. sleeps 0.5 s;
  3. re-reads `SERIES_FIRSTDATE`.
- **Stop conditions.** It stops with one of these reasons:
  - `TARGET_REACHED`: the first bar is at or before `InpTargetDate` (default 2020-01-01).
  - `SERVER_FIRST_DATE_REACHED`: the first bar is at or before `SERIES_SERVER_FIRSTDATE`, the oldest date the Exness
    server holds for the symbol. It is read before loading and logged.
  - `NO_OLDER_DATA`: the first date has not moved for 40 consecutive rounds (about 20 s).
  - `MAX_BARS_LIMIT`: `Bars()` reached `TERMINAL_MAXBARS` (see below).
  - `TIMEOUT`: 30 minutes for the whole run. Running the script again resumes where it stopped.
- **Timeframes.** M15 and H1 are loaded separately, because each timeseries is built and capped on its own. Both are
  built by the terminal from its 1-minute base history, which it downloads automatically. No explicit M1 request is
  needed.
- **Output.** The results go to the Experts tab and to `xauusd_history_loader_status.json` in MT5 Common Files. For
  each timeframe the status file gives: first bar, last completed bar, bar count, `SERIES_SYNCHRONIZED`,
  target reached, stop reason, rounds and last error.

## Max bars in chart matters

- **Timeseries cap.** `Bars()`, and therefore `CopyRates` and the exporter, never exceeds `TERMINAL_MAXBARS`. This is
  confirmed on this machine: the BTCUSDm M15 export stopped at about 100k bars, which is this terminal's setting
  (`config/common.ini`, `[Charts] MaxBars=100000`). Programmatic retrieval does **not** bypass it.
- **What 100,000 bars reaches for gold** (about 23,900 M15 bars a year): back to about **mid-2022**. That is enough
  for the proposed 2023-01-01 replication period plus warm-up, but not for 2020. The loader prints a warning and stops
  at `MAX_BARS_LIMIT` if the cap is hit.
- **The setting was not changed automatically.** `common.ini` is a UTF-16 file that the terminal rewrites on exit.
  The on-disk encoding of "Unlimited" is not documented, so editing it by hand is not clearly safe. The one GUI change
  is: **Tools → Options → Charts → Max bars in chart → Unlimited → OK, then restart MT5.**

## Steps for Rahul

The Mac terminal (Wine, `Exness-MT5Trial5`) is recommended. Claude can then read the results from Common Files
directly, with no file transfer.

1. **Install the three scripts**, with MT5 closed. From the repository root:

   ```
   S="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/Program Files/MetaTrader 5/MQL5/Scripts"
   cp research/gold_v1/history_expansion/tools/Load_XAUUSD_History.ex5 "$S/"
   cp mt5/Export_XAUUSD_History.mq5 mt5/Export_XAUUSD_Spec.mq5 "$S/"
   ```

   The exporters are copied **unchanged**. They were never installed on this Mac terminal.
2. **Compile the two exporters.** This uses the same command-line build that compiled the loader, with MT5 closed:

   ```
   export WINEPREFIX="$HOME/Library/Application Support/net.metaquotes.wine.metatrader5"
   W="/Applications/MetaTrader 5.app/Contents/SharedSupport/wine/bin/wine64"
   for f in Export_XAUUSD_History Export_XAUUSD_Spec; do
     "$W" "C:\\Program Files\\MetaTrader 5\\MetaEditor64.exe" /compile:"C:\\Program Files\\MetaTrader 5\\MQL5\\Scripts\\$f.mq5" /log
   done
   ```

   Alternatively, open each file in MetaEditor and press F7.
3. **Open MT5** and log in to the Exness-MT5Trial5 account. Set **Max bars in chart = Unlimited**, then restart MT5.
4. **Run the loader.** Open any XAUUSDm chart. In Navigator → Scripts (right-click → Refresh if needed), drag
   **Load_XAUUSD_History** onto the chart, keep the default inputs and click OK. Wait for the two final `M15:` / `H1:`
   lines in the Experts tab, which takes at most 30 minutes. If a line says `TIMEOUT`, run the loader once more.
   **No scrolling is needed.**
5. **Export.** Drag **Export_XAUUSD_History** onto the chart, then **Export_XAUUSD_Spec**, both with default inputs.
6. **Tell Claude it is done.** The files are then read from Common Files, never written from Python, and copied with
   hashes into `research/gold_v1/history_expansion/raw/`. The Phase 2A export is never overwritten.

**Windows terminal instead.** Use File → Open Data Folder → `MQL5\Scripts`, and copy the `.ex5` there, or the `.mq5`
and compile it with F7. Steps 3–5 are the same. Then send the Common Files exports and the status JSON.

## Safety audit

- **No trading capability.** There are no `#include` lines at all, so no Trade classes (`CTrade` and similar). There
  is no `OrderSend`/`OrderSendAsync`/`OrderCheck`, no position, order, deal or history-selection functions, no
  `WebRequest`/sockets/mail/FTP/notifications, and no DLL imports. This was checked by a keyword scan and by reading
  the source.
- **Read-only broker access.** The only broker traffic is the normal history download that `Bars`, `CopyTime` and
  `SeriesInfoInteger` start. The only account call is `AccountInfoString(ACCOUNT_SERVER)`, which reads the server
  name for provenance, as the existing exporter does. It reads no login, password or balance.
- **Limited writes.** It writes one file, `xauusd_history_loader_status.json`, into MT5 Common Files, from inside MT5.
  It does not touch chart settings, terminal configuration or symbol properties.
- **Bounded runtime.** Every loop has a stall limit and a 30-minute limit, and it honours `IsStopped()`.
- **Compile side effects.** The test compile ran MetaEditor under Wine while MT5 was closed. It changed only Wine's
  own prefix files (registry and printer-driver cache) and `logs/metaeditor.log`. Nothing in `MQL5/`, `config/`,
  `Bases/` or Common Files changed.

## If Exness stops at December 2025

If the status file reports `server_first_date` around 2025-12 (with `SERVER_FIRST_DATE_REACHED` or `NO_OLDER_DATA`),
the limit is **broker-side** for XAUUSDm on this server. The loader cannot go further. Options, each needing
approval:

- another Exness server or account type (e.g. a real server) that keeps deeper XAUUSDm history, proven identical on
  the overlap with Phase 2A;
- a different gold feed, which is not comparable by default and would need a feed-comparison study first. It must
  never be mixed silently;
- stopping Gold V1, the fallback recorded in the consolidated review.

The loader cannot tell whether the server really lacks older data or merely refuses a request. `NO_OLDER_DATA` well
after the server first date would point to a terminal or request problem and should be reported before anything else
is tried.

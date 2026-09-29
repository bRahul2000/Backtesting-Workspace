# Deployment record — 2026-09-29

Target: the Mac MT5 (Wine) terminal on Exness-MT5Trial5, `…/drive_c/Program Files/MetaTrader 5/MQL5/Scripts/`.
MT5 was closed throughout.

| installed file | SHA-256 | source |
|---|---|---|
| `Load_XAUUSD_History.mq5` | `4f91f5c1…d510d07` | `history_expansion/tools/` |
| `Load_XAUUSD_History.ex5` | `9e3da862…18a85ac` | compiled here, 0 errors / 0 warnings |
| `Export_XAUUSD_History.mq5` | `3379862f…5cd3c` | `mt5/`, byte-identical to HEAD |
| `Export_XAUUSD_History.ex5` | `e01bbc32…ac282` | compiled from a byte-identical copy of `mt5/Export_XAUUSD_History.mq5`, 0 errors / 0 warnings |

## Build notes

- **Space-free path needed.** MetaEditor's command-line `/compile:` ignores source paths that contain spaces under
  Wine (e.g. `Application Support`, `Program Files`): nothing is compiled and no log is written. So the exporter was
  compiled from a byte-identical copy in a space-free scratch folder, and the `.ex5` was installed.
- **`timeout` is not available on macOS.** Compiles were watchdogged with a background process and a 90 s limit.

## `mt5/Export_XAUUSD_Spec.mq5` does not compile as committed — NOT deployed

```
Export_XAUUSD_Spec.mq5(20,19) : error 256: undeclared identifier 'DAY_SUNDAY'
Export_XAUUSD_Spec.mq5(20,38) : error 256: undeclared identifier 'DAY_SATURDAY'
Result: 2 errors, 0 warnings
```

- **Cause.** MQL5's `ENUM_DAY_OF_WEEK` constants are `SUNDAY` … `SATURDAY`, with no `DAY_` prefix. The committed
  file (from commit 78c3dc7) cannot have produced Phase 2A's `xauusd_mt5_spec.json` unchanged. That run presumably
  used a locally edited copy on the Windows terminal.
- **Not fixed.** `mt5/` is protected, so the file was not modified. The copy placed in Scripts was removed.
- **Not needed for history loading.** A spec export is only a *current* snapshot, since MT5 keeps no spec history,
  and one was captured on 2026-09-19 (Phase 2A).
- **The minimal fix, if approved:** replace `DAY_SUNDAY` / `DAY_SATURDAY` with `SUNDAY` / `SATURDAY` on line 20.

## Invariants verified after deployment

- `mt5/` is identical to HEAD; the tracked tree is identical to HEAD (`d56f304`), which includes the Pine P1–P3.1
  code; the Pine tags are unchanged.
- H1–H5 (67 files) and the H3 preregistration (`c481f8a1…`) are unchanged.
- The Phase 2A raw and processed files, which contain the sealed Validation/OOS rows, are unchanged.
- The experiment ledger is unchanged (`bcc4b4d1dc844d93`).
- MT5 `common.ini` still has `MaxBars=100000`. It was not edited.

# Loader v2 — deep history (2026-09-29)

The only change from v1 is the default `InpTargetDate`: from `2020.01.01` to `2014.01.14`, the Exness server's first
date. v1 is archived unchanged in `archive_v1/` (source `4f91f5c1…`, binary `9e3da862…`).

| file | SHA-256 |
|---|---|
| `Load_XAUUSD_History.mq5` v2 | `7697a43953625bb6bd8ef65f37eec56409e7d43f7153f03680c4170ce014cc0e` |
| `Load_XAUUSD_History.ex5` v2, compiled 0 errors / 0 warnings | `971e1953575565a2ce4c54b97db1db70602969afd23337f73458f0e97c227f5d` |

- **Safety scan:** no Trade includes, no order/position/deal/history-selection functions, no web or socket calls, no
  DLLs.
- **Installed** into the Mac MT5 `MQL5/Scripts` with MT5 closed. `Export_XAUUSD_History` is unchanged (`e01bbc32…`).
- **MaxBars** is still `100000000` (Unlimited); it was not edited.
- **Next exports** go to `history_expansion/raw_full/`. The 2019–2026 snapshot in `raw/` remains the preserved
  evidence copy.

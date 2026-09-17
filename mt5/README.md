# BTC Setup A V1 for MT5

**Status: EA SOURCE GENERATED. It has not yet been compiled in MetaEditor or compared with MT5 Strategy Tester results. It is not live approved.** The research strategy is frozen. This EA contains Setup A only, fixed 3R, no Setup B or volatility gate.

The default mode is `AUDIT_ONLY`: the EA writes an audit CSV and **never sends an order**. `DEMO_TRADE` sends orders only when MT5 reports a demo account. There is no live mode. The default Magic Number is `515010220`; check that your Gold EA uses a different number.

## 1. Copy and compile

1. Open MT5. In MT5, click **File → Open Data Folder**.
2. Open `MQL5`, then `Experts`. Copy [BTC_Setup_A_V1.mq5](BTC_Setup_A_V1.mq5) into `Experts`. Leave the original project copy intact.
3. Return to MT5 and press **F4** to open MetaEditor. In MetaEditor's Navigator, open `Experts → BTC_Setup_A_V1.mq5`.
4. Press **F7** to compile. Read the bottom **Errors** tab. The required result is **0 errors**. If it reports errors, copy the exact error messages and line numbers back into this project. Do not change frozen strategy values to silence errors.
5. Return to MT5. In Navigator, right-click **Expert Advisors** and select **Refresh**. Find `BTC_Setup_A_V1`.

## 2. Verify audit mode

1. Open the Exness **BTCUSDm** chart and set timeframe **M15**.
2. Attach the EA to that chart. Leave `InpMode = AUDIT_ONLY` and `InpMagicNumber = 515010220` unless that number conflicts with another EA.
3. Look in MT5's **Experts** tab for `BTC Setup A V1`, the full freeze hash, symbol/spec checks, and warm-up count. A wrong symbol, timeframe, broker specification, or UTC offset must prevent startup.
4. Confirm **no broker orders** appear. Audit mode records theoretical quote-side events only while the terminal receives ticks; it cannot reproduce historical ticks merely by being attached to a chart.
5. To find the CSV, use **File → Open Data Folder → MQL5 → Files → BTC_Setup_A_V1_Audit.csv**. The journal also prints event messages.

## 3. Run two historical Strategy Tester checks

1. In MT5 press **Ctrl+R** to open **Strategy Tester**.
2. Select Expert Advisor `BTC_Setup_A_V1`, symbol **BTCUSDm**, timeframe **M15**.
3. Select **Every tick based on real ticks** if available. Record if the tester says real tick data is unavailable or incomplete.
4. Set the first dates to **2026-01-01 through 2026-03-31**. Choose `AUDIT_ONLY`, then click **Start**.
5. When done, open the Strategy Tester **Journal** and inspect errors. Find `BTC_Setup_A_V1_Audit.csv` in the tester agent's `MQL5/Files` folder. In the tester, use **File → Open Data Folder**, then locate `Tester/Agent-.../MQL5/Files`; MT5 agent folder names vary. Copy the CSV back to this project as, for example, `mt5/exports/test_a_2026q1.csv`.
6. Repeat with **2025-01-01 through 2025-03-31** and save `mt5/exports/test_b_2025q1.csv`. Use separate export filenames. The two periods must not be mixed into a single comparison file.
7. If testing actual broker order behavior, use `DEMO_TRADE` **only on a demo account**, then repeat the exports. Audit mode and demo mode produce different execution evidence.

The EA checks an Exness UTC+0 server clock, because the project’s validated Exness M15 dataset is UTC+0. If the clock check fails, do not override it; record the displayed offset.

## 4. Compare with frozen Python

From `/Users/apple/Documents/Backtesting`, run:

```bash
venv/bin/python tools/compare_mt5_setup_a.py --mt5-export mt5/exports/test_a_2026q1.csv --start 2026-01-01 --end 2026-03-31 --output mt5/exports/compare_a.json
venv/bin/python tools/compare_mt5_setup_a.py --mt5-export mt5/exports/test_b_2025q1.csv --start 2025-01-01 --end 2025-03-31 --output mt5/exports/compare_b.json
```

The comparator reloads the frozen configuration, recomputes Python Setup A on the existing Exness M15 dataset, and lists all signal, direction, price, fill, exit, and outcome differences. The default price tolerance is **USD 0.01**, one BTCUSDm point. Signal timestamp and direction require exact matches. Python used M15 OHLC execution conventions, while MT5 may use real Bid/Ask ticks, so inspect mismatches rather than changing tolerances to hide them. A price or fill difference does not automatically mean an entry rule is wrong.

Before sharing exports, check whether MT5 included account identifiers. Keep the exports local. The source CSV contains `signal_time` at the **close** of the qualifying M15 candle and `signal_candle_time` at its open. All CSV clock values are UTC only if the EA startup UTC check passed.

## Files and operational notes

- [PARITY_RULE_MAP.md](PARITY_RULE_MAP.md): each frozen rule and its MQL5 equivalent.
- [VALIDATION_CHECKLIST.md](VALIDATION_CHECKLIST.md): steps that must pass before any demo forward validation claim.
- The EA isolates its own state with **symbol plus Magic Number**. It does not manage Gold orders. Its research balance tracks only its own deals, beginning from the frozen $10,000 research starting balance; MT5 may reject a demo order for actual account margin.
- A pending stop uses a broker expiration after B+2. A gap cancels its pending order and resets indicators. A filled position is never closed because of a strategy permission lock or data gap.
- Demo mode persists day/month reference equity in MT5 terminal global variables and reads own broker history on restart. Audit-only paper state is session-local.
- Initial pending TP is calculated from the planned trigger and then adjusted to 3R from the actual broker fill. Inspect every modification event. A short interval can exist between fill and adjustment; this must be evaluated in tester before demo use.

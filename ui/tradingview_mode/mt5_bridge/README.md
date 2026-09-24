# TradingView Mode Live feed (read-only MT5 bridge)

`TradingViewLiveFeed.mq5` is an MQL5 **Service**. It is not an Expert Advisor and
is not attached to a chart. It only reads market data (`SymbolInfoTick`,
`SymbolInfo*`, `CopyRates`, `TerminalInfoInteger`, `Time*`) and writes it to
MetaTrader's **Common\Files** folder. It contains no trading call, and
`tests/tradingview_mode/test_live.py` fails if one is ever added. Python only
reads the files. This is the same file bridge the Stage 3 tooling uses
(`scripts/stage3`). It is separate from `mt5/`, and the Stage 3/4/5 EAs are not
touched or enabled.

## Files it writes (every ~500 ms)

| File | Content |
|---|---|
| `tv_live_<SYMBOL>_quote.json` | writer id, sequence, heartbeat (GMT), server and GMT clock, connection flag, digits, point, broker spread in points, last tick (ms time, bid, ask), last 3 M15/M30/H1 bars |
| `tv_live_<SYMBOL>_<M15|M30|H1>_seed.csv` | the last 500 broker bars, rewritten when a new bar opens |

Every file is written to a `.tmp` file first and then moved into place, so
Python never reads a half-written file.

## Install (once)

1. In MetaTrader 5, logged into Exness, choose **File → Open Data Folder**, then
   open `MQL5/Services`.
2. Copy `TradingViewLiveFeed.mq5` there.
3. Press **F4** (MetaEditor), open the file and press **F7**. Check for **0 errors**.
4. In the MT5 **Navigator**, right-click **Services**, choose **Refresh**, then
   right-click **TradingViewLiveFeed** and choose **Add service**. Keep
   `InpSymbols = BTCUSDm,XAUUSDm` and start it.
5. Check the **Experts/Journal** tab for `TradingView Live Feed started (read-only)`.
6. In the project, run `./venv/bin/python -m streamlit run app.py`, open
   TradingView Mode, click **Live** (the strip above the chart shows the Live controls),
   pick a symbol and timeframe, and click **Go Live**.

Python reads
`~/Library/Application Support/net.metaquotes.wine.metatrader5/drive_c/users/user/AppData/Roaming/MetaQuotes/Terminal/Common/Files`.
Set `TV_MT5_COMMON_FILES` to use another folder.

## States shown in the terminal

| State | Meaning |
|---|---|
| LIVE | The service is writing (heartbeat ≤ 5 s), the terminal is connected, the server clock is UTC+0, bar history is present, and the last tick is ≤ 60 s old. |
| STALE | The heartbeat is 5–60 s old, or there has been no tick for over 60 s (market closed or feed paused). |
| CONNECTING | MetaTrader is running but not connected to the broker, or there is no bar history yet. |
| DISCONNECTED | No feed file, or the heartbeat is more than 60 s old (MetaTrader or the service stopped). |
| ERROR | The file is unreadable, the symbol doesn't match, bars are misaligned, duplicated or insane, ask is below bid, the server clock is not UTC+0, or the heartbeat is in the future. |

No other data source is ever substituted.

## Synthetic feed (tests / UI checks without MetaTrader)

```bash
./venv/bin/python tests/tradingview_mode/synthetic_mt5_feed.py /tmp/mt5files --seconds 600
TV_MT5_COMMON_FILES=/tmp/mt5files ./venv/bin/python -m streamlit run app.py
```

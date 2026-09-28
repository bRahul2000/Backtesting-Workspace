# TradingView Mode terminal

This is a React + Lightweight Charts (v5) terminal served as a Streamlit custom
component. Python stays authoritative for data, timeframes, indicators and
(later) strategy results. See [CONTRACT.md](CONTRACT.md).

## Running it

TradingView Mode always renders this terminal; there is no renderer toggle.
If the build is missing or cannot be served, the page shows an `st.error`.

```bash
./venv/bin/python -m streamlit run app.py
```

## Build (macOS)

```bash
cd ui/tradingview_mode/component/frontend
npm install
npm run build     # writes dist/, which Python serves
```

Restart Streamlit after the first build, because the component is registered
at import. `vite.config.js` must keep `base: "./"`. Streamlit serves the
component under `/component/<name>/`, and absolute `/assets/...` URLs load
Streamlit's own HTML instead of the bundle. `component.build_problems()` checks
for this and a test enforces it.

## Layout

```
frontend/src/
  main.jsx               Streamlit connection, error boundary, global error reporting
  App.jsx                terminal grid, iframe height fitting, status bar
  events.js              explicit events, serialized by Python's `ack`
  chart/ChartEngine.js   Lightweight Charts wrapper; diffs by revision, keeps zoom
  components/            TopBar, LeftToolbar, ChartPanel (+legend), Watchlist, BottomPanel
```

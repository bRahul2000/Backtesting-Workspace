import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Streamlit } from "streamlit-component-lib";
import { acknowledge, onPendingChange, sendEvent } from "./events.js";
import { formatUtc } from "./format.js";
import { BottomPanel } from "./components/BottomPanel.jsx";
import { ChartPanel } from "./components/ChartPanel.jsx";
import { LeftToolbar } from "./components/LeftToolbar.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { Watchlist } from "./components/Watchlist.jsx";

const MIN_HEIGHT = 560;
const MAX_HEIGHT = 1200;

// Fit the iframe to the visible Streamlit viewport when the parent is reachable
// (same origin); otherwise keep the Python-provided height.
function useFrameHeight(fallback) {
  const [height, setHeight] = useState(fallback);
  useEffect(() => {
    let parentWindow = null;
    const measure = () => {
      try {
        const frame = window.frameElement;
        parentWindow = window.parent;
        const top = frame.getBoundingClientRect().top;
        if (top < 0) return; // parent scrolled; keep current height
        setHeight(Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, parentWindow.innerHeight - top - 12))));
      } catch {
        setHeight(fallback);
      }
    };
    measure();
    try { window.parent.addEventListener("resize", measure); } catch { /* cross-origin */ }
    return () => { try { parentWindow?.removeEventListener("resize", measure); } catch { /* ignore */ } };
  }, [fallback]);
  useEffect(() => { Streamlit.setFrameHeight(height); });
  return height;
}

export function clientLog(level, message) {
  window.dispatchEvent(new CustomEvent("tvterm:log", { detail: { level, message } }));
}

function StatusBar({ payload, crosshairTime }) {
  return (
    <footer className="statusbar">
      <span className="mono">{formatUtc(crosshairTime ?? payload.bars.at(-1)?.time)} UTC</span>
      <span className="sep" />
      <span>{payload.bars.length.toLocaleString()} bars</span>
      <span className="sep" />
      <span>{payload.source.dataset_key} · {payload.source.description}</span>
      <div className="spacer" />
      <span className="muted">Python-authoritative · contract v{payload.contract}</span>
      <span className="sep" />
      <a href="https://www.tradingview.com/lightweight-charts/" target="_blank" rel="noreferrer" className="muted">
        Charts: Lightweight Charts™
      </a>
    </footer>
  );
}

const DAY = 86400;
const isoDate = (epochSeconds) => new Date(epochSeconds * 1000).toISOString().slice(0, 10);
const clampDate = (value, min, max) => (min && value < min ? min : max && value > max ? max : value);

// Chart window around a trade, keeping roughly the current zoom (span in days).
function windowAround(trade, spanDays, min, max) {
  const half = Math.max(2, Math.ceil(spanDays / 2));
  return {
    start: clampDate(isoDate(trade.entry_time - half * DAY), min, max),
    end: clampDate(isoDate(trade.exit_time + half * DAY), min, max),
  };
}

// Trade selection / chart focus. Purely client-side: it never asks Python to
// rerun a backtest; at most it requests chart bars around the trade.
function useTradeFocus(payload, engine) {
  const run = payload.tester.run;
  const overlay = payload.trade_overlay;
  const [selectedTradeId, setSelectedTradeId] = useState(null);
  const [pendingFocus, setPendingFocus] = useState(null);
  const [note, setNote] = useState(null);
  const tradesById = useMemo(() => new Map((run?.trades || []).map((t) => [t.trade_id, t])), [run]);
  const overlayById = useMemo(() => new Map(overlay.trades.map((o) => [o.trade_id, o])), [overlay]);

  useEffect(() => { setSelectedTradeId(null); setPendingFocus(null); setNote(null); }, [run?.run_id]);
  useEffect(() => {
    if (pendingFocus === null) return;
    const placed = overlayById.get(pendingFocus);
    if (placed && engine?.focusBars(placed.entry_bar, placed.exit_bar)) {
      setPendingFocus(null);
      setNote(null);
    }
  }, [overlayById, pendingFocus, engine]);

  const spanDays = payload.range.start
    ? (Date.parse(payload.range.end) - Date.parse(payload.range.start)) / 86400000 + 1 : 30;

  const showOnBacktestDataset = useCallback((trade) => {
    const tested = payload.tester.options.datasets.find((d) => d.dataset_key === run.dataset.dataset_key);
    sendEvent("select_dataset", { dataset_key: run.dataset.dataset_key });
    sendEvent("set_date_range", windowAround(trade, Math.min(spanDays, 30), tested?.min, tested?.max));
    setPendingFocus(trade.trade_id);
    setNote(`Switching chart to ${run.dataset.label} around trade #${trade.trade_id}…`);
  }, [payload.tester.options.datasets, run, spanDays]);

  const selectTrade = useCallback((trade) => {
    setSelectedTradeId(trade.trade_id);
    const placed = overlayById.get(trade.trade_id);
    if (placed) {
      engine?.focusBars(placed.entry_bar, placed.exit_bar);
      setPendingFocus(null);
      setNote(null);
      return;
    }
    if (!overlay.available) {
      setPendingFocus(null);
      setNote(
        <>
          {overlay.reason} Markers are only drawn on the tested market data.{" "}
          <button type="button" className="link-btn" onClick={() => showOnBacktestDataset(trade)}>
            Show trade #{trade.trade_id} on {run.dataset.symbol} · {run.dataset.timeframe}
          </button>
        </>,
      );
      return;
    }
    sendEvent("set_date_range", windowAround(trade, spanDays, payload.range.min, payload.range.max));
    setPendingFocus(trade.trade_id);
    setNote(`Loading chart bars around trade #${trade.trade_id}…`);
  }, [overlayById, overlay, engine, spanDays, payload.range.min, payload.range.max, run, showOnBacktestDataset]);

  return { selectedTradeId, selectTrade, tradesById, note };
}

function Terminal({ payload, fallbackHeight }) {
  const height = useFrameHeight(fallbackHeight);
  const [engine, setEngine] = useState(null);
  const [pending, setPending] = useState(null);
  const [crosshairMode, setCrosshairModeState] = useState("normal");
  const [crosshairTime, setCrosshairTime] = useState(null);
  const [clientLogs, setClientLogs] = useState([]);

  useEffect(() => onPendingChange(setPending), []);
  // Python echoes the id of the last event it processed.
  useEffect(() => { if (payload.ack) acknowledge(payload.ack); }, [payload.ack, payload]);
  useEffect(() => { sendEvent("chart_ready"); }, []);
  useEffect(() => {
    const onLog = (event) => setClientLogs((prev) => [...prev.slice(-99), {
      ...event.detail, time: new Date().toISOString().slice(11, 19),
    }]);
    window.addEventListener("tvterm:log", onLog);
    return () => window.removeEventListener("tvterm:log", onLog);
  }, []);

  const setCrosshairMode = useCallback((mode) => {
    setCrosshairModeState(mode);
    engine?.setCrosshairMode(mode);
  }, [engine]);
  const focus = useTradeFocus(payload, engine);
  const engineActions = useMemo(() => ({
    fit: () => engine?.fit(),
    latest: () => engine?.goToLatest(),
    resetScale: () => engine?.resetPriceScale(),
  }), [engine]);

  return (
    <div className="terminal" style={{ height }}>
      <TopBar payload={payload} pending={pending} crosshairMode={crosshairMode}
        setCrosshairMode={setCrosshairMode} engineActions={engineActions} />
      <LeftToolbar crosshairMode={crosshairMode} setCrosshairMode={setCrosshairMode}
        engineActions={engineActions} drawingsEnabled={payload.capabilities.drawings} />
      <ChartPanel payload={payload} onEngine={setEngine} onCrosshairTime={setCrosshairTime}
        tradesById={focus.tradesById} selectedTradeId={focus.selectedTradeId} />
      <Watchlist items={payload.watchlist} />
      <BottomPanel payload={payload} clientLogs={clientLogs} pending={pending}
        selectedTradeId={focus.selectedTradeId} onSelectTrade={focus.selectTrade} focusNote={focus.note} />
      <StatusBar payload={payload} crosshairTime={crosshairTime} />
    </div>
  );
}

export default function App({ args }) {
  const payload = args?.payload;
  if (!payload) {
    return <div className="boot">Waiting for the Python payload…</div>;
  }
  if (payload.contract !== 1) {
    return <div className="fatal"><b>Unsupported contract version {String(payload.contract)}.</b> Rebuild the frontend.</div>;
  }
  return <Terminal payload={payload} fallbackHeight={760} />;
}

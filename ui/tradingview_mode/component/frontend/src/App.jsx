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
      <ChartPanel payload={payload} onEngine={setEngine} onCrosshairTime={setCrosshairTime} />
      <Watchlist items={payload.watchlist} />
      <BottomPanel payload={payload} clientLogs={clientLogs} />
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

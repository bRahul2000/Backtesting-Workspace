import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Streamlit } from "streamlit-component-lib";
import { acknowledge, isIdle, onPendingChange, sendEvent } from "./events.js";
import { intervalMs, tickAction } from "./replayControls.js";
import { POLL_MS, pollAction } from "./liveControls.js";
import { formatUtc } from "./format.js";
import { Icon } from "./components/icons.jsx";
import { BottomPanel } from "./components/BottomPanel.jsx";
import { ChartPanel } from "./components/ChartPanel.jsx";
import { LeftToolbar } from "./components/LeftToolbar.jsx";
import { TopBar } from "./components/TopBar.jsx";
import { Watchlist } from "./components/Watchlist.jsx";

const MIN_HEIGHT = 560;
const MAX_HEIGHT = 4000;
const BOTTOM_EDGE = 6;       // px left between the terminal and the browser's bottom edge (page.py uses the same)

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
        setHeight(Math.round(Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, parentWindow.innerHeight - top - BOTTOM_EDGE))));
      } catch {
        setHeight(fallback);
      }
    };
    measure();
    // the page's own styles may settle after the first measurement
    const timers = [300, 1000, 2500].map((ms) => setTimeout(measure, ms));
    try { window.parent.addEventListener("resize", measure); } catch { /* cross-origin */ }
    return () => {
      timers.forEach(clearTimeout);
      try { parentWindow?.removeEventListener("resize", measure); } catch { /* ignore */ }
    };
  }, [fallback]);
  useEffect(() => { Streamlit.setFrameHeight(height); });
  return height;
}

export function clientLog(level, message) {
  window.dispatchEvent(new CustomEvent("tvterm:log", { detail: { level, message } }));
}

function historyNote(live) {
  if (live.more_history) return "More history available (scroll left)";
  if (live.bar_count >= live.history_limit) return `History limit ${live.history_limit.toLocaleString()} bars`;
  return live.source === "binance" ? "Start of Binance history" : "All bars the MT5 bridge provides";
}

function StatusBar({ payload, crosshairTime }) {
  return (
    <footer className="statusbar">
      <span className="mono">{formatUtc(crosshairTime ?? payload.bars.at(-1)?.time)} UTC</span>
      <span className="sep" />
      {payload.live?.phase === "streaming" ? (
        <span className="history-status">
          {payload.bars.length.toLocaleString()} bars · {payload.live.source_label} · {payload.live.timeframe}
          <span className="muted"> · {historyNote(payload.live)}</span>
        </span>
      ) : <span>{payload.bars.length.toLocaleString()} bars</span>}
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

// Trade selection / chart focus, by the trade's unique key (trade_id repeats
// across data segments). Purely client-side: it never asks Python to rerun a
// backtest; at most it requests chart bars around the trade.
function useTradeFocus(payload, engine) {
  const run = payload.tester.run;
  const overlay = payload.trade_overlay;
  const [selectedKey, setSelectedKey] = useState(null);
  const [pendingFocus, setPendingFocus] = useState(null);
  const [note, setNote] = useState(null);
  const tradesByKey = useMemo(() => new Map((run?.trades || []).map((t) => [t.key, t])), [run]);
  const overlayByKey = useMemo(() => new Map(overlay.trades.map((o) => [o.key, o])), [overlay]);
  const label = (t) => (t.segment ? `${t.segment}/${t.trade_id}` : `#${t.trade_id}`);

  useEffect(() => { setSelectedKey(null); setPendingFocus(null); setNote(null); }, [run?.run_id, run?.history_id]);
  useEffect(() => {
    if (selectedKey !== null && !tradesByKey.has(selectedKey)) setSelectedKey(null);
  }, [tradesByKey, selectedKey]);
  useEffect(() => {
    if (pendingFocus === null) return;
    const placed = overlayByKey.get(pendingFocus);
    if (placed && engine?.focusBars(placed.entry_bar, placed.exit_bar)) {
      setPendingFocus(null);
      setNote(null);
    }
  }, [overlayByKey, pendingFocus, engine]);

  const spanDays = payload.range.start
    ? (Date.parse(payload.range.end) - Date.parse(payload.range.start)) / 86400000 + 1 : 30;

  const showOnBacktestDataset = useCallback((trade) => {
    const tested = payload.tester.options.datasets.find((d) => d.dataset_key === run.dataset.dataset_key);
    sendEvent("select_dataset", { dataset_key: run.dataset.dataset_key });
    sendEvent("set_date_range", windowAround(trade, Math.min(spanDays, 30), tested?.min, tested?.max));
    setPendingFocus(trade.key);
    setNote(`Switching chart to ${run.dataset.label} around trade ${label(trade)}…`);
  }, [payload.tester.options.datasets, run, spanDays]);

  const selectTrade = useCallback((trade) => {
    setSelectedKey(trade.key);
    const placed = overlayByKey.get(trade.key);
    if (placed) {
      engine?.focusBars(placed.entry_bar, placed.exit_bar);
      setPendingFocus(null);
      setNote(null);
      return;
    }
    if (payload.replay?.enabled) {
      // Never move a replay chart to (or reveal) a trade after the cursor.
      setPendingFocus(null);
      setNote(`Trade ${label(trade)} is not drawn in Replay: markers appear only for trades that closed by the replay cursor.`);
      return;
    }
    if (!overlay.available) {
      setPendingFocus(null);
      setNote(
        <>
          {overlay.reason} Markers are only drawn on the tested market data.{" "}
          <button type="button" className="link-btn" onClick={() => showOnBacktestDataset(trade)}>
            Show trade {label(trade)} on {run.dataset.symbol} · {run.dataset.timeframe}
          </button>
        </>,
      );
      return;
    }
    sendEvent("set_date_range", windowAround(trade, spanDays, payload.range.min, payload.range.max));
    setPendingFocus(trade.key);
    setNote(`Loading chart bars around trade ${label(trade)}…`);
  }, [overlayByKey, overlay, engine, spanDays, payload.range.min, payload.range.max, run, showOnBacktestDataset, payload.replay?.enabled]);

  return { selectedKey, selectTrade, tradesByKey, note };
}

// Pine Strategy Tester rows: select a trade, highlight its fills and entry/exit prices, and bring it into view. A
// trade on bars older than the loaded window loads them first: the date range's START moves back and its END is
// kept, so the Pine calculation range (first available bar -> chart end) and therefore every trade stay identical.
function usePineTradeFocus(payload, engine) {
  const [selectedKey, setSelectedKey] = useState(null);
  const [pendingTrade, setPendingTrade] = useState(null);
  const [note, setNote] = useState(null);
  const show = useCallback((trade) => {
    if (!engine || engine.findIndex(trade.entry_time) < 0) return false;
    engine.selectPineTrade(trade);
    const lastTime = engine.bars.length ? engine.bars[engine.bars.length - 1].time : trade.entry_time;
    return engine.focusBars(trade.entry_time, trade.open || trade.exit_time === null ? lastTime : trade.exit_time);
  }, [engine]);
  useEffect(() => {
    if (!pendingTrade) return;
    if (show(pendingTrade)) { setPendingTrade(null); setNote(null); }
  }, [payload.bars_rev, pendingTrade, show]);
  const select = useCallback((trade) => {
    setSelectedKey(trade.key);
    if (show(trade)) { setPendingTrade(null); setNote(null); return; }
    if (payload.replay?.enabled || payload.live?.enabled) {
      setNote(`Trade #${trade.number} is not on the loaded bars.`);
      return;
    }
    const day = (seconds) => new Date(seconds * 1000).toISOString().slice(0, 10);
    const start = day(trade.entry_time - 2 * 86400);
    const end = payload.range.end;
    sendEvent("set_date_range", { start: payload.range.min && start < payload.range.min ? payload.range.min : start, end });
    setPendingTrade(trade);
    setNote(`Loading older bars for trade #${trade.number}…`);
  }, [show, payload.replay?.enabled, payload.live?.enabled, payload.range.end, payload.range.min]);
  // The chart may be rebuilt (new view): re-apply the highlight.
  useEffect(() => { if (!selectedKey && engine) engine.selectPineTrade(null); }, [selectedKey, engine]);
  // A new symbol / timeframe: no trade of the previous one stays selected
  useEffect(() => { setSelectedKey(null); setPendingTrade(null); setNote(null); }, [payload.view_key]);
  return { selectedKey, select, note };
}

// Replay playback: a local timer asks Python for one more bar per tick, but only
// when no event is in flight, so steps can never pile up behind a slow rerun.
function useReplayPlayback(replay) {
  const latest = useRef(replay);
  latest.current = replay;
  const enabled = !!replay?.enabled;
  const playing = enabled && replay.playing && !replay.at_end;
  const speed = replay?.speed;
  useEffect(() => {
    if (!playing) return undefined;
    const timer = setInterval(() => {
      if (tickAction(latest.current, isIdle()) === "step") sendEvent("step_forward");
    }, intervalMs(speed));
    return () => clearInterval(timer);
  }, [playing, speed]);
}

// Live: ask Python to re-read the MT5 feed about once a second, never while an
// event is still in flight.
function useLivePolling(live) {
  const latest = useRef(live);
  latest.current = live;
  const enabled = !!live?.enabled && live.phase === "streaming";
  useEffect(() => {
    if (!enabled) return undefined;
    const timer = setInterval(() => {
      if (pollAction(latest.current, isIdle()) === "poll") sendEvent("live_poll");
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [enabled]);
}

// Python-generated exports arrive once in the payload; download each id once.
function useExportDownload(exportFile) {
  const seen = useRef(new Set());
  useEffect(() => {
    if (!exportFile || seen.current.has(exportFile.id)) return;
    seen.current.add(exportFile.id);
    const url = URL.createObjectURL(new Blob([exportFile.content], { type: exportFile.mime }));
    const link = document.createElement("a");
    link.href = url;
    link.download = exportFile.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    clientLog("info", `Downloaded ${exportFile.filename}`);
  }, [exportFile]);
}

// ---- layout (TradingView style: the chart dominates) ------------------------------------------------------------
// Preferences persist in this browser (localStorage). Modes: normal · chart (chart only: no toolbar, watchlist, dock,
// nor Streamlit's page sidebar) · tester (chart + Strategy Tester) · editor (chart + Pine Editor).
const LAYOUT_KEY = "tvterm:layout";
const LAYOUT_DEFAULT = { tools: true, watch: true, watchWidth: 240, mode: "normal" };

function useLayout() {
  const [layout, setLayout] = useState(() => {
    try { return { ...LAYOUT_DEFAULT, ...JSON.parse(window.localStorage.getItem(LAYOUT_KEY) || "{}") }; } catch { return LAYOUT_DEFAULT; }
  });
  useEffect(() => { try { window.localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout)); } catch { /* unavailable */ } }, [layout]);
  // Chart only also hides Streamlit's page sidebar: a rule in the parent page keyed to this iframe's attribute
  // (it cannot outlive the terminal: without the iframe the selector no longer matches).
  useEffect(() => {
    try {
      const frame = window.frameElement;
      if (!frame) return;
      frame.dataset.tvLayout = layout.mode;
      const doc = window.parent.document;
      if (!doc.getElementById("tvterm-layout-style")) {
        const style = doc.createElement("style");
        style.id = "tvterm-layout-style";
        style.textContent = 'body:has(iframe[data-tv-layout="chart"]) [data-testid="stSidebar"] { display: none !important; }';
        doc.head.appendChild(style);
      }
    } catch { /* cross-origin parent: only the terminal's own panels change */ }
  }, [layout.mode]);
  const update = useCallback((patch) => setLayout((prev) => ({ ...prev, ...patch })), []);
  const setMode = useCallback((mode) => {
    update({ mode });
    if (mode === "tester") sendEvent("set_bottom_panel", { panel: "strategy_tester", open: true });
    if (mode === "editor") sendEvent("set_bottom_panel", { panel: "pine", open: true });
  }, [update]);
  const normal = layout.mode === "normal";
  return { layout, update, setMode, showTools: normal && layout.tools, showWatch: normal && layout.watch,
    showDock: layout.mode !== "chart" };
}

// Drag the watchlist's left edge to resize it (160-440 px).
function WatchResize({ width, onWidth }) {
  const drag = useRef(null);
  return (
    <div className="watch-resize" title="Drag to resize the watchlist"
      onPointerDown={(e) => { drag.current = { x: e.clientX, width }; e.currentTarget.setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (drag.current) onWidth(Math.round(Math.min(440, Math.max(160, drag.current.width + drag.current.x - e.clientX)))); }}
      onPointerUp={() => { drag.current = null; }} />
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
  const layoutApi = useLayout();
  const { layout, showTools, showWatch, showDock } = layoutApi;
  const focus = useTradeFocus(payload, engine);
  const pineFocus = usePineTradeFocus(payload, engine);
  useExportDownload(payload.tester.export);
  useReplayPlayback(payload.replay);
  useLivePolling(payload.live);
  const engineActions = useMemo(() => ({
    fit: () => engine?.fit(),
    latest: () => engine?.goToLatest(),
    resetScale: () => engine?.resetPriceScale(),
  }), [engine]);

  return (
    <div className={`terminal layout-${layout.mode}`} style={{ height,
      gridTemplateColumns: `${showTools ? 40 : layout.mode === "normal" ? 14 : 0}px minmax(0, 1fr) ${showWatch ? layout.watchWidth : layout.mode === "normal" ? 14 : 0}px` }}>
      <TopBar payload={payload} pending={pending} crosshairMode={crosshairMode}
        setCrosshairMode={setCrosshairMode} engineActions={engineActions} layoutApi={layoutApi} />
      {showTools ? (
        <LeftToolbar crosshairMode={crosshairMode} setCrosshairMode={setCrosshairMode}
          engineActions={engineActions} drawingsEnabled={payload.capabilities.drawings} onCollapse={() => layoutApi.update({ tools: false })} />
      ) : layout.mode === "normal" && (
        <button type="button" className="rail left-rail" title="Show chart tools" onClick={() => layoutApi.update({ tools: true })}>
          <Icon name="chevronRight" size={12} /></button>
      )}
      <ChartPanel payload={payload} onEngine={setEngine} onCrosshairTime={setCrosshairTime}
        tradesByKey={focus.tradesByKey} selectedKey={focus.selectedKey} busy={!!pending} />
      {showWatch ? (
        <div className="watch-wrap">
          <WatchResize width={layout.watchWidth} onWidth={(w) => layoutApi.update({ watchWidth: w })} />
          <Watchlist items={payload.watchlist} replay={!!payload.replay?.enabled} live={payload.live?.phase === "streaming"}
            timeframe={payload.timeframe} onCollapse={() => layoutApi.update({ watch: false })} />
        </div>
      ) : layout.mode === "normal" && (
        <button type="button" className="rail right-rail" title="Show watchlist" onClick={() => layoutApi.update({ watch: true })}>
          <Icon name="chevronLeft" size={12} /></button>
      )}
      {showDock && <BottomPanel payload={payload} clientLogs={clientLogs} pending={pending}
        selectedKey={focus.selectedKey} onSelectTrade={focus.selectTrade} focusNote={focus.note} pineFocus={pineFocus} />}
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

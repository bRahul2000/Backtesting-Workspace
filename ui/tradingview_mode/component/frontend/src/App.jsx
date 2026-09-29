import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Streamlit } from "streamlit-component-lib";
import { acknowledge, isIdle, onPendingChange, sendEvent } from "./events.js";
import { intervalMs, tickAction } from "./replayControls.js";
import { POLL_MS, pollAction } from "./liveControls.js";
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
  useExportDownload(payload.tester.export);
  useReplayPlayback(payload.replay);
  useLivePolling(payload.live);
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
        tradesByKey={focus.tradesByKey} selectedKey={focus.selectedKey} busy={!!pending} />
      <Watchlist items={payload.watchlist} replay={!!payload.replay?.enabled} live={payload.live?.phase === "streaming"} timeframe={payload.timeframe} />
      <BottomPanel payload={payload} clientLogs={clientLogs} pending={pending}
        selectedKey={focus.selectedKey} onSelectTrade={focus.selectTrade} focusNote={focus.note}
        onFocusBars={(entryTime, exitTime) => !!engine?.focusBars(entryTime, exitTime)} />
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

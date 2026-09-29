import React, { useEffect, useRef, useState } from "react";
import { sendEvent } from "../events.js";
import { Icon } from "./icons.jsx";
import { StrategyTester } from "./tester/StrategyTester.jsx";
import { TradesWorkspace } from "./tester/TradesTable.jsx";
import { PineEditor } from "./PineEditor.jsx";
import { PineTester, PineTradesTable, pineStrategies } from "./tester/PineTester.jsx";

// ONE dock height for every tab: changing tabs only swaps the content inside the same rectangle (the chart never
// moves). The height changes only when the user drags the dock's top edge; it and the collapsed state persist in this
// browser (localStorage; storage may be unavailable in private windows).
const DEFAULT_HEIGHT = 280;
const HEIGHT_STORAGE = "tvterm:dock-height";
const OPEN_STORAGE = "tvterm:dock-open";

function storedHeight() {
  try { return Number(window.localStorage.getItem(HEIGHT_STORAGE)) || DEFAULT_HEIGHT; } catch { return DEFAULT_HEIGHT; }
}

function storedOpen() {
  try { const v = window.localStorage.getItem(OPEN_STORAGE); return v === null ? null : v === "1"; } catch { return null; }
}

const TABS = [
  ["indicators", "Indicators"],
  ["strategy_tester", "Strategy Tester"],
  ["trades", "Trades"],
  ["pine", "Pine Editor"],
  ["logs", "Logs"],
];

function ParamInput({ indicator, name, value, revision }) {
  const [draft, setDraft] = useState(String(value));
  // Re-sync on every Python payload so a rejected edit reverts to Python's value.
  useEffect(() => setDraft(String(value)), [value, revision]);
  const commit = () => {
    const number = Number(draft);
    if (draft.trim() === "" || !Number.isFinite(number)) { setDraft(String(value)); return; }
    if (number !== value) sendEvent("update_indicator", { id: indicator.id, params: { [name]: number } });
  };
  return (
    <label className="param">
      <span>{name}</span>
      <input className="mono" value={draft} inputMode="decimal" onChange={(e) => setDraft(e.target.value)}
        onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setDraft(String(value)); }} />
    </label>
  );
}

function IndicatorsTab({ indicators, revision }) {
  if (!indicators.length) {
    return <div className="empty">No indicators. Use <b>Indicators</b> in the top bar to add one — values are calculated in Python.</div>;
  }
  return (
    <table className="grid-table">
      <thead><tr><th /><th>Indicator</th><th>ID</th><th>Pane</th><th>Parameters</th><th /></tr></thead>
      <tbody>
        {indicators.map((item) => (
          <tr key={item.id} className={item.enabled ? "" : "is-muted"}>
            <td><span className="swatch" style={{ background: item.color }} /></td>
            <td>{item.name}</td>
            <td className="mono muted">{item.id}</td>
            <td className="muted">{item.pane === "overlay" ? "Price" : "Lower"}</td>
            <td className="params">
              {Object.entries(item.params).length
                ? Object.entries(item.params).map(([name, value]) => <ParamInput key={name} indicator={item} name={name} value={value} revision={revision} />)
                : <span className="muted">—</span>}
            </td>
            <td className="row-actions">
              <button type="button" className="icon-btn" title={item.enabled ? "Hide" : "Show"}
                onClick={() => sendEvent("toggle_indicator", { id: item.id, enabled: !item.enabled })}>
                <Icon name={item.enabled ? "eye" : "eyeOff"} size={15} />
              </button>
              <button type="button" className="icon-btn danger" title="Remove"
                onClick={() => sendEvent("remove_indicator", { id: item.id })}><Icon name="close" size={15} /></button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LogsTab({ logs, clientLogs }) {
  const [showDebug, setShowDebug] = useState(false);
  const merged = [
    ...logs.map((entry) => ({ ...entry, origin: "py" })),
    ...clientLogs.map((entry) => ({ ...entry, origin: "ui" })),
  ].filter((entry) => showDebug || entry.level !== "debug").reverse();
  return (
    <div className="logs">
      <label className="check small"><input type="checkbox" checked={showDebug} onChange={(e) => setShowDebug(e.target.checked)} /><span>debug</span></label>
      {merged.length === 0 && <div className="empty">No log entries.</div>}
      {merged.map((entry, index) => (
        <div key={index} className={`log-row level-${entry.level}`}>
          <span className="mono muted">{entry.time}</span>
          <span className="log-origin">{entry.origin}</span>
          <span className="log-level">{entry.level}</span>
          <span className="log-msg">{entry.message}</span>
        </div>
      ))}
    </div>
  );
}

// Drag the top edge to resize; one height, remembered in this browser.
function useResizableHeight() {
  const [height, setHeight] = useState(storedHeight);
  const drag = useRef(null);
  const onPointerDown = (event) => {
    drag.current = { y: event.clientY, height };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event) => {
    if (!drag.current) return;
    const next = Math.round(Math.min(620, Math.max(120, drag.current.height + drag.current.y - event.clientY)));
    setHeight(next);
  };
  const onPointerUp = () => {
    if (!drag.current) return;
    drag.current = null;
    try { window.localStorage.setItem(HEIGHT_STORAGE, String(height)); } catch { /* ignore */ }
  };
  return { height, handlers: { onPointerDown, onPointerMove, onPointerUp } };
}

// The Strategy Tester shows ONE engine's results at a time, never combined: "pine" (the Pine strategy on the chart,
// TradingView emulator) or "python" (an explicitly run audited backtest). Pine is the default when the chart has a
// Pine strategy; running an audited backtest switches to it; a newly added Pine strategy switches back.
function useTesterSource(payload, pending) {
  const strategies = pineStrategies(payload.pine);
  const [source, setSource] = useState(() => (strategies.length ? "pine" : "python"));
  const [strategyId, setStrategyId] = useState(null);
  const lastIds = useRef(strategies.map((s) => s.id).join(","));
  const lastRun = useRef(payload.tester.run?.run_id ?? null);
  useEffect(() => {
    const ids = strategies.map((s) => s.id);
    const before = lastIds.current ? lastIds.current.split(",") : [];
    const added = ids.filter((id) => !before.includes(id));
    if (added.length) { setSource("pine"); setStrategyId(added[added.length - 1]); }
    else if (!ids.length && source === "pine" && payload.tester.run) setSource("python");
    lastIds.current = ids.join(",");
  }, [strategies.map((s) => s.id).join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const runId = payload.tester.run?.run_id ?? null;
    if (runId && runId !== lastRun.current) setSource("python");
    lastRun.current = runId;
  }, [payload.tester.run?.run_id]);
  useEffect(() => { if (pending?.type === "run_backtest") setSource("python"); }, [pending?.type]);
  return { source, setSource, strategyId, setStrategyId, strategies };
}

function SourceSwitch({ source, setSource, hasPine, hasPython }) {
  return (
    <div className="tester-source">
      <span className={`source-badge ${source}`}>{source === "pine" ? "Pine · TradingView Emulator" : "Python Audited Engine"}</span>
      <div className="segmented small" role="group" aria-label="Strategy Tester source">
        <button type="button" className={source === "pine" ? "is-active" : ""} onClick={() => setSource("pine")}
          title={hasPine ? "The Pine strategy on the chart (simulated broker emulator)" : "No Pine strategy on the chart"}>Pine</button>
        <button type="button" className={source === "python" ? "is-active" : ""} onClick={() => setSource("python")}
          title={hasPython ? "The last audited backtest run" : "Run an audited backtest (frozen validated datasets)"}>Python</button>
      </div>
      <span className="muted small-text">One engine at a time · results are never combined</span>
    </div>
  );
}

export function BottomPanel({ payload, clientLogs, pending, selectedKey, onSelectTrade, focusNote, pineFocus }) {
  // Optimistic echo of the Python-owned panel state; Python's value wins on the next payload.
  const [tab, setTab] = useState(payload.ui.bottom_panel);
  const [open, setOpen] = useState(payload.ui.bottom_open);
  useEffect(() => { setTab(payload.ui.bottom_panel); setOpen(payload.ui.bottom_open); }, [payload.ui.bottom_panel, payload.ui.bottom_open]);
  const { height, handlers } = useResizableHeight();
  // collapsed / open persists across reloads: restore the stored state once, then remember every change
  const restored = useRef(false);
  useEffect(() => {
    if (!restored.current) {
      restored.current = true;
      const stored = storedOpen();
      if (stored !== null && stored !== payload.ui.bottom_open) {
        setOpen(stored);
        sendEvent("set_bottom_panel", { panel: payload.ui.bottom_panel, open: stored });
        return;
      }
    }
    try { window.localStorage.setItem(OPEN_STORAGE, payload.ui.bottom_open ? "1" : "0"); } catch { /* ignore */ }
  }, [payload.ui.bottom_open]); // eslint-disable-line react-hooks/exhaustive-deps
  const tester = useTesterSource(payload, pending);
  const hasPine = tester.strategies.length > 0;
  const pineScript = tester.strategies.find((s) => s.id === tester.strategyId) || tester.strategies[0];
  const errorCount = payload.logs.filter((entry) => entry.level === "error").length + clientLogs.filter((e) => e.level === "error").length;

  const select = (next, nextOpen = true) => {
    setTab(next);
    setOpen(nextOpen);
    sendEvent("set_bottom_panel", { panel: next, open: nextOpen });
  };

  return (
    <section className={`bottom ${open ? "is-open" : "is-collapsed"}`} style={open ? { height } : undefined}>
      {open && <div className="bottom-resize" title="Drag to resize" {...handlers} />}
      <div className="bottom-tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={open && tab === key}
            className={`bottom-tab ${open && tab === key ? "is-active" : ""}`}
            onClick={() => select(key, !(open && tab === key))}>
            {label}
            {key === "indicators" && payload.indicators.length > 0 && <span className="count">{payload.indicators.length}</span>}
            {key === "logs" && errorCount > 0 && <span className="count error">{errorCount}</span>}
            {key === "strategy_tester" && pending?.type === "run_backtest" && <span className="spinner" />}
            {key === "strategy_tester" && <span className={`source-dot ${tester.source}`} title={tester.source === "pine" ? "Pine · TradingView Emulator" : "Python Audited Engine"} />}
            {key === "trades" && tester.source === "python" && payload.tester.run && <span className="count">{payload.tester.run.trades.length}</span>}
            {key === "trades" && tester.source === "pine" && pineScript?.strategy && <span className="count">{pineScript.strategy.trades.length}</span>}
            {key === "pine" && payload.pine?.scripts.length > 0 && <span className="count">{payload.pine.scripts.length}</span>}
          </button>
        ))}
        <div className="spacer" />
        <button type="button" className="icon-btn" title={open ? "Collapse panel" : "Expand panel"} onClick={() => select(tab, !open)}>
          <Icon name={open ? "expand" : "collapse"} size={15} />
        </button>
      </div>
      {open && (
        <div className="bottom-body">
          {tab === "indicators" && <IndicatorsTab indicators={payload.indicators} revision={payload.ack} />}
          {tab === "strategy_tester" && (
            <div className="tester unified-tester">
              <SourceSwitch source={tester.source} setSource={tester.setSource} hasPine={hasPine} hasPython={!!payload.tester.run} />
              {tester.source === "pine"
                ? <PineTester pine={payload.pine} precision={payload.price_precision ?? 2} strategyId={tester.strategyId}
                    onStrategy={tester.setStrategyId} selectedKey={pineFocus.selectedKey} onSelectTrade={pineFocus.select}
                    note={pineFocus.note} />
                : <StrategyTester payload={payload} pending={pending} selectedKey={selectedKey}
                    onSelectTrade={onSelectTrade} focusNote={focusNote} />}
            </div>
          )}
          {tab === "trades" && (
            <div className="trades-tab">
              <SourceSwitch source={tester.source} setSource={tester.setSource} hasPine={hasPine} hasPython={!!payload.tester.run} />
              {tester.source === "pine" ? (
                <>
                  {pineFocus.note && <div className="tester-note">{pineFocus.note}</div>}
                  {pineScript?.strategy
                    ? <PineTradesTable report={pineScript.strategy} precision={payload.price_precision ?? 2}
                        selectedKey={pineFocus.selectedKey} onSelect={pineFocus.select} />
                    : <div className="empty">No Pine strategy trades.</div>}
                </>
              ) : (
                <>
                  {focusNote && <div className="tester-note">{focusNote}</div>}
                  <TradesWorkspace run={payload.tester.run} precision={payload.tester.run?.price_precision ?? payload.price_precision}
                    selectedKey={selectedKey} onSelect={onSelectTrade} />
                </>
              )}
            </div>
          )}
          {tab === "pine" && <PineEditor pine={payload.pine} pending={pending} />}
          {tab === "logs" && <LogsTab logs={payload.logs} clientLogs={clientLogs} />}
        </div>
      )}
    </section>
  );
}

import React, { useEffect, useState } from "react";
import { sendEvent } from "../events.js";
import { Icon } from "./icons.jsx";

const TABS = [
  ["indicators", "Indicators"],
  ["strategy_tester", "Strategy Tester"],
  ["trades", "Trades"],
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

function StrategyTab() {
  return (
    <div className="empty">
      <b>Strategy Tester</b> is not connected in this phase. When it is, the Python backtester computes every
      result (entries, stops, targets, metrics) and this panel only renders them.
    </div>
  );
}

function TradesTab({ trades }) {
  return (
    <table className="grid-table">
      <thead><tr><th>#</th><th>Side</th><th>Entry (UTC)</th><th>Entry</th><th>Exit (UTC)</th><th>Exit</th><th>P&amp;L</th></tr></thead>
      <tbody>
        {trades.length === 0 && <tr><td colSpan={7} className="empty-cell">No trades. Trade results will come from the Python execution engine.</td></tr>}
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

export function BottomPanel({ payload, clientLogs }) {
  // Optimistic echo of the Python-owned panel state; Python's value wins on the next payload.
  const [tab, setTab] = useState(payload.ui.bottom_panel);
  const [open, setOpen] = useState(payload.ui.bottom_open);
  useEffect(() => { setTab(payload.ui.bottom_panel); setOpen(payload.ui.bottom_open); }, [payload.ui.bottom_panel, payload.ui.bottom_open]);
  const errorCount = payload.logs.filter((entry) => entry.level === "error").length + clientLogs.filter((e) => e.level === "error").length;

  const select = (next, nextOpen = true) => {
    setTab(next);
    setOpen(nextOpen);
    sendEvent("set_bottom_panel", { panel: next, open: nextOpen });
  };

  return (
    <section className={`bottom ${open ? "is-open" : "is-collapsed"}`}>
      <div className="bottom-tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={open && tab === key}
            className={`bottom-tab ${open && tab === key ? "is-active" : ""}`}
            onClick={() => select(key, !(open && tab === key))}>
            {label}
            {key === "indicators" && payload.indicators.length > 0 && <span className="count">{payload.indicators.length}</span>}
            {key === "logs" && errorCount > 0 && <span className="count error">{errorCount}</span>}
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
          {tab === "strategy_tester" && <StrategyTab />}
          {tab === "trades" && <TradesTab trades={payload.trades} />}
          {tab === "logs" && <LogsTab logs={payload.logs} clientLogs={clientLogs} />}
        </div>
      )}
    </section>
  );
}

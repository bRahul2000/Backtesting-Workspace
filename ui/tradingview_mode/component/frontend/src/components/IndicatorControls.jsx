import React, { useEffect, useState } from "react";
import { sendEvent } from "../events.js";
import { Icon } from "./icons.jsx";

// One parameter, typed by the indicator's own spec (int / float / choice) from payload.indicator_catalog.
export function ParamField({ spec, value, onChange, live = false }) {
  const [draft, setDraft] = useState(String(value));
  useEffect(() => setDraft(String(value)), [value]);
  if (spec.kind === "choice") {
    return (
      <label className="param">
        <span>{spec.label}</span>
        <select aria-label={spec.label} value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {spec.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </select>
      </label>
    );
  }
  const commit = () => {
    const number = Number(draft);
    if (draft.trim() === "" || !Number.isFinite(number)) { setDraft(String(value)); return; }
    if (number !== value) onChange(number);
  };
  return (
    <label className="param">
      <span>{spec.label}</span>
      <input className="mono" aria-label={spec.label} value={draft} inputMode="decimal" step={spec.step ?? undefined}
        onChange={(e) => {
          setDraft(e.target.value);
          const number = Number(e.target.value);          // in an editor with Apply: track valid typing at once
          if (live && e.target.value.trim() !== "" && Number.isFinite(number)) onChange(number);
        }} onBlur={commit}
        onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); if (e.key === "Escape") setDraft(String(value)); }} />
    </label>
  );
}

// The settings editor of one active indicator instance: edits are collected and applied together (Python validates).
export function IndicatorSettings({ item, catalog, onClose }) {
  const spec = catalog.find((entry) => entry.key === item.key);
  const [draft, setDraft] = useState(item.params);
  useEffect(() => setDraft(item.params), [item.params]);
  if (!spec) return null;
  const changed = Object.keys(draft).some((name) => draft[name] !== item.params[name]);
  return (
    <div className="ind-settings" role="dialog" aria-label={`${spec.name} settings`}
      onMouseDown={(e) => e.stopPropagation()}>
      <div className="ind-settings-head"><b>{spec.name}</b><span className="muted">{spec.description}</span></div>
      {spec.params.length ? spec.params.map((param) => (
        <ParamField key={param.name} spec={param} value={draft[param.name]} live
          onChange={(value) => setDraft((prev) => ({ ...prev, [param.name]: value }))} />
      )) : <div className="muted">No parameters.</div>}
      <div className="ind-settings-foot">
        <button type="button" className="btn ghost small" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary small" disabled={!changed}
          onClick={() => { sendEvent("update_indicator", { id: item.id, params: draft }); onClose(); }}>Apply</button>
      </div>
    </div>
  );
}

// Eye / gear / X on a chart legend row (overlay) or pane header. Hide and remove act on the chart immediately and are
// then persisted by Python; nothing is recalculated to hide or show.
export function IndicatorControls({ item, engine, catalog }) {
  const [editing, setEditing] = useState(false);
  const label = item.label || item.name;
  const toggle = () => {
    const visible = item.visible === false;
    engine?.setIndicatorVisible(item.id, visible);
    sendEvent("toggle_indicator", { id: item.id, enabled: visible });
  };
  const remove = () => {
    engine?.markRemoving(item.id);
    sendEvent("remove_indicator", { id: item.id });
  };
  return (
    <span className="lg-controls">
      <button type="button" className="lg-btn" aria-label={`${item.visible === false ? "Show" : "Hide"} ${label}`}
        title={item.visible === false ? "Show" : "Hide"} onClick={toggle}>
        <Icon name={item.visible === false ? "eyeOff" : "eye"} size={14} />
      </button>
      <button type="button" className="lg-btn" aria-label={`Settings ${label}`} title="Settings"
        onClick={() => setEditing((open) => !open)}><Icon name="gear" size={14} /></button>
      <button type="button" className="lg-btn danger" aria-label={`Remove ${label}`} title="Remove" onClick={remove}>
        <Icon name="close" size={14} /></button>
      {editing && <IndicatorSettings item={item} catalog={catalog} onClose={() => setEditing(false)} />}
    </span>
  );
}

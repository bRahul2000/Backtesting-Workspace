import React, { useEffect, useMemo, useRef, useState } from "react";
import { sendEvent } from "../events.js";

// Pine Editor. Python compiles and runs every script (language-driven engine);
// this panel only edits text, sends it, and shows what Python reports.
const DRAFT_KEY = "tvterm:pine:draft";

function loadDraft(fallback) {
  try { return window.localStorage.getItem(DRAFT_KEY) ?? fallback; } catch { return fallback; }
}

function saveDraft(text) {
  try { window.localStorage.setItem(DRAFT_KEY, text); } catch { /* storage unavailable */ }
}

function Diagnostics({ result, stale, onJump }) {
  if (!result) return <div className="pine-empty">Compile to check the script. Problems are listed here with their line.</div>;
  const problems = result.diagnostics;
  return (
    <div className="pine-problems">
      {stale && <div className="pine-stale">Edited since the last compile — press Compile again.</div>}
      {result.ok && <div className="pine-ok">✓ Compiled: <b>{result.meta.title}</b>{result.meta.overlay ? " · overlay" : " · own pane"}
        {result.inputs.length > 0 && ` · ${result.inputs.length} input${result.inputs.length > 1 ? "s" : ""}`}</div>}
      {problems.map((d, i) => (
        <button key={`${d.line}-${i}`} type="button" className={`pine-diag is-${d.kind}`} onClick={() => onJump(d.line)}
          title={d.feature ? `Missing language feature: ${d.feature}` : undefined}>
          <span className="pine-diag-kind">{d.kind === "gap" ? "NOT YET SUPPORTED" : d.kind.toUpperCase()}</span>
          <span className="mono">Line {d.line}</span>
          <span className="pine-diag-text">{d.message}</span>
        </button>
      ))}
      {result.report.features.length > 0 && (
        <div className="pine-features" title="Language features this script uses">
          {result.report.features.map((f) => (
            <span key={f.feature} className={`pine-chip is-${f.status}`} title={`${f.description} (${f.status})`}>{f.feature}</span>
          ))}
        </div>
      )}
    </div>
  );
}

function InputField({ script, input }) {
  const [draft, setDraft] = useState(String(input.value ?? ""));
  useEffect(() => setDraft(String(input.value ?? "")), [input.value]);
  const send = (value) => sendEvent("pine_set_input", { id: script.id, index: input.index, value });
  if (input.kind === "bool") {
    return <label className="pine-input"><span>{input.title}</span>
      <input type="checkbox" checked={!!input.value} onChange={(e) => send(e.target.checked)} /></label>;
  }
  if (input.options || input.kind === "source") {
    const options = input.options || ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4", "hlcc4", "volume"];
    return <label className="pine-input"><span>{input.title}</span>
      <select value={String(input.value)} onChange={(e) => {
        const raw = e.target.value;
        const match = options.find((o) => String(o) === raw);
        send(match ?? raw);
      }}>{options.map((o) => <option key={String(o)} value={String(o)}>{String(o)}</option>)}</select></label>;
  }
  if (input.kind === "time") {
    // input.time(): UNIX milliseconds, edited as a UTC date and time (this terminal's exchange time zone)
    const ms = Number(input.value);
    const shown = Number.isFinite(ms) ? new Date(ms).toISOString().slice(0, 16) : "";
    return <label className="pine-input"><span>{input.title} <small>(UTC)</small></span>
      <input className="mono" type="datetime-local" step="60" value={shown} onChange={(e) => {
        const next = Date.parse(`${e.target.value}:00Z`);
        if (Number.isFinite(next) && next !== ms) send(next);
      }} /></label>;
  }
  const numeric = ["int", "float", "price"].includes(input.kind);
  const commit = () => {
    if (numeric) {
      const number = Number(draft);
      if (draft.trim() === "" || !Number.isFinite(number)) { setDraft(String(input.value)); return; }
      if (number !== input.value) send(number);
    } else if (draft !== input.value) send(draft);
  };
  return <label className="pine-input"><span>{input.title}</span>
    <input className="mono" value={draft} inputMode={numeric ? "decimal" : undefined} onChange={(e) => setDraft(e.target.value)}
      onBlur={commit} onKeyDown={(e) => { if (e.key === "Enter") e.currentTarget.blur(); }} /></label>;
}

// request.security() provenance, one line per requested context (symbol · timeframe · source · bars).
function contextsTitle(contexts) {
  if (!contexts?.length) return undefined;
  return contexts.map((c) => `${c.symbol} ${c.timeframe} · ${c.provider} · `
    + (c.native ? "native" : `aggregated from ${c.aggregation_base}`) + ` · ${c.bar_count} bars`
    + (c.forming ? " · forming bar" : "") + ` · ${c.data_identity}`).join("\n");
}

function ScriptRow({ script, editing, onEdit }) {
  const [open, setOpen] = useState(false);
  const outputs = script.outputs.length;
  return (
    <div className={`pine-script ${script.enabled ? "" : "is-hidden"} ${editing ? "is-editing" : ""}`} data-script={script.id}>
      <div className="pine-script-head">
        <input type="checkbox" checked={script.enabled} title={script.enabled ? "Hide" : "Show"}
          onChange={(e) => sendEvent("pine_toggle", { id: script.id, enabled: e.target.checked })} />
        <b className="pine-script-title" title={script.title}>{script.title}</b>
        <span className="pine-badge">{script.overlay ? "overlay" : "pane"}</span>
        {script.inputs.length > 0 && <button type="button" className="rp-btn" onClick={() => setOpen((v) => !v)}>Inputs {open ? "▴" : "▾"}</button>}
        <button type="button" className="rp-btn" onClick={() => onEdit(script)}>Edit</button>
        <button type="button" className="rp-btn exit" title="Remove from chart" onClick={() => sendEvent("pine_remove", { id: script.id })}>✕</button>
      </div>
      <div className="pine-script-meta muted mono" title={contextsTitle(script.contexts)}>
        {script.error ? "error" : `${outputs} output${outputs === 1 ? "" : "s"} · ${script.bars.toLocaleString()} bars · ${script.runtime_ms} ms`
          + (script.incremental ? ` · ${script.executed} bar${script.executed === 1 ? "" : "s"} re-run` : "")
          + (script.contexts?.length ? ` · ${script.contexts.length} requested context${script.contexts.length === 1 ? "" : "s"}` : "")}
      </div>
      {script.error && <div className="pine-script-error">{script.error.message}{script.error.bar_index !== null && script.error.bar_index !== undefined ? ` (bar ${script.error.bar_index})` : ""}</div>}
      {script.truncated_bars > 0 && <div className="pine-script-note">Runs on the last {script.bars.toLocaleString()} bars ({script.truncated_bars.toLocaleString()} older bars not executed).</div>}
      {open && <div className="pine-inputs">{script.inputs.map((input) => <InputField key={input.index} script={script} input={input} />)}</div>}
    </div>
  );
}

function Compatibility({ compat }) {
  const groups = useMemo(() => {
    const out = {};
    compat.features.forEach((f) => { (out[f.category] = out[f.category] || []).push(f); });
    return out;
  }, [compat]);
  return (
    <div className="pine-compat">
      <div className="pine-compat-head">Coverage by language feature — {compat.counts.supported} supported, {compat.counts.partial} partial,
        {" "}{compat.counts.gap} not yet implemented · {compat.functions} built-in functions, {compat.variables} built-in variables.
        No claim of full Pine compatibility.</div>
      {Object.entries(groups).map(([category, features]) => (
        <div key={category} className="pine-compat-group">
          <h4>{category}</h4>
          {features.map((f) => <div key={f.id} className={`pine-compat-row is-${f.status}`} title={f.note || f.description}>
            <span className={`pine-chip is-${f.status}`}>{f.status}</span> {f.description}</div>)}
        </div>
      ))}
    </div>
  );
}

export function PineEditor({ pine, pending }) {
  const examples = pine?.examples || [];
  const [text, setText] = useState(() => loadDraft(examples[0]?.source || ""));
  const [lastSent, setLastSent] = useState(null);            // {id, text}
  const [editingId, setEditingId] = useState(null);
  const [view, setView] = useState("problems");
  const area = useRef(null);
  const gutter = useRef(null);
  useEffect(() => saveDraft(text), [text]);
  const count = pine?.scripts.length ?? 0;
  const previousCount = useRef(count);
  useEffect(() => {                                          // a script was added: show the list
    if (count > previousCount.current) setView("scripts");
    previousCount.current = count;
  }, [count]);
  if (!pine) return <div className="pine-empty">Pine is not available on this view.</div>;

  const editor = pine.editor;
  const result = editor;                                     // Python's result for the last compile/add/update
  const stale = !!(result && lastSent && lastSent.text !== text);
  const busy = !!pending && pending.type?.startsWith("pine_");
  const editing = pine.scripts.find((s) => s.id === editingId) || null;
  const lines = text.split("\n").length;

  const send = (type, extra = {}) => {
    const id = sendEvent(type, { source: text, ...extra });
    setLastSent({ id, text });
    setView("problems");
  };
  const jump = (line) => {
    const el = area.current;
    if (!el) return;
    const offsets = text.split("\n").slice(0, line - 1).reduce((sum, row) => sum + row.length + 1, 0);
    el.focus();
    el.setSelectionRange(offsets, offsets + (text.split("\n")[line - 1] || "").length);
    el.scrollTop = Math.max(0, (line - 3) * 18);
  };
  const onKeyDown = (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const el = e.currentTarget;
      const { selectionStart: start, selectionEnd: end } = el;
      const next = `${text.slice(0, start)}    ${text.slice(end)}`;
      setText(next);
      requestAnimationFrame(() => el.setSelectionRange(start + 4, start + 4));
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      send("pine_compile");
    }
  };

  return (
    <div className="pine-editor">
      <div className="pine-left">
        <div className="pine-toolbar">
          <select className="pine-examples" value="" aria-label="Load an example"
            onChange={(e) => { const ex = examples.find((x) => x.name === e.target.value); if (ex) { setText(ex.source); setEditingId(null); } }}>
            <option value="">Examples…</option>
            {examples.map((ex) => <option key={ex.name} value={ex.name}>{ex.name}</option>)}
          </select>
          <button type="button" className="btn small pine-compile" disabled={busy || !text.trim()} onClick={() => send("pine_compile")}
            title="Compile (Ctrl/⌘+Enter)">Compile</button>
          <button type="button" className="btn primary small pine-add" disabled={busy || !text.trim()} onClick={() => send("pine_add")}>
            Add to chart</button>
          {editing && (
            <button type="button" className="btn small pine-update" disabled={busy} onClick={() => send("pine_update", { id: editing.id })}>
              Update “{editing.title}”</button>
          )}
          {editing && <button type="button" className="rp-btn" onClick={() => setEditingId(null)}>Stop editing</button>}
          <div className="spacer" />
          <span className="muted mono">{lines} lines{busy ? " · compiling…" : ""}</span>
        </div>
        <div className="pine-code">
          <pre className="pine-gutter mono" ref={gutter} aria-hidden="true">
            {Array.from({ length: lines }, (_, i) => `${i + 1}\n`).join("")}
          </pre>
          <textarea ref={area} className="pine-text mono" value={text} spellCheck={false} wrap="off" aria-label="Pine source"
            onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown}
            onScroll={(e) => { if (gutter.current) gutter.current.scrollTop = e.currentTarget.scrollTop; }} />
        </div>
      </div>
      <div className="pine-right">
        <div className="pine-tabs">
          {[["problems", "Problems"], ["scripts", `On chart (${pine.scripts.length})`], ["compat", "Compatibility"]].map(([key, label]) => (
            <button key={key} type="button" className={`pine-tab ${view === key ? "is-active" : ""}`} onClick={() => setView(key)}>{label}</button>
          ))}
        </div>
        <div className="pine-pane">
          {view === "problems" && <Diagnostics result={result} stale={stale} onJump={jump} />}
          {view === "scripts" && (pine.scripts.length
            ? pine.scripts.map((script) => <ScriptRow key={script.id} script={script} editing={editingId === script.id}
              onEdit={(s) => { setText(s.source); setEditingId(s.id); }} />)
            : <div className="pine-empty">No Pine scripts on the chart. Write or load one, then “Add to chart”.</div>)}
          {view === "compat" && <Compatibility compat={pine.compat} />}
        </div>
      </div>
    </div>
  );
}

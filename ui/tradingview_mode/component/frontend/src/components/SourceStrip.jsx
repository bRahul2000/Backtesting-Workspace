import React, { useState } from "react";
import { formatAge, statusClass, utcClock } from "../liveControls.js";

// Chart / Signals / Execution roles (read-only). Python decides every value:
// the signal source is always Exness MT5 and execution is always disabled here.
const roleClass = (state) => (state === "UNAVAILABLE" ? "unavailable" : state === "DISABLED" ? "disabled" : statusClass(state));

function Role({ label, role, detail, showSymbol = true }) {
  const cls = roleClass(role.state);
  const name = `${role.provider}${showSymbol && role.symbol ? ` · ${role.symbol}` : ""}`;
  return (
    <span className={`src-role is-${role.role}`} data-role={role.role} title={`${name} · ${role.state} — ${role.reason}`}>
      <i>{label}</i>
      <span className="src-name">{name}</span>
      <b className={`src-state ${cls}`}>{cls === "live" ? "●" : "○"} {role.state}</b>
      {detail && <span className="src-detail">{detail}</span>}
    </span>
  );
}

function Details({ sources }) {
  const { chart, signal, execution, readiness } = sources;
  const age = (t) => (t ? `${utcClock(t)} · ${formatAge(Date.now() / 1000 - t)} ago` : "—");
  return (
    <div className="src-details" role="dialog" aria-label="Source details">
      <div className="src-col">
        <h4>Chart source</h4>
        <div className="kv"><span>Provider</span><span>{chart.provider}</span></div>
        <div className="kv"><span>Symbol</span><span>{chart.symbol}</span></div>
        <div className="kv"><span>Timeframe</span><span>{chart.timeframe}</span></div>
        <div className="kv"><span>State</span><span>{chart.state}</span></div>
        <div className="kv"><span>Last update</span><span className="mono">{age(chart.last_update)}</span></div>
        <div className="kv"><span>Authoritative</span><span>No (chart / context only)</span></div>
      </div>
      <div className="src-col">
        <h4>Signal source</h4>
        <div className="kv"><span>Provider</span><span>{signal.provider}</span></div>
        <div className="kv"><span>Symbol</span><span>{signal.symbol}</span></div>
        <div className="kv"><span>MT5 feed</span><span>{signal.feed_state}</span></div>
        <div className="kv"><span>Last update</span><span className="mono">{age(signal.last_update)}</span></div>
        <div className="kv"><span>Authority</span><span>{sources.signal_authority_ready ? "READY" : "NOT READY"}</span></div>
        <ul className="src-checks">
          {sources.checks.map((c) => <li key={c.name} className={c.ok ? "ok" : "bad"} title={c.reason}>{c.ok ? "✓" : "✕"} {c.name.replace("_", " ")}</li>)}
        </ul>
      </div>
      <div className="src-col">
        <h4>Execution</h4>
        <div className="kv"><span>Broker</span><span>{execution.provider}</span></div>
        <div className="kv"><span>Symbol</span><span>{execution.symbol}</span></div>
        <div className="kv"><span>Enabled</span><span>No</span></div>
        <div className="kv"><span>Broker connected</span><span>{readiness.broker_connected ? "Yes" : "No"}</span></div>
        <div className="kv"><span>Reason</span><span>{execution.reason}</span></div>
      </div>
      <div className="src-col src-log">
        <h4>Source-state log</h4>
        <ol>{[...sources.log].reverse().map((e, i) => <li key={`${e.time}-${i}`}><span className="mono">{e.time}</span> {e.message}</li>)}</ol>
      </div>
    </div>
  );
}

// Order: roles, Details, then the note - the note is the only part that shrinks away.
export function SourceStrip({ sources }) {
  const [open, setOpen] = useState(false);
  if (!sources) return null;
  const { chart, signal, execution } = sources;
  const signalDetail = signal.state === "LIVE" ? null
    : signal.feed_state === "LIVE" ? "revalidating" : signal.feed_state;  // underlying MT5 feed state
  return (
    <>
    <div className={`source-strip ${sources.signal_authority_ready ? "is-ready" : "is-unavailable"}`} aria-label="Source roles">
      <Role label="Chart" role={chart} />
      <Role label="Signals" role={signal} detail={signalDetail} />
      <Role label="Execution" role={execution} showSymbol={false} />
      <button type="button" className={`src-toggle ${open ? "is-open" : ""}`} onClick={() => setOpen((v) => !v)}
        aria-expanded={open}>Details {open ? "▴" : "▾"}</button>
      <span className={`src-note ${sources.signal_authority_ready ? "" : "is-warn"}`}
        title={sources.signal_authority_ready ? sources.note || "" : signal.reason}>
        {sources.signal_authority_ready ? sources.note : signal.reason}
      </span>
    </div>
    {open && <Details sources={sources} />}
    </>
  );
}

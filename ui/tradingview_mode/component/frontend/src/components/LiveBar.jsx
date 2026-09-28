import React, { useEffect, useState } from "react";
import { sendEvent } from "../events.js";
import { formatAge, quoteText, statusClass, utcClock } from "../liveControls.js";

// Contract, source and state live in the header and the chart legend; this strip holds
// the controls and the provider's quotes, and its Exit button is never pushed off.

function Select({ label, value, options, onChange, disabledText }) {
  return (
    <label className="live-field"><i>{label}</i>
      <select value={value} onChange={(e) => onChange(e.target.value)} aria-label={`Live ${label.toLowerCase()}`}>
        {disabledText && <option value="" disabled>{disabledText}</option>}
        {options.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
      </select>
    </label>
  );
}

const timeframeOptions = (live) => live.timeframes.map((t) => ({ key: t, label: t }));

// Live mode, step 1: choose market, source and timeframe. Nothing connects until Go Live.
function LiveSetup({ live }) {
  const [market, setMarket] = useState(live.market || "");
  const [source, setSource] = useState(live.source);
  const [timeframe, setTimeframe] = useState(live.timeframe);
  useEffect(() => { setMarket(live.market || ""); setSource(live.source); setTimeframe(live.timeframe); },
    [live.market, live.source, live.timeframe]);
  const contract = market ? live.contracts[market][source] : null;
  return (
    <div className={`live-bar is-setup ${live.message ? "has-message" : ""}`} role="group" aria-label="Live setup">
      <span className="live-state is-setup"><span className="live-dot" />LIVE SETUP</span>
      {live.message && <span className="live-unsupported" title={live.message}>{live.message}</span>}
      <Select label="Market" value={market} options={live.markets} onChange={setMarket} disabledText="Choose…" />
      <Select label="Source" value={source} options={live.sources} onChange={setSource} />
      <Select label="Timeframe" value={timeframe} options={timeframeOptions(live)} onChange={setTimeframe} />
      <button type="button" className="btn primary small go-live" disabled={!market}
        title={contract ? `Connect to ${contract} (read-only market data)` : "Choose a market"}
        onClick={() => sendEvent("go_live", { market, source, timeframe })}>Go Live</button>
      <span className="live-reason live-contract">{contract || "Read-only market data · the chart shows the historical dataset until Go Live"}</span>
      <div className="spacer" />
      <button type="button" className="rp-btn exit" title="Leave Live mode" onClick={() => sendEvent("exit_live")}>✕ Exit</button>
    </div>
  );
}

// Streaming strip. Every value (and its label) comes from the active provider via Python.
export function LiveBar({ live }) {
  if (!live?.enabled) return null;
  if (live.phase === "setup") return <LiveSetup live={live} />;
  const cls = statusClass(live.status);
  const go = (change) => sendEvent("go_live", { market: live.market, source: live.source, timeframe: live.timeframe, ...change });
  return (
    <div className={`live-bar ${cls}`} role="status" aria-label="Live market data status" data-source={live.source}>
      <span className={`live-state ${cls}`} title={live.reason}><span className="live-dot" />{live.status}</span>
      <select className="live-switch" value={live.market} aria-label="Live market" onChange={(e) => go({ market: e.target.value })}>
        {live.markets.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
      </select>
      <select className="live-switch" value={live.source} aria-label="Live source" onChange={(e) => go({ source: e.target.value })}>
        {live.sources.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
      </select>
      <span className="live-sep" />
      {live.quotes.map((q) => (
        <span key={q.key} className="live-q" data-quote={q.key} title={q.title}>
          <i>{q.label}</i><b className="mono">{quoteText(q.value, live.digits)}</b>
        </span>
      ))}
      <span className="live-sep" />
      <span className="live-shrink">
        <span className="live-meta mono" title={`Last message from ${live.source_label} at ${utcClock(live.updated_utc)}`}>
          Updated {utcClock(live.updated_utc)} · {formatAge(live.heartbeat_age_s)} ago
        </span>
        {live.tick_age_s !== null && live.tick_age_s !== undefined && live.tick_age_s > 5
          && <span className="live-meta mono">last tick {formatAge(live.tick_age_s)} ago</span>}
        {live.forming_bar_time && <span className="live-meta mono">forming {utcClock(live.forming_bar_time).slice(0, 5)}</span>}
        <span className="live-reason" title={live.reason}>{live.status === "LIVE" ? "Read-only · no trading" : live.reason}</span>
      </span>
      <button type="button" className="rp-btn exit" title="Exit Live and return to the historical chart" onClick={() => sendEvent("exit_live")}>✕ Exit</button>
    </div>
  );
}

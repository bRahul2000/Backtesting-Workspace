import React, { useEffect, useState } from "react";
import { sendEvent } from "../events.js";
import { formatAge, quoteText, statusClass, utcClock } from "../liveControls.js";

// Live mode, step 1: choose symbol/timeframe. Nothing is read from MT5 until Go Live.
function LiveSetup({ live }) {
  const [symbol, setSymbol] = useState(live.symbol || "");
  const [timeframe, setTimeframe] = useState(live.timeframe);
  useEffect(() => { setSymbol(live.symbol || ""); setTimeframe(live.timeframe); }, [live.symbol, live.timeframe]);
  return (
    <div className="live-bar is-setup" role="group" aria-label="Live setup">
      <span className="live-state is-setup"><span className="live-dot" />LIVE SETUP</span>
      {live.message && <span className="live-unsupported">{live.message}</span>}
      <label className="live-field"><i>Symbol</i>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="Live symbol">
          <option value="" disabled>Choose…</option>
          {live.symbols.map((s) => <option key={s} value={s}>{s} · Exness</option>)}
        </select>
      </label>
      <label className="live-field"><i>Timeframe</i>
        <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)} aria-label="Live timeframe">
          {live.timeframes.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </label>
      <button type="button" className="btn primary small go-live" disabled={!symbol}
        onClick={() => sendEvent("go_live", { symbol, timeframe })}>Go Live</button>
      <span className="live-reason">Read-only MT5 market data · the chart shows the historical dataset until Go Live</span>
      <div className="spacer" />
      <button type="button" className="rp-btn exit" title="Leave Live mode" onClick={() => sendEvent("exit_live")}>✕ Exit</button>
    </div>
  );
}

// Read-only live status strip. All values are the broker's, relayed by Python.
export function LiveBar({ live }) {
  if (!live?.enabled) return null;
  if (live.phase === "setup") return <LiveSetup live={live} />;
  const cls = statusClass(live.status);
  const digits = live.digits;
  return (
    <div className={`live-bar ${cls}`} role="status" aria-label="Live market data status">
      <span className={`live-state ${cls}`} title={live.reason}><span className="live-dot" />{live.status}</span>
      <select className="live-switch mono" value={live.symbol} aria-label="Live symbol"
        onChange={(e) => sendEvent("go_live", { symbol: e.target.value, timeframe: live.timeframe })}>
        {live.symbols.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <span className="live-symbol mono">{live.timeframe}</span>
      <span className="live-sep" />
      <span className="live-q"><i>Bid</i><b className="mono">{quoteText(live.bid, digits)}</b></span>
      <span className="live-q"><i>Ask</i><b className="mono">{quoteText(live.ask, digits)}</b></span>
      <span className="live-q" title={live.spread_points !== null ? `${live.spread_points} points (broker)` : undefined}>
        <i>Spread</i><b className="mono">{quoteText(live.spread, digits)}</b>
      </span>
      <span className="live-sep" />
      <span className="live-meta mono" title="Last write by the MT5 feed service">
        Updated {utcClock(live.updated_utc)} · {formatAge(live.heartbeat_age_s)} ago
      </span>
      {live.tick_age_s !== null && live.tick_age_s > 5 && <span className="live-meta mono">last tick {formatAge(live.tick_age_s)} ago</span>}
      {live.forming_bar_time && <span className="live-meta mono">forming {utcClock(live.forming_bar_time).slice(0, 5)}</span>}
      <span className="live-reason">{live.status === "LIVE" ? "Read-only · no trading" : live.reason}</span>
      <div className="spacer" />
      <button type="button" className="rp-btn exit" title="Exit Live and return to the historical chart" onClick={() => sendEvent("exit_live")}>✕ Exit</button>
    </div>
  );
}

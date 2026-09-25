import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { isIdle, sendEvent } from "../events.js";
import { utcLabel } from "../chart/chartView.js";
import { ChartEngine } from "../chart/ChartEngine.js";
import { LiveBar } from "./LiveBar.jsx";
import { ReplayBar } from "./ReplayBar.jsx";
import { formatPrice, formatSigned, formatVolume, paramsLabel, providerShort, timeframeLabel } from "../format.js";

function Values({ values, precision }) {
  return values.map((v) => (
    <span key={v.name} className="lg-val mono" style={{ color: v.color }}>
      {v.value === undefined ? "—" : formatPrice(v.value, precision)}
    </span>
  ));
}

function Legend({ engine, payload }) {
  const [legend, setLegend] = useState(null);
  useEffect(() => engine?.onCrosshair(setLegend), [engine]);
  const precision = payload.price_precision;
  const bar = legend?.bar;
  const direction = bar ? (bar.close >= bar.open ? "up" : "down") : "";
  return (
    <>
      <div className="legend">
        <div className="lg-title">
          <span className="lg-symbol">{payload.live?.phase === "streaming" ? payload.live.title : payload.symbol}</span>
          <span>·</span><span>{timeframeLabel(payload.timeframe)}</span>
          {payload.live?.phase !== "streaming" && <><span>·</span><span>{providerShort(payload.provider)}</span></>}
          <span className={`lg-source ${payload.source.native ? "" : "derived"}`}>{payload.source.description}</span>
        </div>
        {payload.live?.phase === "streaming" && payload.live.note && <div className="lg-note">{payload.live.note}</div>}
        {bar && (
          <div className={`lg-ohlc mono ${direction}`}>
            <span className={`lg-time ${legend.hovering ? "is-hover" : ""}`} title="Candle open time (UTC)">{utcLabel(bar.time)}</span>
            <span><i>O</i>{formatPrice(bar.open, precision)}</span>
            <span><i>H</i>{formatPrice(bar.high, precision)}</span>
            <span><i>L</i>{formatPrice(bar.low, precision)}</span>
            <span><i>C</i>{formatPrice(bar.close, precision)}</span>
            <span>{formatSigned(legend.change, precision)} ({formatSigned(legend.changePct, 2, "%")})</span>
            {payload.ui.show_volume && <span><i>Vol</i>{formatVolume(legend.volume)}</span>}
          </div>
        )}
        {legend?.overlays.map((o) => (
          <div key={o.id} className="lg-ind">
            <span className="lg-ind-name">{o.name} <span className="muted">{paramsLabel(o.params)}</span></span>
            <Values values={o.values} precision={precision} />
          </div>
        ))}
      </div>
      {legend?.panes.map((p) => p.top !== null && (
        <div key={p.id} className="legend pane-legend" style={{ top: p.top + 4 }}>
          <div className="lg-ind">
            <span className="lg-ind-name">{p.name} <span className="muted">{paramsLabel(p.params)}</span></span>
            <Values values={p.values} precision={2} />
          </div>
        </div>
      ))}
    </>
  );
}

export function ChartPanel({ payload, onEngine, onCrosshairTime, tradesByKey, selectedKey, busy }) {
  const host = useRef(null);
  const [engine, setEngine] = useState(null);
  const [dismissed, setDismissed] = useState(() => new Set());

  const [atLatest, setAtLatest] = useState(true);

  useLayoutEffect(() => {
    const instance = new ChartEngine(host.current);
    // Older live history: asked for once per left edge, only when no event is in flight.
    instance.onNeedHistory = () => (isIdle() ? (sendEvent("load_live_history"), true) : false);
    window.__tvChart = instance; // read-only hook for browser regression tests
    setEngine(instance);
    onEngine(instance);
    return () => { onEngine(null); instance.destroy(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => engine?.onFollow(setAtLatest), [engine]);

  useEffect(() => {
    if (!engine) return;
    engine.update(payload);
    engine.setTrades(payload.trade_overlay.trades, tradesByKey, selectedKey);
  }, [engine, payload, tradesByKey, selectedKey]);
  useEffect(() => engine?.onCrosshair((legend) => onCrosshairTime(legend.time)), [engine, onCrosshairTime]);

  const notices = payload.notices.filter((notice) => !dismissed.has(notice.message));
  return (
    <main className={`chart-panel ${payload.replay?.enabled || payload.live?.enabled ? "replaying" : ""} ${
      payload.live?.phase === "setup" && payload.live.message ? "live-message" : ""}`}>
      <div className="chart-host" ref={host} />
      {engine && <Legend engine={engine} payload={payload} />}
      {payload.bars.length === 0 && <div className="chart-empty">No bars in the selected range.</div>}
      {!atLatest && payload.bars.length > 0 && !payload.replay?.enabled && (
        <button type="button" className="go-latest" title="Scroll to the newest candle and follow it"
          onClick={() => engine?.scrollToLatest()}>Go to latest ⇥</button>
      )}
      <LiveBar live={payload.live} />
      <ReplayBar replay={payload.replay} busy={busy} onLatest={() => {
        engine?.scrollToLatest();
        sendEvent("go_to_replay_latest");
      }} />
      {notices.length > 0 && (
        <div className="notices">
          {notices.map((notice) => (
            <div key={notice.message} className={`notice level-${notice.level}`}>
              <span>{notice.message}</span>
              <button type="button" onClick={() => setDismissed((prev) => new Set(prev).add(notice.message))} aria-label="Dismiss">×</button>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}

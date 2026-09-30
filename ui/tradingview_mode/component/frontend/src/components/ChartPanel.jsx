import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { isIdle, sendEvent } from "../events.js";
import { utcLabel } from "../chart/chartView.js";
import { ChartEngine } from "../chart/ChartEngine.js";
import { LiveBar } from "./LiveBar.jsx";
import { ReplayBar } from "./ReplayBar.jsx";
import { SourceStrip } from "./SourceStrip.jsx";
import { IndicatorControls } from "./IndicatorControls.jsx";
import { describeFill } from "../chart/strategyMarkers.js";
import { formatPrice, formatSigned, formatUtc, formatVolume, paramsLabel, providerShort, timeframeLabel } from "../format.js";

function Values({ values, precision }) {
  return values.map((v) => (
    <span key={v.name} className="lg-val mono" style={{ color: v.color }}>
      {v.value === undefined ? "—" : formatPrice(v.value, precision)}
    </span>
  ));
}

// One indicator in the chart legend (overlays) or at the top of its pane: name, settings summary, values under the
// crosshair, a LIMITED / unavailable note when its data requirement is not met, and eye / gear / X.
function IndicatorRow({ item, engine, catalog, precision }) {
  const hidden = item.visible === false;
  return (
    <div className={`lg-ind ${hidden ? "is-hidden" : ""} ${item.native ? "is-native" : ""}`} data-indicator={item.id}>
      <span className="lg-ind-name">{item.native ? (item.label || item.name) : <>{item.name} <span className="muted">{paramsLabel(item.params)}</span></>}</span>
      {item.status === "limited" && <span className="lg-badge warn" title={item.note}>LIMITED</span>}
      {item.status === "unavailable" && <span className="lg-badge bad" title={item.note}>unavailable: {item.note}</span>}
      {!hidden && <Values values={item.values} precision={precision} />}
      {item.native && <IndicatorControls item={item} engine={engine} catalog={catalog} />}
    </div>
  );
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
        {legend && [...legend.overlays, ...legend.panes.filter((p) => p.top === null)].map((o) => (
          <IndicatorRow key={o.id} item={o} engine={engine} catalog={payload.indicator_catalog} precision={precision} />
        ))}
      </div>
      {legend?.panes.map((p) => p.top !== null && (
        <div key={p.id} className="legend pane-legend" style={{ top: p.top + 4 }}>
          <IndicatorRow item={p} engine={engine} catalog={payload.indicator_catalog} precision={2} />
        </div>
      ))}
    </>
  );
}

// Pine strategy fills on the hovered bar (compact markers carry only a tag; the details are here).
function FillTooltip({ engine, precision }) {
  const [hover, setHover] = useState(null);
  useEffect(() => engine?.onCrosshair((legend) => setHover(legend.fills?.length && legend.point
    ? { fills: legend.fills, trades: legend.trades, point: legend.point, time: legend.time } : null)), [engine]);
  if (!hover) return null;
  return (
    <div className="fill-tooltip" style={{ left: hover.point.x + 14, top: Math.max(4, hover.point.y - 10) }}>
      <div className="fill-tooltip-time mono">{formatUtc(hover.time)} UTC · {hover.fills.length} fill{hover.fills.length > 1 ? "s" : ""}</div>
      {hover.fills.map((fill) => (
        <div key={fill.key} className={`fill-tooltip-row ${fill.side > 0 ? "is-buy" : "is-sell"}`}>
          {describeFill(fill, hover.trades, precision)}
        </div>
      ))}
    </div>
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
      payload.live?.phase === "setup" && payload.live.message ? "live-message" : ""} ${payload.sources ? "has-sources" : ""}`}>
      <div className="chart-host" ref={host} />
      {engine && <Legend engine={engine} payload={payload} />}
      {engine && <FillTooltip engine={engine} precision={payload.price_precision ?? 2} />}
      {payload.bars.length === 0 && <div className="chart-empty">No bars in the selected range.</div>}
      {!atLatest && payload.bars.length > 0 && !payload.replay?.enabled && (
        <button type="button" className="go-latest" title="Scroll to the newest candle and follow it"
          onClick={() => engine?.scrollToLatest()}>Go to latest ⇥</button>
      )}
      <LiveBar live={payload.live} />
      <SourceStrip sources={payload.sources} />
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

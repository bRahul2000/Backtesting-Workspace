import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ChartEngine } from "../chart/ChartEngine.js";
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
          <span className="lg-symbol">{payload.symbol}</span>
          <span>·</span><span>{timeframeLabel(payload.timeframe)}</span>
          <span>·</span><span>{providerShort(payload.provider)}</span>
          <span className={`lg-source ${payload.source.native ? "" : "derived"}`}>{payload.source.description}</span>
        </div>
        {bar && (
          <div className={`lg-ohlc mono ${direction}`}>
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

export function ChartPanel({ payload, onEngine, onCrosshairTime, tradesByKey, selectedKey }) {
  const host = useRef(null);
  const [engine, setEngine] = useState(null);
  const [dismissed, setDismissed] = useState(() => new Set());

  useLayoutEffect(() => {
    const instance = new ChartEngine(host.current);
    setEngine(instance);
    onEngine(instance);
    return () => { onEngine(null); instance.destroy(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!engine) return;
    engine.update(payload);
    engine.setTrades(payload.trade_overlay.trades, tradesByKey, selectedKey);
  }, [engine, payload, tradesByKey, selectedKey]);
  useEffect(() => engine?.onCrosshair((legend) => onCrosshairTime(legend.time)), [engine, onCrosshairTime]);

  const notices = payload.notices.filter((notice) => !dismissed.has(notice.message));
  return (
    <main className="chart-panel">
      <div className="chart-host" ref={host} />
      {engine && <Legend engine={engine} payload={payload} />}
      {payload.bars.length === 0 && <div className="chart-empty">No bars in the selected range.</div>}
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

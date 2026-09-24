import React, { useMemo, useState } from "react";
import { sendEvent } from "../events.js";
import { providerShort, timeframeLabel } from "../format.js";
import { Icon } from "./icons.jsx";
import { Popover } from "./Popover.jsx";

function SymbolMenu({ payload, onClose }) {
  return (
    <div className="menu-list">
      <div className="menu-heading">Registered datasets</div>
      {payload.datasets.map((item) => (
        <button key={item.dataset_key} type="button" disabled={!item.available}
          className={`menu-row ${item.dataset_key === payload.dataset_key ? "is-active" : ""}`}
          onClick={() => { sendEvent("select_dataset", { dataset_key: item.dataset_key }); onClose(); }}>
          <span className="menu-row-main">{item.symbol}</span>
          <span className="menu-row-tag">{timeframeLabel(item.timeframe)}</span>
          <span className="menu-row-sub">{item.label}{item.available ? "" : " · file missing"}</span>
        </button>
      ))}
    </div>
  );
}

function IndicatorMenu({ payload, onClose }) {
  const groups = useMemo(() => {
    const byCategory = new Map();
    payload.indicator_catalog.forEach((item) => {
      if (!byCategory.has(item.category)) byCategory.set(item.category, []);
      byCategory.get(item.category).push(item);
    });
    return [...byCategory.entries()];
  }, [payload.indicator_catalog]);
  return (
    <div className="menu-list">
      {groups.map(([category, items]) => (
        <React.Fragment key={category}>
          <div className="menu-heading">{category}</div>
          {items.map((item) => (
            <button key={item.key} type="button" className="menu-row"
              onClick={() => { sendEvent("add_indicator", { key: item.key }); onClose(); }}>
              <span className="menu-row-main">{item.name}</span>
              <span className="menu-row-tag">{item.pane === "overlay" ? "overlay" : "pane"}</span>
              <span className="menu-row-sub">{Object.entries(item.defaults).map(([k, v]) => `${k} ${v}`).join(" · ") || "no parameters"}</span>
            </button>
          ))}
        </React.Fragment>
      ))}
      <div className="menu-foot">Calculated in Python. Edit parameters in the Indicators panel.</div>
    </div>
  );
}

function RangeMenu({ payload, onClose }) {
  const [start, setStart] = useState(payload.range.start || "");
  const [end, setEnd] = useState(payload.range.end || "");
  const valid = start && end && start <= end;
  return (
    <div className="form-menu">
      <div className="menu-heading">Date range (UTC, inclusive)</div>
      <label className="field"><span>From</span>
        <input type="date" value={start} min={payload.range.min || undefined} max={payload.range.max || undefined} onChange={(e) => setStart(e.target.value)} />
      </label>
      <label className="field"><span>To</span>
        <input type="date" value={end} min={payload.range.min || undefined} max={payload.range.max || undefined} onChange={(e) => setEnd(e.target.value)} />
      </label>
      <div className="menu-hint">Available {payload.range.min} → {payload.range.max}. Max {payload.max_bars.toLocaleString()} bars.</div>
      <div className="button-row">
        <button type="button" className="btn ghost" onClick={() => { sendEvent("set_date_range", { start: null, end: null }); onClose(); }}>Default</button>
        <button type="button" className="btn primary" disabled={!valid} onClick={() => { sendEvent("set_date_range", { start, end }); onClose(); }}>Apply</button>
      </div>
    </div>
  );
}

function SettingsMenu({ payload, crosshairMode, setCrosshairMode, engineActions }) {
  return (
    <div className="form-menu">
      <div className="menu-heading">Chart</div>
      <label className="check">
        <input type="checkbox" checked={!!payload.ui.show_volume}
          onChange={(e) => sendEvent("set_chart_setting", { show_volume: e.target.checked })} />
        <span>Volume</span>
      </label>
      <label className="check">
        <input type="checkbox" checked={crosshairMode === "magnet"}
          onChange={(e) => setCrosshairMode(e.target.checked ? "magnet" : "normal")} />
        <span>Magnet crosshair (snap to OHLC)</span>
      </label>
      <div className="button-row">
        <button type="button" className="btn ghost" onClick={engineActions.fit}>Fit all</button>
        <button type="button" className="btn ghost" onClick={engineActions.latest}>Latest</button>
        <button type="button" className="btn ghost" onClick={engineActions.resetScale}>Auto scale</button>
      </div>
      <div className="menu-heading">Data</div>
      <div className="kv"><span>Dataset</span><span>{payload.source.label}</span></div>
      <div className="kv"><span>Resolution</span><span>{payload.source.description}</span></div>
      <div className="kv"><span>Time</span><span>UTC epoch seconds</span></div>
      <div className="kv"><span>Contract</span><span>v{payload.contract}</span></div>
    </div>
  );
}

export function TopBar({ payload, pending, crosshairMode, setCrosshairMode, engineActions }) {
  const [menu, setMenu] = useState(null);
  const close = () => setMenu(null);
  const toggle = (name) => setMenu((current) => (current === name ? null : name));
  const nativeTimeframes = useMemo(() => new Set(payload.datasets
    .filter((item) => item.symbol === payload.symbol && item.provider === payload.provider)
    .map((item) => item.timeframe)), [payload.datasets, payload.symbol, payload.provider]);

  return (
    <header className="topbar">
      <div className="anchor">
        <button type="button" className="symbol-btn" onClick={() => toggle("symbol")} title={payload.source.label}>
          <span className="symbol-name">{payload.symbol}</span>
          <span className="provider-badge">{providerShort(payload.provider)}</span>
          <Icon name="chevron" size={14} />
        </button>
        <Popover open={menu === "symbol"} onClose={close} width={300}><SymbolMenu payload={payload} onClose={close} /></Popover>
      </div>

      <div className="divider" />
      <div className="tf-group" role="group" aria-label="Timeframe">
        {payload.timeframes.map((tf) => (
          <button key={tf} type="button"
            className={`tf-btn ${tf === payload.timeframe ? "is-active" : ""} ${nativeTimeframes.has(tf) ? "is-native" : ""}`}
            title={nativeTimeframes.has(tf) ? `${tf} · native` : `${tf} · derived in Python from a lower native timeframe`}
            onClick={() => tf !== payload.timeframe && sendEvent("select_timeframe", { timeframe: tf })}>
            {timeframeLabel(tf)}
          </button>
        ))}
      </div>
      <div className="divider" />

      <div className="anchor">
        <button type="button" className={`tool-btn ${menu === "indicators" ? "is-open" : ""}`} onClick={() => toggle("indicators")}>
          <Icon name="fx" size={16} /><span>Indicators</span>
        </button>
        <Popover open={menu === "indicators"} onClose={close} width={280}><IndicatorMenu payload={payload} onClose={close} /></Popover>
      </div>
      <div className="anchor">
        <button type="button" className={`tool-btn ${menu === "range" ? "is-open" : ""}`} onClick={() => toggle("range")}
          title="Date range (UTC)">
          <Icon name="calendar" size={16} />
          <span className="mono">{payload.range.start ? `${payload.range.start} → ${payload.range.end}` : "No data"}</span>
        </button>
        <Popover open={menu === "range"} onClose={close} width={260}><RangeMenu payload={payload} onClose={close} /></Popover>
      </div>
      <div className="anchor">
        <button type="button" className={`tool-btn icon-only ${menu === "settings" ? "is-open" : ""}`} onClick={() => toggle("settings")} title="Settings">
          <Icon name="gear" size={16} />
        </button>
        <Popover open={menu === "settings"} onClose={close} width={280}>
          <SettingsMenu payload={payload} crosshairMode={crosshairMode} setCrosshairMode={setCrosshairMode} engineActions={engineActions} />
        </Popover>
      </div>

      <div className="spacer" />
      <span className={`sync ${pending ? "is-pending" : ""}`} title={pending ? `Waiting for Python: ${pending.type}` : "In sync with Python"}>
        <span className="sync-dot" />{pending ? "Syncing" : "Synced"}
      </span>
      <div className="mode-group" role="group" aria-label="Mode">
        <button type="button" className="mode-btn is-active">Historical</button>
        <button type="button" className="mode-btn" disabled title="Replay — not in this phase">Replay</button>
        <button type="button" className="mode-btn" disabled title="Live MT5 feed — not in this phase">Live</button>
      </div>
    </header>
  );
}

import React, { useMemo, useState } from "react";
import { sendEvent } from "../events.js";
import { statusClass } from "../liveControls.js";
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
          {items.map((item) => {
            const unavailable = item.status === "unavailable";
            return (
              <button key={item.key} type="button" className={`menu-row ${unavailable ? "is-unavailable" : ""}`}
                disabled={unavailable} title={item.note || item.description} aria-label={`Add ${item.name}`}
                onClick={() => { if (!unavailable) { sendEvent("add_indicator", { key: item.key }); onClose(); } }}>
                <span className="menu-row-main">{item.name}</span>
                <span className={`menu-row-tag ${item.status === "limited" ? "warn" : ""}`}>
                  {unavailable ? "unavailable" : item.status === "limited" ? "limited data" : item.pane === "overlay" ? "overlay" : "pane"}</span>
                <span className="menu-row-sub">{unavailable || item.status === "limited" ? item.note
                  : item.params.map((p) => `${p.label} ${p.default}`).join(" · ") || "no parameters"}</span>
              </button>
            );
          })}
        </React.Fragment>
      ))}
      <div className="menu-foot">Calculated in Python on the chart's data. Hide, edit or remove each one from its legend on the chart.</div>
    </div>
  );
}

// Freshness of the local history (Python: workspace_data.py). Presentation only; Refresh data asks Python to append
// the local MT5 sources' newer CLOSED bars to the workspace copy (frozen research datasets are never written).
const STATUS_TEXT = { CURRENT: "Current", STALE: "Stale", UNKNOWN: "Unknown" };

function DataStatusMenu({ status, onClose }) {
  const row = (label, value) => <div className="ds-row"><span>{label}</span><b className="mono">{value || "—"}</b></div>;
  return (
    <div className="form-menu data-status-menu">
      <div className="menu-heading">Historical data · {status.label}</div>
      {row("Last local bar", status.last_local && `${status.last_local} UTC`)}
      {row("Latest available", status.latest_available && `${status.latest_available} UTC`)}
      {row("Status", STATUS_TEXT[status.status])}
      {row("Source checked", status.source_captured && `${status.source_captured} UTC · ${status.source === "mt5_export" ? "MT5 history export" : "MT5 Live feed seed"}`)}
      {status.problems && status.problems.length > 0 && <div className="menu-hint is-warn">{status.problems.join(" · ")}</div>}
      <div className="menu-hint">
        {status.status === "UNKNOWN" ? "No local source is known for this dataset, so its freshness cannot be confirmed."
          : "Closed bars only. Refreshed bars go to this terminal's workspace copy; the frozen research dataset is never changed."}
        {status.workspace_extended ? " Workspace history is active." : ""}
      </div>
      {status.refreshable && (
        <div className="button-row">
          <button type="button" className="btn primary data-refresh" onClick={() => { sendEvent("refresh_data"); onClose(); }}>Refresh data</button>
        </div>
      )}
    </div>
  );
}

const LAYOUT_MODES = [["normal", "Normal layout"], ["chart", "Chart only"], ["tester", "Chart + Strategy Tester"],
  ["editor", "Chart + Pine Editor"]];

function LayoutMenu({ layoutApi, onClose }) {
  const { layout, update, setMode } = layoutApi;
  return (
    <div className="menu-list layout-menu">
      <div className="menu-heading">Layout</div>
      {LAYOUT_MODES.map(([mode, label]) => (
        <button key={mode} type="button" className={`menu-row layout-mode ${layout.mode === mode ? "is-active" : ""}`} data-mode={mode}
          onClick={() => { setMode(mode); onClose(); }}>
          <span className="menu-row-main">{label}</span>
        </button>
      ))}
      <div className="menu-heading">Panels (normal layout)</div>
      <label className="check small"><input type="checkbox" checked={layout.tools} onChange={(e) => update({ tools: e.target.checked })} /><span>Chart tools</span></label>
      <label className="check small"><input type="checkbox" checked={layout.watch} onChange={(e) => update({ watch: e.target.checked })} /><span>Watchlist</span></label>
      <div className="menu-foot">Drag the dock's top edge and the watchlist's left edge to resize. Remembered in this browser.</div>
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

function ReplayStartMenu({ payload, onClose }) {
  const [date, setDate] = useState(payload.range.start || "");
  const [time, setTime] = useState("00:00");
  return (
    <div className="form-menu">
      <div className="menu-heading">Replay start (UTC)</div>
      <label className="field"><span>Date</span>
        <input type="date" value={date} min={payload.range.min || undefined} max={payload.range.max || undefined} onChange={(e) => setDate(e.target.value)} />
      </label>
      <label className="field"><span>Time</span><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
      <div className="menu-hint">
        {payload.symbol} · {payload.timeframe} · {payload.source.description}. Replay starts at the bar opening at or before
        this time; later bars are not sent to the chart.
      </div>
      <div className="button-row">
        <button type="button" className="btn primary" disabled={!date}
          onClick={() => { sendEvent("enter_replay", { start: `${date}T${time || "00:00"}` }); onClose(); }}>Start replay</button>
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

export function TopBar({ payload, pending, crosshairMode, setCrosshairMode, engineActions, layoutApi }) {
  const [menu, setMenu] = useState(null);
  const replay = payload.replay?.enabled;
  const live = payload.live?.enabled;
  const streaming = live && payload.live.phase === "streaming";
  const locked = replay ? "Exit Replay to change this" : live ? "Exit Live to change this" : undefined;
  const close = () => setMenu(null);
  const toggle = (name) => setMenu((current) => (current === name ? null : name));
  const nativeTimeframes = useMemo(() => new Set(payload.datasets
    .filter((item) => item.symbol === payload.symbol && item.provider === payload.provider)
    .map((item) => item.timeframe)), [payload.datasets, payload.symbol, payload.provider]);

  return (
    <header className="topbar">
      <div className="anchor">
        <button type="button" className={`symbol-btn ${streaming ? "is-live-header" : ""}`} disabled={replay || live}
          onClick={() => toggle("symbol")} title={streaming ? `${payload.live.identity.venue} · ${payload.live.identity.instrument_kind} · read-only` : locked || payload.source.label}>
          {streaming ? (
            // While Live streams, the header always names contract, source and state.
            <span className="symbol-name live-header">
              {payload.live.title}<span className="live-header-sep">·</span>
              <span className={`live-header-state ${statusClass(payload.live.status)}`}>{payload.live.status}</span>
            </span>
          ) : (
            <>
              <span className="symbol-name">{payload.symbol}</span>
              <span className="provider-badge">{providerShort(payload.provider)}</span>
            </>
          )}
          {!streaming && <Icon name="chevron" size={14} />}
        </button>
        <Popover open={menu === "symbol"} onClose={close} width={300}><SymbolMenu payload={payload} onClose={close} /></Popover>
      </div>

      <div className="divider" />
      <div className="tf-group" role="group" aria-label="Timeframe">
        {payload.timeframes.map((tf) => (
          <button key={tf} type="button" disabled={(replay && tf !== payload.timeframe) || (live && payload.live.phase !== "streaming")}
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
        <button type="button" className={`tool-btn ${menu === "range" ? "is-open" : ""}`} disabled={replay || live} onClick={() => toggle("range")}
          title={locked || "Date range (UTC)"}>
          <Icon name="calendar" size={16} />
          <span className="mono">{payload.range.start ? `${payload.range.start} → ${payload.range.end}` : "No data"}</span>
        </button>
        <Popover open={menu === "range"} onClose={close} width={260}><RangeMenu payload={payload} onClose={close} /></Popover>
      </div>
      {payload.data_status && !live && (
        <div className="anchor ds-anchor">
          <button type="button" className={`tool-btn data-status is-${payload.data_status.status.toLowerCase()} ${menu === "data" ? "is-open" : ""}`}
            onClick={() => toggle("data")}
            title={`Historical data ${STATUS_TEXT[payload.data_status.status].toLowerCase()} · Last local bar ${payload.data_status.last_local || "—"} UTC · latest available ${payload.data_status.latest_available ? `${payload.data_status.latest_available} UTC` : "unknown"}`}>
            <span className="ds-dot" /><span className="ds-text">{STATUS_TEXT[payload.data_status.status]}</span>
            <span className="mono ds-last">{payload.data_status.last_local || "—"}</span>
            {payload.data_status.coverage_gaps?.length > 0 && (
              <span className="ds-gap" title={payload.data_status.coverage_gaps.map((g) => `No local MT5 bars ${g[0]} → ${g[1]} UTC`).join("\n")}>gap</span>
            )}
          </button>
          {payload.data_status.refreshable && payload.data_status.status === "STALE" && !replay && (
            <button type="button" className="tool-btn data-refresh" title="Refresh data: append the newer closed MT5 bars to the workspace history"
              onClick={() => sendEvent("refresh_data")}>↻ Refresh</button>
          )}
          <Popover open={menu === "data"} onClose={close} width={320}>
            <DataStatusMenu status={payload.data_status} onClose={close} />
          </Popover>
        </div>
      )}
      <div className="anchor">
        <button type="button" className={`tool-btn icon-only layout-btn ${menu === "layout" ? "is-open" : ""} ${layoutApi && layoutApi.layout.mode !== "normal" ? "is-focus" : ""}`}
          onClick={() => toggle("layout")} title="Layout: chart only, chart + Strategy Tester, chart + Pine Editor">
          <Icon name="layout" size={16} />
          {layoutApi && layoutApi.layout.mode !== "normal" && <span className="layout-exit">{LAYOUT_MODES.find(([m]) => m === layoutApi.layout.mode)?.[1]}</span>}
        </button>
        {layoutApi && <Popover open={menu === "layout"} onClose={close} width={240}><LayoutMenu layoutApi={layoutApi} onClose={close} /></Popover>}
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
      {/* Popovers are siblings of the mode group: .mode-group clips its overflow
          (rounded corners), which previously hid them and made Live/Replay look dead. */}
      <div className="anchor">
        <div className="mode-group" role="group" aria-label="Mode">
          <button type="button" className={`mode-btn ${replay || live ? "" : "is-active"}`}
            onClick={() => (replay ? sendEvent("exit_replay") : live ? sendEvent("exit_live") : null)}
            title={replay ? "Exit Replay (full historical chart)" : live ? "Exit Live (historical chart)" : "Historical"}>Historical</button>
          <button type="button" className={`mode-btn ${replay ? "is-active replay" : ""}`} disabled={live}
            onClick={() => !replay && toggle("replay")} title={live ? "Exit Live first" : "Historical bar replay"}>Replay</button>
          <button type="button" className={`mode-btn ${live ? "is-active live" : ""}`} disabled={replay}
            onClick={() => !live && sendEvent("enter_live")} title={replay ? "Exit Replay first" : "Read-only Exness MT5 live data"}>Live</button>
        </div>
        <Popover open={menu === "replay"} onClose={close} width={270} align="right"><ReplayStartMenu payload={payload} onClose={close} /></Popover>
      </div>
    </header>
  );
}

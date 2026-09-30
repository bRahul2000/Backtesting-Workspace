import React, { useMemo, useState } from "react";
import { sendEvent } from "../../events.js";
import { formatUtc } from "../../format.js";

// Strategy Tester for the Pine strategy on the chart. Presentation only: trades, fills, equity and every metric come
// from Python's broker emulator for the strategy (SIMULATION - no broker orders), evaluated over the strategy's own
// TEST RANGE, which is independent of the chart's visible window.

const fmt = (value, digits = 2) => (value === null || value === undefined || Number.isNaN(value) ? "—"
  : Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const signed = (value, digits = 2) => (value === null || value === undefined ? "—" : `${value > 0 ? "+" : ""}${fmt(value, digits)}`);
const tone = (value) => (value > 0 ? "pos" : value < 0 ? "neg" : "");
const pct = (value) => (value === null || value === undefined ? "—" : `${signed(value)}%`);
const KIND = { trail: "Trailing stop", stop: "Stop loss", limit: "Take profit", close: "Market close",
  reversal: "Reversal", margin_call: "Margin call", market: "Market" };
const SECTIONS = [["overview", "Overview"], ["performance", "Performance"], ["trades", "List of Trades"], ["properties", "Properties"]];
const SECTION_STORAGE = "tvterm:tester-section";
const utcDate = (epoch) => (epoch ? new Date(epoch * 1000).toISOString().slice(0, 10) : "—");

export function pineStrategies(pine) {
  return (pine?.scripts || []).filter((s) => s.kind === "strategy");
}

function storedSection() {
  try { return window.sessionStorage.getItem(SECTION_STORAGE) || "overview"; } catch { return "overview"; }
}

// ---- header -------------------------------------------------------------------------------------------------------

function Status({ script, pending }) {
  const busy = pending && (pending.type?.startsWith("pine_") || pending.type === "select_dataset" || pending.type === "select_timeframe");
  const [label, cls] = script.error ? ["Error", "bad"] : !script.enabled ? ["Hidden", "muted"] : busy ? ["Calculating…", "busy"]
    : script.strategy ? ["Calculated", "ok"] : ["Not run", "muted"];
  return (
    <span className={`st-status ${cls}`} title={script.error?.message || (script.strategy ? `${script.runtime_ms} ms · ${script.calc_bars} bars` : "")}>
      <i />{label}
    </span>
  );
}

function RangeEditor({ script, bounds, onClose }) {
  const range = script.test_range || {};
  const [mode, setMode] = useState(range.mode === "custom" ? "custom" : "full");
  const split = (text, fallback) => (text || fallback || "").split("T");
  const [fromDate, fromTime] = split(range.start, `${bounds.min}T00:00`);
  const [toDate, toTime] = split(range.end, `${bounds.max}T23:59`);
  const [draft, setDraft] = useState({ fromDate, fromTime, toDate, toTime });
  const set = (key) => (e) => setDraft((prev) => ({ ...prev, [key]: e.target.value }));
  const start = `${draft.fromDate}T${draft.fromTime || "00:00"}`;
  const end = `${draft.toDate}T${draft.toTime || "23:59"}`;
  const invalid = mode === "custom" && (!draft.fromDate || !draft.toDate || start > end);
  const apply = () => {
    sendEvent("pine_set_range", mode === "full" ? { id: script.id, start: null, end: null } : { id: script.id, start, end });
    onClose();
  };
  return (
    <div className="st-range-editor" role="dialog" aria-label="Strategy test range">
      <label className="st-radio"><input type="radio" name="st-range" checked={mode === "full"} onChange={() => setMode("full")} />
        Full available history <span className="muted">{bounds.min} → {bounds.max}</span></label>
      <label className="st-radio"><input type="radio" name="st-range" checked={mode === "custom"} onChange={() => setMode("custom")} />
        Custom range (UTC)</label>
      <div className={`st-range-fields ${mode === "custom" ? "" : "is-disabled"}`}>
        <span>From</span>
        <input type="date" aria-label="Test from date" value={draft.fromDate} min={bounds.min} max={bounds.max} disabled={mode !== "custom"} onChange={set("fromDate")} />
        <input type="time" aria-label="Test from time" value={draft.fromTime} disabled={mode !== "custom"} onChange={set("fromTime")} />
        <span>To</span>
        <input type="date" aria-label="Test to date" value={draft.toDate} min={bounds.min} max={bounds.max} disabled={mode !== "custom"} onChange={set("toDate")} />
        <input type="time" aria-label="Test to time" value={draft.toTime} disabled={mode !== "custom"} onChange={set("toTime")} />
      </div>
      <div className="st-range-note muted">
        The strategy is evaluated only on bars whose open time is inside the range (both ends included). It starts
        fresh at From — its indicators warm up inside the range — and a trade still open at To stays open.
        The chart's visible window is separate: zooming never changes the test.
      </div>
      <div className="st-range-foot">
        <button type="button" className="btn ghost small" onClick={onClose}>Cancel</button>
        <button type="button" className="btn primary small" disabled={invalid} onClick={apply}>Apply</button>
      </div>
    </div>
  );
}

function Header({ script, payload, pending, strategies, onStrategy }) {
  const [editing, setEditing] = useState(false);
  const range = script.test_range;
  const bounds = { min: payload.range.min, max: payload.range.max };
  const rangeText = range ? `${range.mode === "custom" ? "Custom" : "Full history"} · ${utcDate(range.first_time)} → ${utcDate(range.last_time)}`
    : payload.mode === "historical" ? "Full history" : `${payload.mode} bars on the chart`;
  const exporting = pending?.type === "pine_export";
  return (
    <div className="st-head">
      <div className="st-title">
        {strategies.length > 1 ? (
          <select className="st-strategy-select" aria-label="Strategy" value={script.id} onChange={(e) => onStrategy(e.target.value)}>
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.shorttitle || s.title}</option>)}
          </select>
        ) : <b className="st-name">{script.shorttitle || script.title}</b>}
        <span className="st-meta">{payload.symbol} · {payload.timeframe}</span>
        <Status script={script} pending={pending} />
      </div>
      <div className="st-range-wrap">
        <button type="button" className="st-range" aria-label="Test range" disabled={!range}
          title={range ? "Change the strategy's test range" : "The test range applies to the Historical chart"}
          onClick={() => setEditing((open) => !open)}>
          <span className="muted">Test range</span> <b className="mono">{rangeText}</b>
          {range && <span className="muted"> · {range.bars?.toLocaleString("en-US")} bars</span>}
        </button>
        {editing && range && <RangeEditor script={script} bounds={bounds} onClose={() => setEditing(false)} />}
      </div>
      <span className="st-sim muted">Simulated · no broker orders</span>
      <button type="button" className="btn small st-export" disabled={!script.strategy || exporting}
        onClick={() => sendEvent("pine_export", { id: script.id })} title="Download the current trade list (raw values, UTF-8 CSV)">
        {exporting ? "Exporting…" : "Export Trades CSV"}</button>
    </div>
  );
}

// ---- overview -----------------------------------------------------------------------------------------------------

// Equity (line) and its drawdown from the running peak (area), both straight from the report's equity points.
function EquityChart({ equity }) {
  if (!equity || equity.length < 2) return <div className="muted st-empty-chart">No equity history yet.</div>;
  const w = 760, h = 150, dh = 46;
  let peak = -Infinity;
  const points = equity.map(([time, value]) => { peak = Math.max(peak, value); return { time, value, dd: value - peak }; });
  const lo = Math.min(...points.map((p) => p.value)), hi = Math.max(...points.map((p) => p.value));
  const ddLo = Math.min(...points.map((p) => p.dd)) || -1;
  const x = (i) => (i / (points.length - 1)) * w;
  const y = (v) => h - ((v - lo) / (hi - lo || 1)) * (h - 8) - 4;
  const yd = (d) => h + 6 + (d / ddLo) * dh;
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = `M0,${h + 6} ${points.map((p, i) => `L${x(i).toFixed(1)},${yd(p.dd).toFixed(1)}`).join(" ")} L${w},${h + 6} Z`;
  return (
    <div className="st-chart">
      <svg viewBox={`0 0 ${w} ${h + dh + 8}`} preserveAspectRatio="none" role="img" aria-label="Equity and drawdown">
        <path d={area} fill="rgba(242,54,69,0.25)" stroke="none" />
        <path d={line} fill="none" stroke="#2962ff" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="st-chart-axis muted mono"><span>{utcDate(points[0].time)}</span>
        <span>equity {fmt(lo)} – {fmt(hi)} · max drawdown {fmt(ddLo)}</span><span>{utcDate(points.at(-1).time)}</span></div>
    </div>
  );
}

function Card({ label, value, sub, cls = "" }) {
  return (
    <div className="st-card"><span className="st-card-label">{label}</span>
      <b className={`st-card-value mono ${cls}`}>{value}</b>{sub && <span className="st-card-sub mono muted">{sub}</span>}</div>
  );
}

function Overview({ report }) {
  const m = report.metrics;
  return (
    <div className="st-overview">
      <div className="st-cards">
        <Card label="Net P&L" value={signed(m.net_profit)} sub={pct(m.net_profit_percent)} cls={tone(m.net_profit)} />
        <Card label="Total trades" value={m.total_closed_trades} sub={m.open_trades ? `${m.open_trades} open` : null} />
        <Card label="Winning trades" value={m.percent_profitable === null ? "—" : `${fmt(m.percent_profitable)}%`}
          sub={`${m.winning_trades} / ${m.total_closed_trades}`} />
        <Card label="Profit factor" value={fmt(m.profit_factor, 3)} />
        <Card label="Max drawdown" value={fmt(m.max_drawdown)} cls={m.max_drawdown ? "neg" : ""} />
        <Card label="Average trade" value={signed(m.avg_trade)} cls={tone(m.avg_trade)} />
        <Card label="Average winner" value={fmt(m.avg_winning_trade)} cls="pos" />
        <Card label="Average loser" value={fmt(m.avg_losing_trade)} cls="neg" />
        <Card label="Largest winner" value={fmt(m.largest_winning_trade)} cls="pos" />
        <Card label="Largest loser" value={fmt(m.largest_losing_trade)} cls="neg" />
      </div>
      <EquityChart equity={report.equity} />
    </div>
  );
}

// ---- performance --------------------------------------------------------------------------------------------------

function Group({ title, rows }) {
  return (
    <section className="st-group">
      <h4>{title}</h4>
      {rows.map(([name, value, cls, hint]) => (
        <div key={name} className="st-row" title={hint}><span>{name}</span><b className={`mono ${cls || ""}`}>{value}</b></div>
      ))}
    </section>
  );
}

function Performance({ report }) {
  const m = report.metrics;
  const s = report.settings || {};
  return (
    <div className="st-groups">
      <Group title="Returns" rows={[
        ["Net profit", signed(m.net_profit), tone(m.net_profit)], ["Net profit %", pct(m.net_profit_percent), tone(m.net_profit)],
        ["Gross profit", fmt(m.gross_profit), "pos"], ["Gross loss", fmt(m.gross_loss), "neg"],
        ["Initial capital", fmt(m.initial_capital)], ["Ending equity", fmt(m.ending_equity)],
        ["Open P&L", signed(m.open_profit), tone(m.open_profit)],
      ]} />
      <Group title="Trades" rows={[
        ["Closed trades", m.total_closed_trades], ["Long", m.long_trades], ["Short", m.short_trades],
        ["Open trades", m.open_trades], ["Even trades", m.even_trades],
        ["Average bars in trade", fmt(m.avg_bars_in_trade, 1), "", "exit bar − entry bar (engine convention)"],
      ]} />
      <Group title="Wins / losses" rows={[
        ["Winning trades", m.winning_trades], ["Losing trades", m.losing_trades],
        ["Win rate", m.percent_profitable === null ? "—" : `${fmt(m.percent_profitable)}%`],
        ["Average trade", signed(m.avg_trade), tone(m.avg_trade)], ["Average winner", fmt(m.avg_winning_trade), "pos"],
        ["Average loser", fmt(m.avg_losing_trade), "neg"], ["Largest winner", fmt(m.largest_winning_trade), "pos"],
        ["Largest loser", fmt(m.largest_losing_trade), "neg"],
        ["Long net profit", signed(m.long_net_profit), tone(m.long_net_profit)],
        ["Short net profit", signed(m.short_net_profit), tone(m.short_net_profit)],
      ]} />
      <Group title="Risk / drawdown" rows={[
        ["Max drawdown", fmt(m.max_drawdown), m.max_drawdown ? "neg" : ""], ["Max run-up", fmt(m.max_runup)],
        ["Profit factor", fmt(m.profit_factor, 3)], ["Margin calls", m.margin_calls],
      ]} />
      <Group title="Costs (as modelled)" rows={[
        ["Commission paid", fmt(m.commission_paid)], ["Commission setting", `${s.commission_value ?? "—"} · ${s.commission_type ?? "—"}`],
        ["Slippage setting", `${s.slippage ?? 0} ticks`],
      ]} />
    </div>
  );
}

// ---- list of trades -----------------------------------------------------------------------------------------------

const COLUMNS = [
  ["number", "#", (t) => t.number], ["direction", "Type", (t) => t.direction], ["entry_time", "Entry time", (t) => t.entry_time],
  ["entry_price", "Entry price", (t) => t.entry_price], ["exit_time", "Exit time", (t) => t.exit_time ?? Infinity],
  ["exit_price", "Exit price", (t) => t.exit_price ?? -Infinity], ["qty", "Qty", (t) => t.qty],
  ["profit", "P&L", (t) => t.profit ?? -Infinity], ["profit_percent", "P&L %", (t) => t.profit_percent ?? -Infinity],
  ["exit_kind", "Exit reason", (t) => `${t.exit_kind || ""}${t.exit_comment || ""}`], ["bars_held", "Bars", (t) => t.bars_held ?? -1],
];

export function PineTradesTable({ report, precision, selectedKey, onSelect }) {
  const [sort, setSort] = useState({ key: "number", dir: -1 });
  const rows = useMemo(() => {
    const getter = COLUMNS.find((c) => c[0] === sort.key)[2];
    return [...report.trades].sort((a, b) => {
      const x = getter(a), y = getter(b);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [report.trades, sort]);
  const by = (key) => setSort((prev) => ({ key, dir: prev.key === key ? -prev.dir : (key === "number" ? -1 : 1) }));
  return (
    <div className="st-table-wrap">
      <table className="grid-table pine-trades st-trades">
        <thead><tr>{COLUMNS.map(([key, label]) => (
          <th key={key} aria-sort={sort.key === key ? (sort.dir > 0 ? "ascending" : "descending") : "none"}>
            <button type="button" className="st-sort" onClick={() => by(key)}>{label}{sort.key === key ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</button>
          </th>))}</tr></thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.key} className={`${t.open ? "is-open" : ""} ${t.key === selectedKey ? "is-selected" : ""}`}
              onClick={() => onSelect && onSelect(t)} title="Show this trade on the chart" data-trade={t.number}>
              <td className="mono">{t.number}</td>
              <td className={t.direction > 0 ? "pos" : "neg"}>{t.direction > 0 ? "Long" : "Short"}</td>
              <td className="mono">{formatUtc(t.entry_time)}</td>
              <td className="mono">{fmt(t.entry_price, precision)}</td>
              <td className="mono">{t.open ? "Open" : formatUtc(t.exit_time)}</td>
              <td className="mono">{fmt(t.exit_price, precision)}</td>
              <td className="mono">{fmt(t.qty, 4)}</td>
              <td className={`mono ${tone(t.profit)}`}>{signed(t.profit)}</td>
              <td className={`mono ${tone(t.profit_percent)}`} title="net P&L / entry value (engine convention)">{pct(t.profit_percent)}</td>
              <td title={[t.exit_id ? `ID ${t.exit_id}` : "", t.entry_comment ? `entry: ${t.entry_comment}` : ""].filter(Boolean).join(" · ")}>
                {t.open ? "—" : [KIND[t.exit_kind] || t.exit_kind, t.exit_comment].filter(Boolean).join(" · ")}</td>
              <td className="mono">{t.bars_held ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- properties ---------------------------------------------------------------------------------------------------

function Properties({ script, report }) {
  const s = report.settings || {};
  const r = report.calc_range || {};
  const range = script.test_range;
  const rows = [
    ["Test range", range ? `${range.mode === "custom" ? `Custom ${range.start} → ${range.end} UTC` : "Full available history"}` : "The bars on the chart"],
    ["Evaluated bars", `${r.bars ?? "—"}${script.truncated_bars ? ` (latest ${r.bars} of ${r.bars + script.truncated_bars})` : ""}`],
    ["Evaluated from → to", `${formatUtc(r.first_time)} → ${formatUtc(r.last_time)} UTC`],
    ["Fills (markers)", `${report.fills_reported ?? "—"} reported of ${report.fill_count ?? "—"}`],
    ["Initial capital", fmt(s.initial_capital)], ["Order size", `${s.default_qty_value} · ${s.default_qty_type}`],
    ["Pyramiding", s.pyramiding], ["Commission", `${s.commission_value} · ${s.commission_type}`], ["Slippage", s.slippage],
    ["Process orders on close", String(s.process_orders_on_close)], ["Pine version", s.version],
  ];
  return (
    <div className="pine-props">
      <table className="grid-table"><tbody>
        {rows.map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td className="mono">{String(v ?? "—")}</td></tr>)}
      </tbody></table>
      {script.inputs?.length > 0 && (
        <table className="grid-table"><thead><tr><th>Input</th><th>Value</th></tr></thead><tbody>
          {script.inputs.map((i) => <tr key={i.index}><td>{i.title}</td><td className="mono">
            {i.kind === "time" && Number.isFinite(Number(i.value)) ? `${new Date(Number(i.value)).toISOString().slice(0, 16).replace("T", " ")} UTC` : String(i.value)}</td></tr>)}
        </tbody></table>
      )}
    </div>
  );
}

// ---- tester -------------------------------------------------------------------------------------------------------

export function PineTester({ pine, payload, pending, precision, selectedKey, onSelectTrade, note, strategyId, onStrategy }) {
  const strategies = useMemo(() => pineStrategies(pine), [pine]);
  const [section, setSectionState] = useState(storedSection);
  const setSection = (key) => {
    setSectionState(key);
    try { window.sessionStorage.setItem(SECTION_STORAGE, key); } catch { /* storage unavailable */ }
  };
  const script = strategies.find((s) => s.id === strategyId) || strategies[0];
  if (!script) {
    return <div className="empty">No Pine strategy on the chart. Add a script declared with <b>strategy()</b> in the Pine Editor.</div>;
  }
  const report = script.strategy;
  return (
    <div className="pine-strategy st">
      <Header script={script} payload={payload} pending={pending} strategies={strategies} onStrategy={onStrategy} />
      <div className="subtabs st-tabs" role="tablist">
        {SECTIONS.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={section === key}
            className={`subtab ${section === key ? "is-active" : ""}`} onClick={() => setSection(key)}>
            {label}{key === "trades" && report ? <span className="count">{report.trades.length}</span> : null}
          </button>
        ))}
      </div>
      {script.error && <div className="tester-note">{script.error.message}</div>}
      {!script.enabled && <div className="tester-note">This strategy is hidden on the chart; show it to calculate.</div>}
      {note && <div className="tester-note">{note}</div>}
      {!report && !script.error && script.enabled && <div className="empty">The strategy has not run yet.</div>}
      {report && (
        <div className="subtab-body">
          {section === "overview" && <Overview report={report} />}
          {section === "performance" && <Performance report={report} />}
          {section === "trades" && <PineTradesTable report={report} precision={precision} selectedKey={selectedKey} onSelect={onSelectTrade} />}
          {section === "properties" && <Properties script={script} report={report} />}
        </div>
      )}
    </div>
  );
}

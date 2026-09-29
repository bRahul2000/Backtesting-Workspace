import React, { useMemo, useState } from "react";
import { formatUtc } from "../../format.js";

// Strategy Tester, source "Pine · TradingView emulator" (P3.1). Presentation only: trades, fills, equity and every
// metric come from Python's broker emulator for the Pine strategy on the chart - SIMULATION ONLY, never mixed with the
// Python audited engine's results.

const fmt = (value, digits = 2) => (value === null || value === undefined || Number.isNaN(value) ? "—"
  : Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const signed = (value, digits = 2) => (value === null || value === undefined ? "—" : `${value > 0 ? "+" : ""}${fmt(value, digits)}`);
const tone = (value) => (value > 0 ? "pos" : value < 0 ? "neg" : "");
const KIND = { trail: "Trailing stop", stop: "Stop loss", limit: "Take profit", close: "Market close",
  reversal: "Reversal", margin_call: "Margin call", market: "Market" };
const SECTIONS = [["overview", "Overview"], ["performance", "Performance"], ["trades", "Trades"], ["properties", "Properties"]];

export function pineStrategies(pine) {
  return (pine?.scripts || []).filter((s) => s.kind === "strategy");
}

function EquitySpark({ equity }) {
  if (!equity || equity.length < 2) return <div className="muted small-text">No equity history yet.</div>;
  const values = equity.map((p) => p[1]);
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const w = 520, h = 70;
  const d = equity.map((p, i) => `${i ? "L" : "M"}${(i / (equity.length - 1)) * w},${h - ((p[1] - lo) / span) * h}`).join(" ");
  return (
    <svg className="pine-equity" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" role="img" aria-label="Equity">
      <path d={d} fill="none" stroke="#2962ff" strokeWidth="1.5" />
    </svg>
  );
}

function MetricGrid({ rows }) {
  return (
    <div className="pine-metrics">
      {rows.map(([name, value, extra, cls, title]) => (
        <div key={name} className="pine-metric" title={title}><span className="muted">{name}</span>
          <span className={`mono ${cls || ""}`}>{value}{extra ? <span className="muted"> {extra}</span> : null}</span></div>
      ))}
    </div>
  );
}

// Only metrics P3.1 computes (outputs.strategy_metrics).
function Overview({ report }) {
  const m = report.metrics;
  return (
    <>
      <MetricGrid rows={[
        ["Net profit", signed(m.net_profit), `${signed(m.net_profit_percent)}%`, tone(m.net_profit)],
        ["Gross profit", fmt(m.gross_profit)], ["Gross loss", fmt(m.gross_loss)],
        ["Profit factor", fmt(m.profit_factor, 3)], ["Total trades", m.total_closed_trades],
        ["Winning trades", m.winning_trades], ["Losing trades", m.losing_trades],
        ["Win rate", m.percent_profitable === null ? "—" : `${fmt(m.percent_profitable)}%`],
        ["Average trade", signed(m.avg_trade), null, tone(m.avg_trade)],
        ["Average winner", fmt(m.avg_winning_trade)], ["Average loser", fmt(m.avg_losing_trade)],
        ["Largest winner", fmt(m.largest_winning_trade)], ["Largest loser", fmt(m.largest_losing_trade)],
        ["Max drawdown", fmt(m.max_drawdown)], ["Max run-up", fmt(m.max_runup)],
        ["Avg bars in trade", fmt(m.avg_bars_in_trade, 1), null, "", "exit bar − entry bar (engine convention)"],
      ]} />
      <EquitySpark equity={report.equity} />
    </>
  );
}

function Performance({ report }) {
  const m = report.metrics;
  return (
    <>
      <table className="grid-table pine-perf">
        <thead><tr><th /><th>All</th><th>Long</th><th>Short</th></tr></thead>
        <tbody>
          <tr><td>Closed trades</td><td className="mono">{m.total_closed_trades}</td><td className="mono">{m.long_trades}</td><td className="mono">{m.short_trades}</td></tr>
          <tr><td>Net profit</td><td className={`mono ${tone(m.net_profit)}`}>{signed(m.net_profit)}</td>
            <td className={`mono ${tone(m.long_net_profit)}`}>{signed(m.long_net_profit)}</td>
            <td className={`mono ${tone(m.short_net_profit)}`}>{signed(m.short_net_profit)}</td></tr>
        </tbody>
      </table>
      <MetricGrid rows={[
        ["Initial capital", fmt(m.initial_capital)], ["Ending equity", fmt(m.ending_equity)],
        ["Open P&L", signed(m.open_profit), null, tone(m.open_profit)], ["Open trades", m.open_trades],
        ["Even trades", m.even_trades], ["Commission paid", fmt(m.commission_paid)], ["Margin calls", m.margin_calls],
        ["Position size", fmt(m.position_size, 6)],
      ]} />
      <EquitySpark equity={report.equity} />
    </>
  );
}

export function PineTradesTable({ report, precision, selectedKey, onSelect }) {
  const rows = [...report.trades].reverse();
  return (
    <table className="grid-table pine-trades">
      <thead><tr><th>#</th><th>Direction</th><th>Entry time</th><th>Entry price</th><th>Exit time</th><th>Exit price</th>
        <th>Entry comment</th><th>Exit comment</th><th>Qty</th><th>P&amp;L</th>
        <th title="net P&L / entry value (engine convention)">P&amp;L %</th><th>Run-up</th><th>Drawdown</th>
        <th title="exit bar − entry bar">Bars</th></tr></thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.key} className={`${t.open ? "is-open" : ""} ${t.key === selectedKey ? "is-selected" : ""}`}
            onClick={() => onSelect && onSelect(t)} title="Show this trade on the chart">
            <td className="mono">{t.number}</td>
            <td className={t.direction > 0 ? "pos" : "neg"}>{t.direction > 0 ? "Long" : "Short"}</td>
            <td className="mono">{formatUtc(t.entry_time)}</td>
            <td className="mono">{fmt(t.entry_price, precision)}</td>
            <td className="mono">{t.open ? "Open" : formatUtc(t.exit_time)}</td>
            <td className="mono">{fmt(t.exit_price, precision)}</td>
            <td title={`ID ${t.entry_id}`}>{t.entry_comment || t.entry_id}</td>
            <td title={[KIND[t.exit_kind], t.exit_id ? `ID ${t.exit_id}` : ""].filter(Boolean).join(" · ")}>
              {t.open ? "—" : t.exit_comment || t.exit_id}</td>
            <td className="mono">{fmt(t.qty, 4)}</td>
            <td className={`mono ${tone(t.profit)}`}>{signed(t.profit)}</td>
            <td className={`mono ${tone(t.profit_percent)}`}>{t.profit_percent === null || t.profit_percent === undefined ? "—" : `${signed(t.profit_percent)}%`}</td>
            <td className="mono">{fmt(t.max_runup)}</td>
            <td className="mono">{fmt(t.max_drawdown)}</td>
            <td className="mono">{t.bars_held ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Properties({ script, report }) {
  const s = report.settings || {};
  const r = report.calc_range || {};
  const rows = [
    ["Calculated bars", `${r.bars ?? "—"}${script.truncated_bars ? ` (latest ${r.bars} of ${r.bars + script.truncated_bars})` : ""}`],
    ["Calculation range", `${formatUtc(r.first_time)} → ${formatUtc(r.last_time)} UTC`],
    ["Chart shows from", script.display_from ? `${formatUtc(script.display_from)} UTC (older bars load on demand)` : "the first calculated bar"],
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

export function PineTester({ pine, precision, selectedKey, onSelectTrade, note, strategyId, onStrategy }) {
  const strategies = useMemo(() => pineStrategies(pine), [pine]);
  const [section, setSection] = useState("overview");
  const script = strategies.find((s) => s.id === strategyId) || strategies[0];
  if (!script) {
    return <div className="empty">No Pine strategy on the chart. Add a script declared with <b>strategy()</b> in the Pine Editor.</div>;
  }
  const report = script.strategy;
  return (
    <div className="pine-strategy">
      <div className="subtabs">
        {SECTIONS.map(([key, label]) => (
          <button key={key} type="button" className={`subtab ${section === key ? "is-active" : ""}`} onClick={() => setSection(key)}>
            {label}{key === "trades" && report ? <span className="count">{report.trades.length}</span> : null}
          </button>
        ))}
        {strategies.length > 1 && (
          <select className="pine-strategy-select" value={script.id} onChange={(e) => onStrategy(e.target.value)} title="Strategy on the chart">
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.shorttitle || s.title} ({s.id})</option>)}
          </select>
        )}
        <span className="tested-on muted">{script.shorttitle || script.title} · simulated (broker emulator) · no broker orders</span>
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

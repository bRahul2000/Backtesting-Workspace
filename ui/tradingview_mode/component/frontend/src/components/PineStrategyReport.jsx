import React, { useMemo, useState } from "react";

// P3.1 Pine strategy report. Presentation only: trades, fills, equity and every metric come from Python's broker
// emulator (one ledger). SIMULATION ONLY - no order reaches a broker.

const fmt = (value, digits = 2) => (value === null || value === undefined || Number.isNaN(value) ? "—"
  : Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }));
const utc = (seconds) => {
  if (seconds === null || seconds === undefined) return "—";
  const d = new Date(seconds * 1000);
  const z = (n) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${z(d.getUTCMonth() + 1)}-${z(d.getUTCDate())} ${z(d.getUTCHours())}:${z(d.getUTCMinutes())}`;
};
const KIND = { trail: "Trailing stop", stop: "Stop loss", limit: "Take profit", close: "Market close",
  reversal: "Reversal", margin_call: "Margin call" };

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

function Metrics({ m }) {
  const rows = [
    ["Net profit", fmt(m.net_profit), `${fmt(m.net_profit_percent)}%`], ["Gross profit", fmt(m.gross_profit)],
    ["Gross loss", fmt(m.gross_loss)], ["Profit factor", fmt(m.profit_factor, 3)],
    ["Max drawdown", fmt(m.max_drawdown)], ["Closed trades", m.total_closed_trades],
    ["Winning / losing", `${m.winning_trades} / ${m.losing_trades}`], ["Percent profitable", `${fmt(m.percent_profitable)}%`],
    ["Avg trade", fmt(m.avg_trade)], ["Avg win / loss", `${fmt(m.avg_winning_trade)} / ${fmt(m.avg_losing_trade)}`],
    ["Largest win / loss", `${fmt(m.largest_winning_trade)} / ${fmt(m.largest_losing_trade)}`],
    ["Long / short trades", `${m.long_trades} / ${m.short_trades}`], ["Commission paid", fmt(m.commission_paid)],
    ["Open P&L", fmt(m.open_profit)], ["Initial capital", fmt(m.initial_capital)], ["Ending equity", fmt(m.ending_equity)],
  ];
  return (
    <div className="pine-metrics">
      {rows.map(([name, value, extra]) => (
        <div key={name} className="pine-metric"><span className="muted">{name}</span>
          <span className="mono">{value}{extra ? <span className="muted"> {extra}</span> : null}</span></div>
      ))}
    </div>
  );
}

function Trades({ trades, precision }) {
  const rows = [...trades].reverse();
  return (
    <table className="grid-table pine-trades">
      <thead><tr><th>#</th><th>Side</th><th>Entry</th><th>Entry time</th><th>Entry price</th><th>Exit</th>
        <th>Exit time</th><th>Exit price</th><th>Qty</th><th>Profit</th></tr></thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.key} className={t.open ? "is-open" : ""}>
            <td className="mono">{t.number}</td>
            <td>{t.direction > 0 ? "Long" : "Short"}</td>
            <td>{t.entry_id}</td>
            <td className="mono">{utc(t.entry_time)}</td>
            <td className="mono">{fmt(t.entry_price, precision)}</td>
            <td title={KIND[t.exit_kind] || ""}>{t.open ? "Open" : t.exit_id}</td>
            <td className="mono">{utc(t.exit_time)}</td>
            <td className="mono">{fmt(t.exit_price, precision)}</td>
            <td className="mono">{fmt(t.qty, 4)}</td>
            <td className={`mono ${t.profit > 0 ? "pos" : t.profit < 0 ? "neg" : ""}`}>{fmt(t.profit)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function PineStrategyReport({ pine, precision }) {
  const strategies = useMemo(() => (pine?.scripts || []).filter((s) => s.kind === "strategy"), [pine]);
  const [selected, setSelected] = useState(null);
  const script = strategies.find((s) => s.id === selected) || strategies[0];
  if (!script) {
    return <div className="empty">No Pine strategy on the chart. Add a script declared with <b>strategy()</b> in the Pine Editor.</div>;
  }
  const report = script.strategy;
  return (
    <div className="pine-strategy">
      <div className="tester-bar">
        {strategies.length > 1 && (
          <select value={script.id} onChange={(e) => setSelected(e.target.value)}>
            {strategies.map((s) => <option key={s.id} value={s.id}>{s.shorttitle || s.title}</option>)}
          </select>
        )}
        <span className="run-status muted">{script.shorttitle || script.title} · simulated (broker emulator) · no broker orders</span>
      </div>
      {script.error && <div className="tester-note">{script.error.message}</div>}
      {!report && !script.error && <div className="empty">The strategy has not run yet.</div>}
      {report && (
        <>
          <Metrics m={report.metrics} />
          <EquitySpark equity={report.equity} />
          <Trades trades={report.trades} precision={precision} />
        </>
      )}
    </div>
  );
}

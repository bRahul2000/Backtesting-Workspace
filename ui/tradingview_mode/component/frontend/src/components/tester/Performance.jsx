import React, { useState } from "react";
import { formatMetric, formatMoney, signClass } from "../../format.js";

function PeriodTable({ rows, label }) {
  if (!rows.length) return <div className="empty small">No {label.toLowerCase()} statistics.</div>;
  return (
    <table className="grid-table compact">
      <thead><tr><th>{label}</th><th className="num">Trades</th><th className="num">Win %</th><th className="num">PF</th><th className="num">Avg R</th><th className="num">P&amp;L</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.period}>
            <td className="mono">{row.period}</td>
            <td className="mono num">{row.trades}</td>
            <td className="mono num">{formatMetric(row.win_rate, 1)}</td>
            <td className="mono num">{formatMetric(row.profit_factor, 2)}</td>
            <td className={`mono num ${signClass(row.average_r)}`}>{formatMetric(row.average_r, 2)}</td>
            <td className={`mono num ${signClass(row.pnl)}`}>{formatMoney(row.pnl)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Every value comes from UniversalBacktestResult (winning/losing counts are
// derived in Python and labelled so).
export function Performance({ run }) {
  const [periods, setPeriods] = useState("yearly");
  if (!run) return <div className="empty">No backtest result yet.</div>;
  const s = run.summary;
  const { long, short } = run.directional;
  const rows = [
    ["Net P&L", formatMoney(s.pnl), formatMoney(long.pnl), formatMoney(short.pnl), [s.pnl, long.pnl, short.pnl]],
    ["Total trades", s.total_trades, long.trades, short.trades],
    ["Winning trades *", s.winning_trades, "—", "—"],
    ["Losing trades *", s.losing_trades, "—", "—"],
    ["Win rate", formatMetric(s.win_rate, 2, "%"), formatMetric(long.win_rate, 2, "%"), formatMetric(short.win_rate, 2, "%")],
    ["Profit factor", formatMetric(s.profit_factor, 3), formatMetric(long.profit_factor, 3), formatMetric(short.profit_factor, 3)],
    ["Average R", formatMetric(s.average_r, 3), formatMetric(long.average_r, 3), formatMetric(short.average_r, 3), [s.average_r, long.average_r, short.average_r]],
    ["Max drawdown", formatMetric(s.max_drawdown_percent, 2, "%"), "—", "—"],
    ["Max losing streak", s.max_losing_streak, "—", "—"],
    ["Trades / month", formatMetric(s.trades_per_month, 2), "—", "—"],
    ["Entries (incl. open at end)", s.total_entries, "—", "—"],
  ];
  return (
    <div className="performance">
      <div className="perf-col">
        <table className="grid-table compact">
          <thead><tr><th>Metric</th><th className="num">All</th><th className="num">Long</th><th className="num">Short</th></tr></thead>
          <tbody>
            {rows.map(([label, all, lo, sh, signs]) => (
              <tr key={label}>
                <td>{label}</td>
                {[all, lo, sh].map((value, index) => (
                  <td key={index} className={`mono num ${signs ? signClass(signs[index]) : ""}`}>{value}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="footnote">* counted in Python from the result's trade log with the adapter's own ±1e-9 threshold.</div>
      </div>
      <div className="perf-col">
        <div className="segmented small">
          <button type="button" className={periods === "yearly" ? "is-active" : ""} onClick={() => setPeriods("yearly")}>Yearly</button>
          <button type="button" className={periods === "monthly" ? "is-active" : ""} onClick={() => setPeriods("monthly")}>Monthly</button>
        </div>
        <PeriodTable rows={run.periods[periods]} label={periods === "yearly" ? "Year" : "Month"} />
      </div>
    </div>
  );
}

import React, { useState } from "react";
import { formatMetric, formatMoney, signClass } from "../../format.js";
import { filterPeriods } from "../../tradeView.js";

// Columns are exactly the fields UniversalBacktestResult carries per period.
function PeriodTable({ rows, label }) {
  if (!rows.length) return <div className="empty small">No {label.toLowerCase()}s in this view.</div>;
  return (
    <table className="grid-table compact">
      <thead><tr><th>{label}</th><th className="num">Trades</th><th className="num">Win rate</th><th className="num">P&amp;L</th><th className="num">Avg R</th><th className="num">PF</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.period}>
            <td className="mono">{row.period}</td>
            <td className="mono num">{row.trades}</td>
            <td className="mono num">{formatMetric(row.win_rate, 1, "%")}</td>
            <td className={`mono num ${signClass(row.pnl)}`}>{formatMoney(row.pnl)}</td>
            <td className={`mono num ${signClass(row.average_r)}`}>{formatMetric(row.average_r, 3)}</td>
            <td className="mono num">{formatMetric(row.profit_factor, 2)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function LongShort({ run }) {
  const s = run.summary;
  const { long, short } = run.directional;
  const rows = [
    ["Trades", s.total_trades, long.trades, short.trades],
    ["Win rate", formatMetric(s.win_rate, 2, "%"), formatMetric(long.win_rate, 2, "%"), formatMetric(short.win_rate, 2, "%")],
    ["Net P&L", formatMoney(s.pnl), formatMoney(long.pnl), formatMoney(short.pnl), [s.pnl, long.pnl, short.pnl]],
    ["Average R", formatMetric(s.average_r, 3), formatMetric(long.average_r, 3), formatMetric(short.average_r, 3), [s.average_r, long.average_r, short.average_r]],
    ["Profit factor", formatMetric(s.profit_factor, 3), formatMetric(long.profit_factor, 3), formatMetric(short.profit_factor, 3)],
    ["Max drawdown", formatMetric(s.max_drawdown_percent, 2, "%"), "n/a", "n/a"],
  ];
  return (
    <table className="grid-table compact">
      <thead><tr><th /><th className="num">All</th><th className="num">Long</th><th className="num">Short</th></tr></thead>
      <tbody>
        {rows.map(([label, all, lo, sh, signs]) => (
          <tr key={label}>
            <td>{label}</td>
            {[all, lo, sh].map((value, i) => <td key={i} className={`mono num ${signs ? signClass(signs[i]) : ""}`}>{value}</td>)}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Streaks({ run }) {
  const d = run.python_derived;
  const rows = [
    ["Max losing streak", run.summary.max_losing_streak, "result"],
    ["Max winning streak", d.max_winning_streak, "Python-derived"],
    ["Winning trades", d.winning_trades, "Python-derived"],
    ["Losing trades", d.losing_trades, "Python-derived"],
    ["Trades / month", formatMetric(run.summary.trades_per_month, 2), "result"],
    ["Entries (incl. open at end)", run.summary.total_entries, "result"],
  ];
  return (
    <table className="grid-table compact">
      <tbody>
        {rows.map(([label, value, source]) => (
          <tr key={label}><td>{label}</td><td className="mono num">{value}</td><td className="muted source">{source}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

export function Performance({ run }) {
  const [periods, setPeriods] = useState("monthly");
  const [monthFilter, setMonthFilter] = useState("all");
  if (!run) return <div className="empty">No backtest result yet.</div>;
  const rows = periods === "yearly" ? run.periods.yearly : filterPeriods(run.periods.monthly, monthFilter);
  return (
    <div className="performance">
      <div className="perf-col">
        <div className="section-title">Long vs short</div>
        <LongShort run={run} />
        <div className="section-title spaced">Streaks &amp; counts</div>
        <Streaks run={run} />
        <div className="footnote">Python-derived: counted in Python from the result's trade log with the adapter's ±1e-9 thresholds; streaks never span data segments. Per-direction drawdown is not part of the result.</div>
      </div>
      <div className="perf-col">
        <div className="period-head">
          <div className="segmented small">
            <button type="button" className={periods === "monthly" ? "is-active" : ""} onClick={() => setPeriods("monthly")}>Monthly</button>
            <button type="button" className={periods === "yearly" ? "is-active" : ""} onClick={() => setPeriods("yearly")}>Yearly</button>
          </div>
          {periods === "monthly" && (
            <div className="segmented small">
              {[["all", "All"], ["winning", "Winning"], ["losing", "Losing"]].map(([key, label]) => (
                <button key={key} type="button" className={monthFilter === key ? "is-active" : ""} onClick={() => setMonthFilter(key)}>{label}</button>
              ))}
            </div>
          )}
          <span className="muted small-text">by entry month/year · per-period drawdown not in the result</span>
        </div>
        <div className="period-scroll">
          <PeriodTable rows={rows} label={periods === "yearly" ? "Year" : "Month"} />
        </div>
      </div>
    </div>
  );
}

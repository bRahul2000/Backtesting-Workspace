import React from "react";
import { sendEvent } from "../../events.js";
import { formatMetric, formatMoney, signClass } from "../../format.js";

// In-memory runs of this Streamlit session. Restoring shows the result Python
// already returned; nothing is executed again.
export function History({ tester }) {
  const rows = tester.history || [];
  if (!rows.length) return <div className="empty">No runs in this session yet.</div>;
  return (
    <div className="table-scroll">
      <table className="grid-table compact history-table">
        <thead>
          <tr><th>Run</th><th>Ledger</th><th>Strategy</th><th>Instrument</th><th>Dataset</th><th>Range</th>
            <th className="num">Trades</th><th className="num">Net P&amp;L</th><th className="num">Win rate</th><th /></tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const active = row.history_id === tester.active_history_id;
            return (
              <tr key={row.history_id} className={active ? "is-selected" : ""}>
                <td className="mono">{row.run_id}</td>
                <td><span className={`ledger-badge ${row.ledger_mode}`}>{row.ledger_mode}</span></td>
                <td className="nowrap">{row.strategy}</td>
                <td>{row.instrument}</td>
                <td className="muted nowrap">{row.dataset}</td>
                <td className="mono nowrap">{row.start} → {row.end}</td>
                <td className="mono num">{row.total_trades}</td>
                <td className={`mono num ${signClass(row.pnl)}`}>{formatMoney(row.pnl)}</td>
                <td className="mono num">{formatMetric(row.win_rate, 2, "%")}</td>
                <td>{active ? <span className="muted small-text">shown</span> : (
                  <button type="button" className="btn ghost small" onClick={() => sendEvent("restore_run", { history_id: row.history_id })}>Show</button>
                )}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="footnote">Session only (kept in memory, last 10 runs). Showing a run restores its returned result without re-running it.</div>
    </div>
  );
}

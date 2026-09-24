import React, { useEffect, useMemo, useState } from "react";
import { formatMetric, formatPrice, formatUtc, signClass } from "../../format.js";

const PAGE_SIZE = 50;

// Paginated list of Python trade records. Nothing here is calculated.
export function TradesTable({ run, precision, selectedId, onSelect }) {
  const trades = run?.trades || [];
  const [page, setPage] = useState(0);
  const [newestFirst, setNewestFirst] = useState(false);
  const ordered = useMemo(() => (newestFirst ? [...trades].reverse() : trades), [trades, newestFirst]);
  const pages = Math.max(1, Math.ceil(ordered.length / PAGE_SIZE));
  useEffect(() => { setPage(0); }, [run?.run_id]);
  const rows = ordered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  if (!run) return <div className="empty">No backtest result yet. Configure a strategy and press <b>Run backtest</b>.</div>;
  if (!trades.length) return <div className="empty">The backtest completed with no closed trades.</div>;
  const price = (value) => formatPrice(value, precision);
  return (
    <div className="trades-wrap">
      <div className="table-scroll">
        <table className="grid-table trades-table">
          <thead>
            <tr>
              <th>#</th><th>Side</th><th>Signal (UTC)</th><th>Entry (UTC)</th><th className="num">Entry</th>
              <th className="num">SL</th><th className="num">TP</th><th>Exit (UTC)</th><th className="num">Exit</th>
              <th>Reason</th><th className="num">Qty</th><th className="num">P&amp;L</th><th className="num">P&amp;L %</th>
              <th className="num">R</th><th className="num">Bars</th><th className="num">Comm. in</th>
              <th className="num">Comm. out</th><th>Setup</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.trade_id} className={`clickable ${t.trade_id === selectedId ? "is-selected" : ""}`}
                onClick={() => onSelect(t)} title="Show this trade on the chart">
                <td className="mono">{t.trade_id}</td>
                <td><span className={`side ${t.direction === "LONG" ? "long" : "short"}`}>{t.direction}</span></td>
                <td className="mono muted">{formatUtc(t.signal_time)}</td>
                <td className="mono">{formatUtc(t.entry_time)}</td>
                <td className="mono num">{price(t.entry_price)}</td>
                <td className="mono num">{price(t.stop_loss)}</td>
                <td className="mono num">{price(t.take_profit)}</td>
                <td className="mono">{formatUtc(t.exit_time)}</td>
                <td className="mono num">{price(t.exit_price)}</td>
                <td className="nowrap">{t.exit_reason}</td>
                <td className="mono num">{formatMetric(t.quantity, 4)}</td>
                <td className={`mono num ${signClass(t.pnl)}`}>{formatMetric(t.pnl, 2)}</td>
                <td className={`mono num ${signClass(t.pnl_percent)}`}>{formatMetric(t.pnl_percent, 2, "%")}</td>
                <td className={`mono num ${signClass(t.r_multiple)}`}>{formatMetric(t.r_multiple, 2)}</td>
                <td className="mono num">{t.bars_held}</td>
                <td className="mono num muted">{formatMetric(t.entry_commission, 2)}</td>
                <td className="mono num muted">{formatMetric(t.exit_commission, 2)}</td>
                <td className="muted nowrap setup">{t.setup_id || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <span className="muted">{trades.length.toLocaleString()} trades · UTC · click a row to show it on the chart</span>
        <div className="spacer" />
        <label className="check small"><input type="checkbox" checked={newestFirst} onChange={(e) => { setNewestFirst(e.target.checked); setPage(0); }} /><span>Newest first</span></label>
        <button type="button" className="btn ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹</button>
        <span className="mono">{page + 1} / {pages}</span>
        <button type="button" className="btn ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>›</button>
      </div>
    </div>
  );
}

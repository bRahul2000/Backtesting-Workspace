import React, { useEffect, useMemo, useState } from "react";
import { sendEvent } from "../../events.js";
import { formatMetric, formatPrice, formatUtc, signClass } from "../../format.js";
import { FILTERS, neighbours, pageOf, tradeView } from "../../tradeView.js";

const PAGE_SIZE = 50;
const FILTER_LABELS = { all: "All", long: "Long", short: "Short", winners: "Winners", losers: "Losers" };
const SORT_LABELS = { entry_time: "Entry time", exit_time: "Exit time", pnl: "P&L", r_multiple: "R multiple", bars_held: "Bars held" };

export const tradeLabel = (t) => (t.segment === null || t.segment === undefined ? `#${t.trade_id}` : `${t.segment}/${t.trade_id}`);

// Every value is copied from Python's trade row; only layout happens here.
function TradeDetails({ trade, precision, position, onPrevious, onNext }) {
  if (!trade) return <aside className="trade-details empty">Select a trade to see its details and show it on the chart.</aside>;
  const price = (v) => formatPrice(v, precision);
  const rows = [
    ["Trade", `${tradeLabel(trade)}${trade.segment ? ` (segment ${trade.segment}, id ${trade.trade_id})` : ""}`],
    ["Direction", trade.direction],
    ["Signal (UTC)", formatUtc(trade.signal_time)],
    ["Entry (UTC)", formatUtc(trade.entry_time)],
    ["Entry price", price(trade.entry_price)],
    ["Stop loss", price(trade.stop_loss)],
    ["Take profit", price(trade.take_profit)],
    ["Exit (UTC)", formatUtc(trade.exit_time)],
    ["Exit price", price(trade.exit_price)],
    ["Exit reason", trade.exit_reason],
    ["Quantity", formatMetric(trade.quantity, 6)],
    ["P&L", formatMetric(trade.pnl, 2), signClass(trade.pnl)],
    ["P&L %", formatMetric(trade.pnl_percent, 3, "%"), signClass(trade.pnl_percent)],
    ["R multiple", formatMetric(trade.r_multiple, 3), signClass(trade.r_multiple)],
    ["Bars held", trade.bars_held],
    ["Entry commission", formatMetric(trade.entry_commission, 4)],
    ["Exit commission", formatMetric(trade.exit_commission, 4)],
    ["Setup", trade.setup_id],
    ["Entry model", trade.entry_model],
  ].filter(([, value]) => value !== null && value !== undefined);
  return (
    <aside className="trade-details">
      <div className="details-head">
        <button type="button" className="btn ghost small" disabled={!onPrevious} onClick={onPrevious} title="Previous trade in this view">‹ Prev</button>
        <span className="mono">{position}</span>
        <button type="button" className="btn ghost small" disabled={!onNext} onClick={onNext} title="Next trade in this view">Next ›</button>
      </div>
      <div className="details-body">
        {rows.map(([label, value, cls]) => (
          <div key={label} className="kv"><span>{label}</span><span className={`mono ${cls || ""}`}>{value}</span></div>
        ))}
      </div>
    </aside>
  );
}

export function TradesWorkspace({ run, precision, selectedKey, onSelect }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState("entry_time");
  const [sortDir, setSortDir] = useState("asc");
  const [page, setPage] = useState(0);
  const trades = run?.trades || [];
  const view = useMemo(() => tradeView(trades, { filter, query, sortKey, sortDir }), [trades, filter, query, sortKey, sortDir]);
  const pages = Math.max(1, Math.ceil(view.length / PAGE_SIZE));
  useEffect(() => { setPage(0); }, [run?.run_id, run?.history_id, filter, query, sortKey, sortDir]);
  // Keep the selected trade's page in view when it is chosen via Prev/Next.
  useEffect(() => {
    const target = pageOf(view, selectedKey, PAGE_SIZE);
    if (target !== null) setPage(target);
  }, [selectedKey]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!run) return <div className="empty">No backtest result yet. Configure a strategy and press <b>Run backtest</b>.</div>;
  if (!trades.length) return <div className="empty">The backtest completed with no closed trades.</div>;
  const selected = trades[selectedKey] && trades[selectedKey].key === selectedKey ? trades[selectedKey] : null;
  const nav = neighbours(view, selectedKey);
  const rows = view.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const price = (value) => formatPrice(value, precision);
  const exportRun = (kind) => sendEvent("export_run", { history_id: run.history_id, kind });

  return (
    <div className="trades-ws">
      <div className="trades-main">
        <div className="trades-toolbar">
          <div className="segmented small">
            {FILTERS.map((key) => (
              <button key={key} type="button" className={filter === key ? "is-active" : ""} onClick={() => setFilter(key)}>{FILTER_LABELS[key]}</button>
            ))}
          </div>
          <input className="search mono" type="search" placeholder="Search id, setup, exit reason" value={query} onChange={(e) => setQuery(e.target.value)} />
          <select value={sortKey} onChange={(e) => setSortKey(e.target.value)} title="Sort by">
            {Object.entries(SORT_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select>
          <button type="button" className="btn ghost small" onClick={() => setSortDir(sortDir === "asc" ? "desc" : "asc")} title="Sort direction">{sortDir === "asc" ? "↑ Asc" : "↓ Desc"}</button>
          <div className="spacer" />
          <button type="button" className="btn ghost small" disabled={!run.history_id} onClick={() => exportRun("trades_csv")} title="Complete trade log, generated by Python">Export trades CSV</button>
          <button type="button" className="btn ghost small" disabled={!run.history_id} onClick={() => exportRun("summary_json")} title="Run metadata, fingerprints, properties and statistics, generated by Python">Export summary JSON</button>
        </div>
        <div className="table-scroll">
          <table className="grid-table trades-table">
            <thead>
              <tr>
                <th>Trade</th><th>Side</th><th>Entry (UTC)</th><th className="num">Entry</th><th className="num">SL</th>
                <th className="num">TP</th><th>Exit (UTC)</th><th className="num">Exit</th><th>Reason</th>
                <th className="num">P&amp;L</th><th className="num">R</th><th className="num">Bars</th><th>Setup</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.key} className={`clickable ${t.key === selectedKey ? "is-selected" : ""}`} onClick={() => onSelect(t)} title="Show this trade on the chart">
                  <td className="mono">{tradeLabel(t)}</td>
                  <td><span className={`side ${t.direction === "LONG" ? "long" : "short"}`}>{t.direction}</span></td>
                  <td className="mono">{formatUtc(t.entry_time)}</td>
                  <td className="mono num">{price(t.entry_price)}</td>
                  <td className="mono num">{price(t.stop_loss)}</td>
                  <td className="mono num">{price(t.take_profit)}</td>
                  <td className="mono">{formatUtc(t.exit_time)}</td>
                  <td className="mono num">{price(t.exit_price)}</td>
                  <td className="nowrap">{t.exit_reason}</td>
                  <td className={`mono num ${signClass(t.pnl)}`}>{formatMetric(t.pnl, 2)}</td>
                  <td className={`mono num ${signClass(t.r_multiple)}`}>{formatMetric(t.r_multiple, 2)}</td>
                  <td className="mono num">{t.bars_held}</td>
                  <td className="muted nowrap setup">{t.setup_id || "—"}</td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={13} className="empty-cell">No trades match this view.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="pager">
          <span className="muted">{view.length.toLocaleString()} of {trades.length.toLocaleString()} trades · UTC</span>
          <div className="spacer" />
          <button type="button" className="btn ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹</button>
          <span className="mono">{page + 1} / {pages}</span>
          <button type="button" className="btn ghost" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>›</button>
        </div>
      </div>
      <TradeDetails trade={selected} precision={precision}
        position={nav.index >= 0 ? `${nav.index + 1} / ${view.length}` : selected ? "not in view" : ""}
        onPrevious={nav.previous ? () => onSelect(nav.previous) : null}
        onNext={nav.next ? () => onSelect(nav.next) : null} />
    </div>
  );
}

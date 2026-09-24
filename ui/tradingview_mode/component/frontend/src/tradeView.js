// Presentation-only views over Python's trade rows: filter, search, sort and
// navigate. Every function returns a new array and never modifies the rows or
// the payload; no trade value is computed here.

export const FILTERS = ["all", "long", "short", "winners", "losers"];
export const SORT_KEYS = ["entry_time", "exit_time", "pnl", "r_multiple", "bars_held"];

// Winners/losers use the sign of Python's own pnl with the adapter's ±1e-9 threshold.
const WIN = 1e-9;
const MATCH = {
  all: () => true,
  long: (t) => t.direction === "LONG",
  short: (t) => t.direction === "SHORT",
  winners: (t) => t.pnl > WIN,
  losers: (t) => t.pnl < -WIN,
};

export function filterTrades(trades, filter = "all", query = "") {
  const match = MATCH[filter] || MATCH.all;
  const needle = String(query || "").trim().toLowerCase();
  return trades.filter((trade) => match(trade) && (!needle || [
    String(trade.trade_id), trade.segment === null || trade.segment === undefined ? "" : `${trade.segment}/${trade.trade_id}`,
    trade.setup_id || "", trade.exit_reason || "",
  ].some((text) => text.toLowerCase().includes(needle))));
}

export function sortTrades(trades, key = "entry_time", direction = "asc") {
  const sign = direction === "desc" ? -1 : 1;
  const missing = (value) => value === null || value === undefined;
  // Rows without the value (trades still open in Replay) go last; ties keep
  // trade_log order (the unique key), so the view is deterministic.
  return [...trades].sort((a, b) => {
    if (missing(a[key]) || missing(b[key])) {
      return missing(a[key]) === missing(b[key]) ? a.key - b.key : (missing(a[key]) ? 1 : -1);
    }
    return a[key] === b[key] ? a.key - b.key : (a[key] < b[key] ? -sign : sign);
  });
}

export function tradeView(trades, { filter = "all", query = "", sortKey = "entry_time", sortDir = "asc" } = {}) {
  return sortTrades(filterTrades(trades, filter, query), sortKey, sortDir);
}

// Previous / next trade within the current view.
export function neighbours(view, selectedKey) {
  const index = view.findIndex((trade) => trade.key === selectedKey);
  return {
    index,
    previous: index > 0 ? view[index - 1] : null,
    next: index >= 0 && index < view.length - 1 ? view[index + 1] : null,
  };
}

export function pageOf(view, selectedKey, pageSize) {
  const index = view.findIndex((trade) => trade.key === selectedKey);
  return index < 0 ? null : Math.floor(index / pageSize);
}

// Monthly/yearly display filter on Python's per-period pnl.
export function filterPeriods(rows, mode = "all") {
  if (mode === "winning") return rows.filter((row) => typeof row.pnl === "number" && row.pnl > WIN);
  if (mode === "losing") return rows.filter((row) => typeof row.pnl === "number" && row.pnl < -WIN);
  return rows.slice();
}

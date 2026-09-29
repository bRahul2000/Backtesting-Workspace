// P3.1 Pine strategy fills -> chart markers. Presentation only: every fill (bar time, side, quantity, price, kind,
// comment) is computed by Python's broker emulator; nothing here simulates or decides a trade.
//
// Source of truth: the Pine strategy's FILLS. Every fill whose bar is loaded on the chart becomes exactly one marker
// (several fills on one bar stack; none is hidden). Fills on bars that are not loaded are counted, not drawn.
// Markers are compact (TradingView style): an arrow per fill, a short tag on exits (TP / SL / TS ...); the full
// comment, price and P&L are in the hover tooltip (fillsAt / describeFill).

const EXIT_KIND_TAGS = { limit: "TP", stop: "SL", trail: "TS", close: "X", reversal: "R", margin_call: "MC" };
const COMMENT_TAGS = { TP: "TP", FULL_SL: "SL", TRAIL_SL: "TS" };

export function isExit(fill) {
  return fill.kind === "exit" || fill.kind === "close" || fill.kind === "reversal" || fill.kind === "margin_call";
}

// Short marker tag: the exit comment's code when it is a known one, otherwise the exit kind's.
export function fillTag(fill) {
  if (!isExit(fill)) return "";
  if (fill.comment && COMMENT_TAGS[fill.comment]) return COMMENT_TAGS[fill.comment];
  return EXIT_KIND_TAGS[fill.exit_kind] || EXIT_KIND_TAGS[fill.kind] || "X";
}

// -> { markers, audit: { fills, entries, exits, inside, outside } }. `loadedTimes`: Set of the chart's bar times
// (null = all); `selected`: Set of fill keys drawn larger (the selected trade).
export function strategyMarkers(fills, loadedTimes = null, { colors = { buy: "#2962ff", sell: "#e91e63" },
  selected = null } = {}) {
  const markers = [];
  const audit = { fills: 0, entries: 0, exits: 0, inside: 0, outside: 0 };
  for (const fill of fills || []) {
    audit.fills += 1;
    if (isExit(fill)) audit.exits += 1; else audit.entries += 1;
    if (fill.time === null || fill.time === undefined || (loadedTimes && !loadedTimes.has(fill.time))) {
      audit.outside += 1;
      continue;
    }
    audit.inside += 1;
    const buy = fill.side > 0;
    markers.push({
      time: fill.time, position: buy ? "belowBar" : "aboveBar", shape: buy ? "arrowUp" : "arrowDown",
      color: buy ? colors.buy : colors.sell, text: fillTag(fill), id: fill.key,
      size: selected && selected.has(fill.key) ? 2 : 1,
    });
  }
  markers.sort((a, b) => a.time - b.time);
  return { markers, audit };
}

// Fills on one bar (hover tooltip), in fill order.
export function fillsAt(fills, time) {
  return (fills || []).filter((f) => f.time === time);
}

// The closed trade an exit fill belongs to (same exit bar, price and opposite side), if reported.
export function tradeOfExit(fill, trades) {
  return (trades || []).find((t) => !t.open && t.exit_time === fill.time && t.exit_price === fill.price
    && t.direction === -fill.side) || null;
}

// One tooltip line per fill: side, quantity, price, comment, and on an exit the closed trade's P&L.
export function describeFill(fill, trades, precision = 2) {
  const price = Number(fill.price).toLocaleString("en-US", { minimumFractionDigits: precision, maximumFractionDigits: precision });
  const head = `${fill.side > 0 ? "Buy" : "Sell"} ${Number(fill.qty.toFixed(6))} @ ${price}`;
  const label = fill.comment || fill.id;
  if (!isExit(fill)) return `${head} · ${label}`;
  const trade = tradeOfExit(fill, trades);
  if (!trade) return `${head} · ${label}`;
  const pct = trade.profit_percent === null || trade.profit_percent === undefined ? "" : ` (${trade.profit_percent.toFixed(2)}%)`;
  return `${head} · ${label} · P&L ${trade.profit >= 0 ? "+" : ""}${trade.profit.toFixed(2)}${pct}`;
}

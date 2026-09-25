// Pure chart-view decisions (no DOM, no chart): diffing Python's bars and
// indicator points into incremental updates, keeping the user's view, and UTC
// labels. Tested in tests/tradingview_mode/frontend/chartView.test.mjs.

const BAR_FIELDS = ["time", "open", "high", "low", "close", "volume"];

export const sameBar = (a, b) => BAR_FIELDS.every((f) => a[f] === b[f]);
export const samePoint = (a, b) => a.time === b.time && a.value === b.value;

function indexOfTime(items, time) {
  let low = 0;
  let high = items.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (items[mid].time === time) return mid;
    if (items[mid].time < time) low = mid + 1;
    else high = mid - 1;
  }
  return -1;
}

// How to go from `prev` to `next` (both sorted by time):
//   {kind: "none"}                        identical
//   {kind: "tail", updates}               only the last item changed and/or one was appended,
//                                         every earlier item identical -> series.update(...)
//   {kind: "replace", shift}              anything else -> series.setData(...); `shift` is how
//                                         many positions existing items moved (prepended history),
//                                         or null when the two share no item.
export function diffSeries(prev, next, same = sameBar) {
  const replace = () => {
    if (!prev.length || !next.length) return { kind: "replace", shift: null };
    const at = indexOfTime(next, prev[0].time);
    if (at >= 0) return { kind: "replace", shift: at };
    const back = indexOfTime(prev, next[0].time);
    return { kind: "replace", shift: back >= 0 ? -back : null };
  };
  const n = prev.length;
  if (!n || !next.length) return n === next.length ? { kind: "none" } : replace();
  let fixed;
  if (next.length === n) fixed = n - 1;
  else if (next.length === n + 1) fixed = n - 1;
  else return replace();
  if (next[0].time !== prev[0].time) return replace();
  for (let i = 0; i < fixed; i += 1) if (!same(prev[i], next[i])) return replace();
  if (next[n - 1].time !== prev[n - 1].time) return replace();
  const updates = [];
  if (!same(prev[n - 1], next[n - 1])) updates.push(next[n - 1]);
  if (next.length === n + 1) {
    if (next[n].time <= next[n - 1].time) return replace();
    updates.push(next[n]);
  }
  return updates.length ? { kind: "tail", updates } : { kind: "none" };
}

// Follow-latest: the newest bar is (nearly) in view on the right.
export const FOLLOW_TOLERANCE_BARS = 1;
export function isAtLatest(logical, count) {
  return !!logical && count > 0 && logical.to >= count - 1 - FOLLOW_TOLERANCE_BARS;
}

// After replacing the data, the same bars stay on screen at the same zoom.
export function shiftedRange(logical, shift) {
  if (!logical || shift === null || shift === undefined) return null;
  return { from: logical.from + shift, to: logical.to + shift };
}

// Ask Python for older history when the view reaches the left edge.
export const HISTORY_EDGE_BARS = 40;
export function wantsOlderHistory(logical, { more, firstTime, requestedFor }) {
  return !!logical && !!more && firstTime !== null && firstTime !== undefined
    && logical.from < HISTORY_EDGE_BARS && requestedFor !== firstTime;
}

// ---- UTC labels ------------------------------------------------------------------

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad = (n) => String(n).padStart(2, "0");

export function utcLabel(epochSeconds) {
  if (epochSeconds === null || epochSeconds === undefined) return "—";
  const d = new Date(epochSeconds * 1000);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`;
}

// Axis tick marks, always UTC. Lightweight Charts TickMarkType:
// 0 Year, 1 Month, 2 DayOfMonth, 3 Time, 4 TimeWithSeconds.
export function tickLabel(epochSeconds, tickMarkType) {
  const d = new Date(epochSeconds * 1000);
  switch (tickMarkType) {
    case 0: return String(d.getUTCFullYear());
    case 1: return `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
    case 2: return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
    case 4: return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
    default: return `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
  }
}

export { indexOfTime };

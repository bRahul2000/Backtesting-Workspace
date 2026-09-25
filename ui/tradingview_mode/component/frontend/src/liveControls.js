// Pure Live-mode helpers. Python owns the feed state; these only format it and
// decide when to ask Python for a refresh.

export const POLL_MS = 1000;

// Refresh only while Live is on and nothing is waiting for Python, so polls can
// never pile up behind a slow rerun.
export function pollAction(live, idle) {
  if (!live || !live.enabled || live.phase !== "streaming") return "stop";
  return idle ? "poll" : "wait";
}

export function statusClass(status) {
  return { LIVE: "live", STALE: "stale", CONNECTING: "connecting", DISCONNECTED: "disconnected", ERROR: "error" }[status] || "disconnected";
}

export function formatAge(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 0) return "0s";
  if (seconds < 90) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}

export function utcClock(epochSeconds) {
  if (epochSeconds === null || epochSeconds === undefined) return "—";
  return `${new Date(epochSeconds * 1000).toISOString().slice(11, 19)} UTC`;
}

// Broker-native quote formatting: exactly the symbol's digits.
export function quoteText(value, digits) {
  if (value === null || value === undefined || digits === null || digits === undefined) return "—";
  return Number(value).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

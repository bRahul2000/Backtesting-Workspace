// Explicit frontend -> Python events. Python validates every one.
//
// Streamlit keeps a component's last value across reruns and restarts an
// in-flight rerun when a new value arrives, so events are serialized: one is
// in flight until Python echoes its id back as `payload.ack`.
import { Streamlit } from "streamlit-component-lib";

const nonce = Math.random().toString(36).slice(2, 8);
let seq = 0;
let inFlight = null;
let hydrating = false;               // a payload's data files are still loading: nothing new is sent meanwhile
let inFlightTimer = null;
const queue = [];
const listeners = new Set();
// A backtest runs synchronously in one Streamlit rerun and can take minutes.
const TIMEOUT_MS = { run_backtest: 30 * 60 * 1000 };
const DEFAULT_TIMEOUT_MS = 60 * 1000;

function notify() {
  listeners.forEach((listener) => listener(inFlight));
}

function dispatch(event) {
  inFlight = event;
  clearTimeout(inFlightTimer);
  // Safety valve only: a slow first load (uncached aggregation) or a backtest
  // can take a while, and sending the next event early would make Streamlit
  // restart the run and drop this one. Unblock after the timeout and say so.
  const timeout = TIMEOUT_MS[event.type] ?? DEFAULT_TIMEOUT_MS;
  inFlightTimer = setTimeout(() => {
    window.dispatchEvent(new CustomEvent("tvterm:log", {
      detail: { level: "warning", message: `No acknowledgement from Python for ${event.type} (${event.id}) after ${timeout / 1000}s.` },
    }));
    acknowledge(event.id, true);
  }, timeout);
  Streamlit.setComponentValue(event);
  notify();
}

export function sendEvent(type, data = {}) {
  seq += 1;
  const event = { id: `${nonce}-${seq}`, type, data };
  if (inFlight) queue.push(event);
  else dispatch(event);
  return event.id;
}

export function acknowledge(ackId, timedOut = false) {
  if (!inFlight || (ackId !== inFlight.id && !timedOut)) return;
  clearTimeout(inFlightTimer);
  inFlight = null;
  const next = queue.shift();
  if (next) dispatch(next);
  else notify();
}

export function onPendingChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// True when no event is waiting for Python; replay playback only steps then,
// so it can never queue up more steps than the server has processed.
export function isIdle() {
  return inFlight === null && queue.length === 0 && !hydrating;
}

export function setHydrating(value) {
  hydrating = !!value;
}

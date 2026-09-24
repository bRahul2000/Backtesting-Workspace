// Explicit frontend -> Python events. Python validates every one.
//
// Streamlit keeps a component's last value across reruns and restarts an
// in-flight rerun when a new value arrives, so events are serialized: one is
// in flight until Python echoes its id back as `payload.ack`.
import { Streamlit } from "streamlit-component-lib";

const nonce = Math.random().toString(36).slice(2, 8);
let seq = 0;
let inFlight = null;
let inFlightTimer = null;
const queue = [];
const listeners = new Set();

function notify() {
  listeners.forEach((listener) => listener(inFlight));
}

function dispatch(event) {
  inFlight = event;
  clearTimeout(inFlightTimer);
  // Safety valve only: a slow first load (uncached aggregation) can take
  // seconds, and sending the next event early would make Streamlit restart
  // the run and drop this one. Unblock after 60s and say so.
  inFlightTimer = setTimeout(() => {
    window.dispatchEvent(new CustomEvent("tvterm:log", {
      detail: { level: "warning", message: `No acknowledgement from Python for ${event.type} (${event.id}) after 60s.` },
    }));
    acknowledge(event.id, true);
  }, 60000);
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

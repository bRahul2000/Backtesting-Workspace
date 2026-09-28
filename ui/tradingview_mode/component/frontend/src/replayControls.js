// Pure replay control logic. Python owns the replay state; these helpers only
// decide what the controls allow and when playback may request the next bar.

export const SPEEDS = [1, 2, 5, 10];

// 1x = one bar per second ... 10x = ten bars per second (requested rate; the
// real rate is bounded by the server round trip because a step is only sent
// once the previous one is acknowledged).
export function intervalMs(speed) {
  return Math.round(1000 / (SPEEDS.includes(speed) ? speed : 1));
}

export function controls(replay, busy = false) {
  if (!replay || !replay.enabled) {
    return { back: false, forward: false, play: false, pause: false, exit: false };
  }
  return {
    back: !busy && !replay.at_start && !replay.playing,
    forward: !busy && !replay.at_end && !replay.playing,
    play: !replay.playing && !replay.at_end,
    pause: replay.playing,
    exit: true,
  };
}

// Playback tick: step only while playing, not at the end, and when idle.
export function tickAction(replay, idle) {
  if (!replay || !replay.enabled || !replay.playing || replay.at_end) return "stop";
  return idle ? "step" : "wait";
}

export function utcParts(epochSeconds) {
  const iso = new Date(epochSeconds * 1000).toISOString();
  return { date: iso.slice(0, 10), time: iso.slice(11, 16) };
}

export function utcText(date, time) {
  return `${date}T${time || "00:00"}`;
}

export function statusText(replay) {
  if (!replay || !replay.enabled) return "";
  const { date, time } = utcParts(replay.cursor_timestamp);
  const position = `${(replay.cursor_index + 1).toLocaleString("en-US")} / ${replay.total_available_bars.toLocaleString("en-US")}`;
  return `REPLAY · ${date} ${time} UTC · ${position} · ${replay.speed}x · ${replay.playing ? "PLAYING" : "PAUSED"}`;
}

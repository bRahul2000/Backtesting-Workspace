import React, { useState } from "react";
import { sendEvent } from "../events.js";
import { SPEEDS, controls, statusText, utcParts, utcText } from "../replayControls.js";
import { Popover } from "./Popover.jsx";

// Floating replay controls. Every change is an explicit event; Python decides
// the revealed bars and sends back only history up to the cursor.
function JumpMenu({ replay, onClose }) {
  const initial = utcParts(replay.cursor_timestamp);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const send = (type, field) => { sendEvent(type, { [field]: utcText(date, time) }); onClose(); };
  return (
    <div className="form-menu">
      <div className="menu-heading">Go to (UTC)</div>
      <label className="field"><span>Date</span><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label className="field"><span>Time</span><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></label>
      <div className="menu-hint">Resolves to the bar opening at or before this time.</div>
      <div className="button-row">
        <button type="button" className="btn ghost" onClick={() => send("set_replay_start", "start")}>Restart here</button>
        <button type="button" className="btn primary" onClick={() => send("jump_replay", "to")}>Jump</button>
      </div>
    </div>
  );
}

export function ReplayBar({ replay, busy, onLatest }) {
  const [jumpOpen, setJumpOpen] = useState(false);
  if (!replay?.enabled) return null;
  const allow = controls(replay, busy);
  return (
    <div className="replay-bar" role="toolbar" aria-label="Replay controls">
      <span className={`replay-status mono ${replay.playing ? "is-playing" : ""}`}>{statusText(replay)}</span>
      <span className="replay-sep" />
      <div className="anchor">
        <button type="button" className="rp-btn" title="Jump / restart at a date and time (UTC)" onClick={() => setJumpOpen((v) => !v)}>⤓ Go to</button>
        <Popover open={jumpOpen} onClose={() => setJumpOpen(false)} width={240} align="up"><JumpMenu replay={replay} onClose={() => setJumpOpen(false)} /></Popover>
      </div>
      <button type="button" className="rp-btn" disabled={!allow.back} title="Previous bar" onClick={() => sendEvent("step_backward")}>◀︎</button>
      {replay.playing ? (
        <button type="button" className="rp-btn wide is-active" title="Pause" onClick={() => sendEvent("pause_replay")}>❚❚ Pause</button>
      ) : (
        <button type="button" className="rp-btn wide" disabled={!allow.play} title="Play" onClick={() => sendEvent("play_replay")}>▶︎ Play</button>
      )}
      <button type="button" className="rp-btn" disabled={!allow.forward} title="Next bar" onClick={() => sendEvent("step_forward")}>▶︎|</button>
      <select className="rp-speed" value={replay.speed} title="Playback speed (bars per second)"
        onChange={(e) => sendEvent("set_replay_speed", { speed: Number(e.target.value) })}>
        {SPEEDS.map((speed) => <option key={speed} value={speed}>{speed}x</option>)}
      </select>
      <button type="button" className="rp-btn" title="Go to latest revealed bar" onClick={onLatest}>⇥ Latest</button>
      <button type="button" className="rp-btn exit" title="Exit Replay and return to the full historical chart" onClick={() => sendEvent("exit_replay")}>✕ Exit</button>
    </div>
  );
}

import React from "react";
import { Icon } from "./icons.jsx";

// Drawing tools are declared but disabled until drawing persistence exists.
const DRAWING_TOOLS = [
  ["trend", "Trend line"],
  ["hline", "Horizontal line"],
  ["vline", "Vertical line"],
  ["rect", "Rectangle"],
  ["text", "Text"],
  ["measure", "Measure"],
];

export function LeftToolbar({ crosshairMode, setCrosshairMode, engineActions, drawingsEnabled, onCollapse }) {
  return (
    <nav className="lefttools" aria-label="Chart tools">
      <button type="button" className={`side-btn ${crosshairMode === "normal" ? "is-active" : ""}`}
        title="Crosshair" onClick={() => setCrosshairMode("normal")}><Icon name="crosshair" /></button>
      <button type="button" className={`side-btn ${crosshairMode === "magnet" ? "is-active" : ""}`}
        title="Magnet crosshair (snap to OHLC)" onClick={() => setCrosshairMode("magnet")}><Icon name="magnet" /></button>
      <div className="side-sep" />
      {DRAWING_TOOLS.map(([icon, label]) => (
        <button key={icon} type="button" className="side-btn" disabled={!drawingsEnabled}
          title={`${label} — drawing tools are not in this phase`}><Icon name={icon} /></button>
      ))}
      <div className="side-sep" />
      <button type="button" className="side-btn" title="Fit all bars" onClick={engineActions.fit}><Icon name="fit" /></button>
      <button type="button" className="side-btn" title="Go to latest bar" onClick={engineActions.latest}><Icon name="latest" /></button>
      <div className="side-fill" />
      <button type="button" className="side-btn" disabled={!drawingsEnabled} title="Delete drawings — not in this phase"><Icon name="trash" /></button>
      {onCollapse && <button type="button" className="side-btn tools-collapse" title="Hide chart tools" onClick={onCollapse}><Icon name="chevronLeft" size={14} /></button>}
    </nav>
  );
}

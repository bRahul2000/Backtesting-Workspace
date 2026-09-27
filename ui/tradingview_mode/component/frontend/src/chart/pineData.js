// Pure Pine render-protocol helpers (tested in Node; no chart library here).

export const TRANSPARENT = "rgba(0,0,0,0)";
const BREAK_STYLES = new Set(["linebr", "steplinebr", "areabr"]);

export function fade(css, alpha) {
  const m = /rgba\((\d+),(\d+),(\d+),([\d.]+)\)/.exec(css);
  return m ? `rgba(${m[1]},${m[2]},${m[3]},${Math.min(Number(m[4]), alpha)})` : css;
}

export function firstColor(output) {
  return output.data.find((p) => p.color)?.color || "#2962FF";
}

// Plot points -> Lightweight Charts data for the plot style. `linebr`-type
// styles break at na; the other styles connect across na (as Pine draws them).
// A point whose Pine color is na is drawn transparent.
export function seriesData(output) {
  const style = output.style || "line";
  const breaks = BREAK_STYLES.has(style);
  const area = style === "area" || style === "areabr";
  const out = [];
  for (const p of output.data) {
    if (p.value === null) {
      if (breaks) out.push({ time: p.time });
      continue;
    }
    const color = p.color || TRANSPARENT;
    out.push(area ? { time: p.time, value: p.value, lineColor: color, topColor: fade(color, 0.35), bottomColor: fade(color, 0.02) }
      : { time: p.time, value: p.value, color });
  }
  return out;
}

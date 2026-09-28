// Pine drawing objects (P2.3a): pure coordinate mapping and geometry (no chart imports; unit-tested).
// Python sends raw Pine coordinates: xloc.bar_index x values are bar indices of the script's bars (the chart's
// logical index is x + first_bar_index), xloc.bar_time x values are UNIX times in milliseconds.

// Chart logical index of a UNIX time (seconds). Bar times map exactly; a time between two bars is interpolated
// and a time outside the loaded bars is extrapolated with the nearest bar spacing - a documented presentation
// fallback (it does not model session gaps).
export function logicalFromTime(times, t) {
  const n = times.length;
  if (!n || t === null || t === undefined) return null;
  if (n === 1) return t === times[0] ? 0 : null;
  if (t <= times[0]) return (t - times[0]) / (times[1] - times[0]);
  if (t >= times[n - 1]) return n - 1 + (t - times[n - 1]) / (times[n - 1] - times[n - 2]);
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid;
  }
  return lo + (t - times[lo]) / (times[hi] - times[lo]);
}

// Chart logical index of a drawing x-coordinate.
export function logicalOf(x, xloc, firstBarIndex, times) {
  if (x === null || x === undefined) return null;
  if (xloc === "bar_time") return logicalFromTime(times, x / 1000);
  return x + (firstBarIndex || 0);
}

// A segment extended to the visible width (extend.left / right / both), as Pine's extend property does.
export function extendSegment(p1, p2, extend, width) {
  if (!extend || extend === "none" || p1.x === p2.x) return [p1, p2];
  const [a, b] = p1.x <= p2.x ? [p1, p2] : [p2, p1];
  const slope = (b.y - a.y) / (b.x - a.x);
  const at = (x) => ({ x, y: a.y + slope * (x - a.x) });
  const left = extend === "left" || extend === "both" ? at(Math.min(0, a.x)) : a;
  const right = extend === "right" || extend === "both" ? at(Math.max(width, b.x)) : b;
  return [left, right];
}

// Horizontal extension of a box's left/right edges.
export function extendBox(x1, x2, extend, width) {
  const left = Math.min(x1, x2), right = Math.max(x1, x2);
  return [extend === "left" || extend === "both" ? Math.min(0, left) : left,
          extend === "right" || extend === "both" ? Math.max(width, right) : right];
}

// The price a label is anchored at: its y for yloc.price, the bar's high / low for abovebar / belowbar.
export function labelPrice(label, bar) {
  if (label.yloc === "abovebar") return bar ? bar.high : null;
  if (label.yloc === "belowbar") return bar ? bar.low : null;
  return label.y;
}

// Line styles -> canvas dash patterns.
export function dashFor(style, width) {
  const w = Math.max(1, width || 1);
  if (style === "dotted") return [w, w * 2];
  if (style === "dashed") return [w * 4, w * 3];
  return [];
}

// P2.3b oracle-support tables-core: the geometry of a Pine table anchored at the pane's top-right corner. Columns and
// rows are sized by their largest cell (text width / font size plus padding); empty columns and rows take no space.
// `measure(text, px)` returns a text width in pixels; `sizePx` maps Pine text sizes to font pixels.
export function tableLayout(table, measure, paneWidth, sizePx, { pad = 4, margin = 8 } = {}) {
  const widths = new Array(table.columns).fill(0);
  const heights = new Array(table.rows).fill(0);
  const cells = (table.cells || []).map((cell) => {
    const px = sizePx[cell.text_size] ?? sizePx.normal;
    const lines = String(cell.text).split("\n");
    const w = Math.max(...lines.map((line) => measure(line, px))) + 2 * pad;
    const h = lines.length * px * 1.25 + 2 * pad;
    widths[cell.column] = Math.max(widths[cell.column], w);
    heights[cell.row] = Math.max(heights[cell.row], h);
    return { ...cell, px, lines };
  });
  const xs = widths.reduce((acc, w) => [...acc, acc[acc.length - 1] + w], [0]);
  const ys = heights.reduce((acc, h) => [...acc, acc[acc.length - 1] + h], [0]);
  const width = xs[xs.length - 1], height = ys[ys.length - 1];
  const left = paneWidth - margin - width, top = margin;
  return {
    x: left, y: top, width, height,
    cells: cells.map((cell) => ({ ...cell, x: left + xs[cell.column], y: top + ys[cell.row],
                                  w: widths[cell.column], h: heights[cell.row] })),
  };
}

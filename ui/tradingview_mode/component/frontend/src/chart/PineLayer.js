// Renders Pine script outputs (Python's render protocol) on the chart.
// Knows output KINDS (plot, shape, char, hline, fill, bgcolor, barcolor), never
// any particular indicator, and the P2.3a drawing objects (line, label, box,
// linefill) that Python keeps: presentation only, from their raw Pine coordinates.
// P2.3b: tables (oracle-support subset) drawn at the pane's top-right corner.
import { AreaSeries, HistogramSeries, LineSeries, LineStyle, LineType, createSeriesMarkers } from "lightweight-charts";
import { diffSeries, indexOfTime } from "./chartView.js";
import { dashFor, extendBox, extendSegment, labelPrice, logicalOf, tableLayout } from "./drawingGeometry.js";
import { firstColor, seriesData } from "./pineData.js";
import { fillsAt, strategyMarkers } from "./strategyMarkers.js";

const SIZE_PX = { tiny: 7, small: 10, normal: 14, large: 20, huge: 28, auto: 10 };
const LINE_STYLES = { solid: LineStyle.Solid, dotted: LineStyle.Dotted, dashed: LineStyle.Dashed };

const samePlotPoint = (a, b) => a.time === b.time && a.value === b.value && a.color === b.color;

// ---- primitives -------------------------------------------------------------------------

class Primitive {
  constructor(zOrder) {
    this.zOrder = zOrder;
    this.data = null;
    this.views = [{ zOrder: () => this.zOrder, renderer: () => this.renderer() }];
  }

  attached({ chart, series, requestUpdate }) { this.chart = chart; this.series = series; this.request = requestUpdate; }

  detached() { this.chart = null; this.series = null; this.request = null; }

  paneViews() { return this.views; }

  set(data) { this.data = data; this.request?.(); }
}

// bgcolor: a column behind each colored bar.
class BackgroundPrimitive extends Primitive {
  constructor() { super("bottom"); }

  renderer() {
    const self = this;
    return {
      draw() {},
      drawBackground(target) {
        if (!self.chart || !self.data) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          const scale = self.chart.timeScale();
          const spacing = scale.options().barSpacing;
          for (const p of self.data) {
            const x = scale.timeToCoordinate(p.time);
            if (x === null || x < -spacing || x > mediaSize.width + spacing) continue;
            context.fillStyle = p.color;
            context.fillRect(x - spacing / 2, 0, spacing, mediaSize.height);
          }
        });
      },
    };
  }
}

// fill(): a band between two plots (per-bar color) or two hlines.
class FillPrimitive extends Primitive {
  constructor() { super("bottom"); }

  renderer() {
    const self = this;
    return {
      draw(target) {
        const d = self.data;
        if (!self.chart || !self.series || !d) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          const y = (price) => self.series.priceToCoordinate(price);
          if (d.kind === "hline") {
            const y1 = y(d.a), y2 = y(d.b);
            if (y1 === null || y2 === null || !d.color) return;
            context.fillStyle = d.color;
            context.fillRect(0, Math.min(y1, y2), mediaSize.width, Math.abs(y2 - y1));
            return;
          }
          const scale = self.chart.timeScale();
          for (let i = 0; i + 1 < d.points.length; i += 1) {
            const p = d.points[i], q = d.points[i + 1];
            if (!p.color) continue;
            const x1 = scale.timeToCoordinate(p.time), x2 = scale.timeToCoordinate(q.time);
            if (x1 === null || x2 === null || x2 < 0 || x1 > mediaSize.width) continue;
            const a1 = y(p.a), a2 = y(q.a), b1 = y(p.b), b2 = y(q.b);
            if ([a1, a2, b1, b2].some((v) => v === null)) continue;
            context.fillStyle = p.color;
            context.beginPath();
            context.moveTo(x1, a1); context.lineTo(x2, a2); context.lineTo(x2, b2); context.lineTo(x1, b1);
            context.closePath();
            context.fill();
          }
        });
      },
    };
  }
}

// plotshape()/plotchar(): Pine's glyphs at abovebar/belowbar/top/bottom/absolute.
class ShapesPrimitive extends Primitive {
  constructor(stack) { super("top"); this.stack = stack; }

  renderer() {
    const self = this;
    return {
      draw(target) {
        const d = self.data;
        if (!self.chart || !self.series || !d) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          const scale = self.chart.timeScale();
          const size = SIZE_PX[d.size] || SIZE_PX.auto;
          const gap = 4 + self.stack * (size + 3);
          context.textAlign = "center";
          for (const p of d.points) {
            const x = scale.timeToCoordinate(p.time);
            if (x === null || x < -size || x > mediaSize.width + size) continue;
            let yy;
            let up;
            if (d.location === "top") { yy = gap + size / 2; up = false; }
            else if (d.location === "bottom") { yy = mediaSize.height - gap - size / 2; up = true; }
            else {
              const anchor = d.location === "absolute" ? p.price : d.location === "belowbar" ? p.low : p.high;
              const base = anchor === undefined || anchor === null ? null : self.series.priceToCoordinate(anchor);
              if (base === null) continue;
              up = d.location === "belowbar";
              yy = d.location === "absolute" ? base : up ? base + gap + size / 2 : base - gap - size / 2;
            }
            const color = p.color || "#2962FF";
            if (d.char) {
              context.fillStyle = color;
              context.font = `${size + 2}px sans-serif`;
              context.textBaseline = "middle";
              context.fillText(d.char, x, yy);
            } else {
              drawShape(context, d.style, x, yy, size, color, p.text, d.textcolor);
            }
            if (p.text && !(d.style === "labelup" || d.style === "labeldown")) {
              context.fillStyle = d.textcolor || color;
              context.font = "11px sans-serif";
              context.textBaseline = up ? "top" : "bottom";
              context.fillText(p.text, x, up ? yy + size / 2 + 2 : yy - size / 2 - 2);
            }
          }
        });
      },
    };
  }
}

function drawShape(ctx, style, x, y, size, color, text, textcolor) {
  const h = size / 2;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1.5, size / 7);
  ctx.beginPath();
  switch (style) {
    case "triangleup": ctx.moveTo(x, y - h); ctx.lineTo(x + h, y + h); ctx.lineTo(x - h, y + h); ctx.closePath(); ctx.fill(); return;
    case "triangledown": ctx.moveTo(x, y + h); ctx.lineTo(x + h, y - h); ctx.lineTo(x - h, y - h); ctx.closePath(); ctx.fill(); return;
    case "arrowup":
      ctx.moveTo(x, y - h); ctx.lineTo(x + h, y); ctx.lineTo(x + h / 3, y); ctx.lineTo(x + h / 3, y + h);
      ctx.lineTo(x - h / 3, y + h); ctx.lineTo(x - h / 3, y); ctx.lineTo(x - h, y); ctx.closePath(); ctx.fill(); return;
    case "arrowdown":
      ctx.moveTo(x, y + h); ctx.lineTo(x + h, y); ctx.lineTo(x + h / 3, y); ctx.lineTo(x + h / 3, y - h);
      ctx.lineTo(x - h / 3, y - h); ctx.lineTo(x - h / 3, y); ctx.lineTo(x - h, y); ctx.closePath(); ctx.fill(); return;
    case "circle": ctx.arc(x, y, h, 0, Math.PI * 2); ctx.fill(); return;
    case "square": ctx.fillRect(x - h, y - h, size, size); return;
    case "diamond": ctx.moveTo(x, y - h); ctx.lineTo(x + h, y); ctx.lineTo(x, y + h); ctx.lineTo(x - h, y); ctx.closePath(); ctx.fill(); return;
    case "cross": ctx.moveTo(x - h, y); ctx.lineTo(x + h, y); ctx.moveTo(x, y - h); ctx.lineTo(x, y + h); ctx.stroke(); return;
    case "flag":
      ctx.moveTo(x - h / 2, y + h); ctx.lineTo(x - h / 2, y - h); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(x - h / 2, y - h); ctx.lineTo(x + h, y - h / 2); ctx.lineTo(x - h / 2, y); ctx.closePath(); ctx.fill(); return;
    case "labelup":
    case "labeldown": {
      const label = text || "";
      ctx.font = "11px sans-serif";
      const w = Math.max(size, ctx.measureText(label).width + 8);
      const hh = 16;
      const top = style === "labelup" ? y - hh / 2 + 3 : y - hh / 2 - 3;
      ctx.beginPath();
      if (style === "labelup") { ctx.moveTo(x, top - 5); ctx.lineTo(x + 5, top); ctx.lineTo(x - 5, top); }
      else { ctx.moveTo(x, top + hh + 5); ctx.lineTo(x + 5, top + hh); ctx.lineTo(x - 5, top + hh); }
      ctx.closePath(); ctx.fill();
      ctx.fillRect(x - w / 2, top, w, hh);
      if (label) {
        ctx.fillStyle = textcolor || "#ffffff";
        ctx.textBaseline = "middle";
        ctx.fillText(label, x, top + hh / 2);
      }
      return;
    }
    default: // xcross (Pine's default shape)
      ctx.moveTo(x - h, y - h); ctx.lineTo(x + h, y + h); ctx.moveTo(x + h, y - h); ctx.lineTo(x - h, y + h); ctx.stroke();
  }
}

// Drawing objects of one script (P2.3a): linefills, boxes, lines, then labels.
class DrawingsPrimitive extends Primitive {
  constructor(engine) { super("top"); this.engine = engine; }

  renderer() {
    const self = this;
    return {
      draw(target) {
        const d = self.data;
        if (!self.chart || !self.series || !d) return;
        target.useMediaCoordinateSpace(({ context, mediaSize }) => {
          const scale = self.chart.timeScale();
          const bars = self.engine.bars || [];
          const times = bars.map((b) => b.time);
          const px = (x, xloc) => {
            const logical = logicalOf(x, xloc, d.first_bar_index, times);
            return logical === null ? null : scale.logicalToCoordinate(logical);
          };
          const py = (price) => (price === null || price === undefined ? null : self.series.priceToCoordinate(price));
          const lines = new Map();
          for (const l of d.lines || []) {
            const x1 = px(l.x1, l.xloc), x2 = px(l.x2, l.xloc), y1 = py(l.y1), y2 = py(l.y2);
            if ([x1, x2, y1, y2].some((v) => v === null)) continue;
            lines.set(l.key, extendSegment({ x: x1, y: y1 }, { x: x2, y: y2 }, l.extend, mediaSize.width));
          }
          for (const f of d.linefills || []) {
            const a = lines.get(f.line1), b = lines.get(f.line2);
            if (!a || !b || !f.color) continue;
            context.fillStyle = f.color;
            context.beginPath();
            context.moveTo(a[0].x, a[0].y); context.lineTo(a[1].x, a[1].y);
            context.lineTo(b[1].x, b[1].y); context.lineTo(b[0].x, b[0].y);
            context.closePath();
            context.fill();
          }
          for (const box of d.boxes || []) {
            const l = px(box.left, box.xloc), r = px(box.right, box.xloc), t = py(box.top), bt = py(box.bottom);
            if ([l, r, t, bt].some((v) => v === null)) continue;
            const [x1, x2] = extendBox(l, r, box.extend, mediaSize.width);
            const top = Math.min(t, bt), height = Math.abs(bt - t);
            if (box.bgcolor) { context.fillStyle = box.bgcolor; context.fillRect(x1, top, x2 - x1, height); }
            if (box.border_color && (box.border_width || 0) > 0) {
              context.strokeStyle = box.border_color;
              context.lineWidth = box.border_width;
              context.setLineDash(dashFor(box.border_style, box.border_width));
              context.strokeRect(x1, top, x2 - x1, height);
              context.setLineDash([]);
            }
            if (box.text) {
              const size = SIZE_PX[box.text_size] || SIZE_PX.normal;
              context.font = `${size}px sans-serif`;
              context.fillStyle = box.text_color || "#131722";
              context.textAlign = box.text_halign === "left" ? "left" : box.text_halign === "right" ? "right" : "center";
              context.textBaseline = box.text_valign === "top" ? "top" : box.text_valign === "bottom" ? "bottom" : "middle";
              const tx = context.textAlign === "left" ? x1 + 4 : context.textAlign === "right" ? x2 - 4 : (x1 + x2) / 2;
              const ty = context.textBaseline === "top" ? top + 4 : context.textBaseline === "bottom" ? top + height - 4 : top + height / 2;
              context.fillText(box.text, tx, ty);
            }
          }
          for (const l of d.lines || []) {
            const seg = lines.get(l.key);
            if (!seg || !l.color) continue;
            context.strokeStyle = l.color;
            context.lineWidth = Math.max(1, l.width || 1);
            context.setLineDash(dashFor(l.style, l.width));
            context.beginPath();
            context.moveTo(seg[0].x, seg[0].y); context.lineTo(seg[1].x, seg[1].y);
            context.stroke();
            context.setLineDash([]);
            if (l.style === "arrow_right" || l.style === "arrow_both") arrow(context, seg[0], seg[1], l.color);
            if (l.style === "arrow_left" || l.style === "arrow_both") arrow(context, seg[1], seg[0], l.color);
          }
          for (const label of d.labels || []) {
            const logical = logicalOf(label.x, label.xloc, d.first_bar_index, times);
            const x = logical === null ? null : scale.logicalToCoordinate(logical);
            const bar = logical !== null && Number.isInteger(logical) ? bars[logical] : null;
            const y = py(labelPrice(label, bar));
            if (x === null || y === null) continue;
            drawLabel(context, label, x, y);
          }
          for (const table of d.tables || []) drawTable(context, table, mediaSize.width);
        });
      },
    };
  }
}

// A Pine table (oracle-support subset): top-right of the pane, cells sized to their text.
function drawTable(ctx, table, paneWidth) {
  const measure = (text, px) => { ctx.font = `${px}px sans-serif`; return ctx.measureText(text).width; };
  const layout = tableLayout(table, measure, paneWidth, SIZE_PX);
  if (table.bgcolor) { ctx.fillStyle = table.bgcolor; ctx.fillRect(layout.x, layout.y, layout.width, layout.height); }
  for (const cell of layout.cells) {
    if (cell.bgcolor) { ctx.fillStyle = cell.bgcolor; ctx.fillRect(cell.x, cell.y, cell.w, cell.h); }
    if (table.border_color && table.border_width > 0) {
      ctx.strokeStyle = table.border_color;
      ctx.lineWidth = table.border_width;
      ctx.strokeRect(cell.x, cell.y, cell.w, cell.h);
    }
    ctx.font = `${cell.px}px sans-serif`;
    ctx.fillStyle = cell.text_color || "#000000";
    ctx.textBaseline = "middle";
    ctx.textAlign = cell.text_halign === "left" ? "left" : cell.text_halign === "right" ? "right" : "center";
    const tx = ctx.textAlign === "left" ? cell.x + 4 : ctx.textAlign === "right" ? cell.x + cell.w - 4 : cell.x + cell.w / 2;
    const lineHeight = cell.px * 1.25;
    const first = cell.y + cell.h / 2 - ((cell.lines.length - 1) * lineHeight) / 2;
    cell.lines.forEach((line, i) => ctx.fillText(line, tx, first + i * lineHeight));
  }
}

function arrow(ctx, from, to, color) {
  const angle = Math.atan2(to.y - from.y, to.x - from.x);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(to.x, to.y);
  ctx.lineTo(to.x - 8 * Math.cos(angle - 0.4), to.y - 8 * Math.sin(angle - 0.4));
  ctx.lineTo(to.x - 8 * Math.cos(angle + 0.4), to.y - 8 * Math.sin(angle + 0.4));
  ctx.closePath();
  ctx.fill();
}

// Pine label styles: glyph styles reuse the plotshape glyphs; label_* styles are text bubbles.
function drawLabel(ctx, label, x, y) {
  const style = label.style || "label_down";
  const size = SIZE_PX[label.size] || SIZE_PX.normal;
  const text = label.text || "";
  const color = label.color || null;
  if (style === "label_up" || style === "label_down") {
    if (color) drawShape(ctx, style === "label_up" ? "labelup" : "labeldown", x, y, size, color, text, label.textcolor);
    else if (text) { ctx.fillStyle = label.textcolor || "#131722"; ctx.textAlign = "center"; ctx.fillText(text, x, y); }
    return;
  }
  if (!style.startsWith("label_") && style !== "none" && style !== "text_outline") {
    if (color) drawShape(ctx, style, x, y, size, color);
    if (text) {
      ctx.fillStyle = label.textcolor || color || "#131722";
      ctx.font = "11px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "bottom";
      ctx.fillText(text, x, y - size / 2 - 2);
    }
    return;
  }
  ctx.font = "11px sans-serif";
  const w = ctx.measureText(text).width + 8, h = 16;
  const left = style.endsWith("left") ? x : style.endsWith("right") ? x - w : x - w / 2;
  const top = style.includes("upper") ? y - h : style.includes("lower") ? y : y - h / 2;
  if (color && style !== "none" && style !== "text_outline") { ctx.fillStyle = color; ctx.fillRect(left, top, w, h); }
  if (text) {
    ctx.fillStyle = label.textcolor || "#131722";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, left + w / 2, top + h / 2);
  }
}

// ---- layer --------------------------------------------------------------------------------

export class PineLayer {
  constructor(engine) {
    this.engine = engine;
    this.chart = engine.chart;
    this.sig = null;
    this.scripts = [];          // [{ id, overlay, pane, plots: Map, hosts, primitives: [], priceLines: [] }]
    this.barColors = new Map(); // time -> css color (barcolor)
    this.strategyMarkers = null; // P3.1: Pine strategy fills on the price candles (Python-computed)
    this.strategySig = null;
    this.strategyFills = [];     // every reported fill of the visible strategies (source of truth for markers)
    this.strategyTrades = [];
    this.strategyAudit = { fills: 0, entries: 0, exits: 0, inside: 0, outside: 0, rendered: 0 };
    this.selectedTrade = null;   // { key, entry_time, exit_time, entry_price, exit_price, fills: Set }
    this.tradeLines = [];
  }

  // One marker per fill on a loaded bar; the audit reconciles fills against markers. Rebuilt whenever the fills, the
  // loaded bars or the selected trade change.
  syncStrategyMarkers(scripts) {
    const strategies = scripts.filter((s) => s.enabled && !s.error && s.strategy);
    const fills = strategies.flatMap((s) => s.strategy.fills || []);
    this.strategyTrades = strategies.flatMap((s) => s.strategy.trades || []);
    const bars = this.engine.bars;
    const sig = `${fills.length}|${fills.at(-1)?.key ?? ""}|${fills.at(-1)?.time ?? ""}|${fills[0]?.time ?? ""}|`
      + `${bars.length}|${bars[0]?.time ?? ""}|${bars.at(-1)?.time ?? ""}|${this.selectedTrade?.key ?? ""}`;
    this.strategyFills = fills;
    if (sig === this.strategySig) return;
    this.strategySig = sig;
    if (!this.strategyMarkers) this.strategyMarkers = createSeriesMarkers(this.engine.candles, []);
    const { markers, audit } = strategyMarkers(fills, new Set(bars.map((b) => b.time)),
      { selected: this.selectedTrade?.fills || null });
    this.strategyMarkers.setMarkers(markers);
    this.strategyAudit = { ...audit, rendered: this.strategyMarkers.markers().length };
  }

  fillsAt(time) { return time === null || time === undefined ? [] : fillsAt(this.strategyFills, time); }

  // Highlight one Pine trade: its fills drawn larger and entry / exit price lines. null clears.
  selectTrade(trade) {
    this.tradeLines.forEach((line) => this.engine.candles.removePriceLine(line));
    this.tradeLines = [];
    if (!trade) {
      this.selectedTrade = null;
    } else {
      const keys = new Set(this.strategyFills.filter((f) => (f.time === trade.entry_time && f.price === trade.entry_price
        && f.side === trade.direction) || (!trade.open && f.time === trade.exit_time && f.price === trade.exit_price
        && f.side === -trade.direction)).map((f) => f.key));
      this.selectedTrade = { ...trade, fills: keys };
      const line = (price, title, color) => this.engine.candles.createPriceLine({ price, color, lineWidth: 1,
        lineStyle: LineStyle.Dashed, axisLabelVisible: true, title });
      this.tradeLines.push(line(trade.entry_price, `#${trade.number} entry`, "#4aa3ff"));
      if (!trade.open) this.tradeLines.push(line(trade.exit_price, `#${trade.number} exit`, trade.profit >= 0 ? "#22ab94" : "#f23645"));
    }
    this.strategySig = null;
    this.syncStrategyMarkers(this.lastScripts || []);
  }

  // Structure first (rebuild on change), then data (incremental).
  sync(scripts, basePane) {
    const visible = scripts.filter((s) => s.enabled && !s.error);
    let pane = basePane;
    const layout = visible.map((s) => ({ script: s, pane: s.overlay ? 0 : pane++ }));
    const sig = JSON.stringify(layout.map(({ script, pane: p }) => [script.id, p, script.outputs.map((o) =>
      [o.id, o.kind, o.style, o.linewidth, o.location, o.char, o.between])]));
    if (sig !== this.sig) {
      this.clear();
      this.sig = sig;
      this.scripts = layout.map(({ script, pane: p }) => this.build(script, p));
    }
    layout.forEach(({ script }, index) => this.update(this.scripts[index], script));
    this.lastScripts = visible;
    this.syncStrategyMarkers(visible);
    this.barColors = new Map();
    visible.forEach((s) => s.outputs.filter((o) => o.kind === "barcolor").forEach((o) => o.data.forEach((p) => this.barColors.set(p.time, p.color))));
  }

  clear() {
    for (const entry of this.scripts) {
      entry.primitives.forEach(([series, primitive]) => series.detachPrimitive(primitive));
      entry.priceLines.forEach(([series, line]) => series.removePriceLine(line));
      [...entry.plots.values()].forEach((plot) => this.chart.removeSeries(plot.api));
      if (entry.hostOwned) this.chart.removeSeries(entry.host);
    }
    this.scripts = [];
    this.sig = null;
  }

  build(script, pane) {
    const entry = { id: script.id, title: script.shorttitle || script.title, overlay: script.overlay, pane,
                    plots: new Map(), primitives: [], priceLines: [], hlines: new Map(), fills: new Map(), shapes: new Map(),
                    bg: null, host: null, hostOwned: false, drawings: null };
    let stack = 0;
    for (const output of script.outputs) {
      if (output.kind !== "plot") continue;
      const style = output.style || "line";
      const width = Math.max(1, Math.min(4, output.linewidth || 1));
      const common = { priceLineVisible: !!output.trackprice, lastValueVisible: true, crosshairMarkerVisible: false,
                       title: "", priceFormat: { type: "price", precision: this.engine.precision ?? 2, minMove: 10 ** -(this.engine.precision ?? 2) } };
      let api;
      if (style === "histogram" || style === "columns") {
        api = this.chart.addSeries(HistogramSeries, { ...common, base: output.histbase || 0, color: firstColor(output) }, pane);
      } else if (style === "area" || style === "areabr") {
        api = this.chart.addSeries(AreaSeries, { ...common, lineWidth: width, lineColor: firstColor(output) }, pane);
      } else {
        const markers = style === "circles" || style === "cross";
        api = this.chart.addSeries(LineSeries, {
          ...common, color: firstColor(output), lineWidth: width, lineVisible: !markers, pointMarkersVisible: markers,
          pointMarkersRadius: markers ? width + 1 : undefined,
          lineType: style.startsWith("stepline") ? LineType.WithSteps : LineType.Simple,
        }, pane);
      }
      entry.plots.set(output.id, { api, data: [], title: output.title || "Plot", raw: output });
    }
    const firstPlot = entry.plots.values().next().value;
    if (script.overlay) entry.host = this.engine.candles;
    else if (firstPlot) entry.host = firstPlot.api;
    else {
      const prices = script.outputs.filter((o) => o.kind === "hline" && o.price !== null).map((o) => o.price);
      entry.host = this.chart.addSeries(LineSeries, {
        lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
        autoscaleInfoProvider: () => (prices.length ? { priceRange: { minValue: Math.min(...prices), maxValue: Math.max(...prices) } } : null),
      }, pane);
      entry.hostOwned = true;
    }
    for (const output of script.outputs) {
      if (output.kind === "hline" && output.price !== null) {
        const line = entry.host.createPriceLine({ price: output.price, color: output.color || "#787B86",
          lineWidth: Math.max(1, Math.min(4, output.linewidth || 1)), lineStyle: LINE_STYLES[output.linestyle] ?? LineStyle.Solid,
          axisLabelVisible: false, title: "" });
        entry.priceLines.push([entry.host, line]);
        entry.hlines.set(output.id, output.price);
      } else if (output.kind === "fill") {
        const primitive = new FillPrimitive();
        const [a] = output.between;
        const anchor = entry.plots.get(a)?.api || entry.host;
        anchor.attachPrimitive(primitive);
        entry.primitives.push([anchor, primitive]);
        entry.fills.set(output.id, primitive);
      } else if (output.kind === "bgcolor") {
        const primitive = new BackgroundPrimitive();
        entry.host.attachPrimitive(primitive);
        entry.primitives.push([entry.host, primitive]);
        entry.bg = entry.bg || [];
        entry.bg.push([output.id, primitive]);
      } else if (output.kind === "shape" || output.kind === "char") {
        const primitive = new ShapesPrimitive(output.location === "abovebar" || output.location === "belowbar" ? stack++ : 0);
        entry.host.attachPrimitive(primitive);
        entry.primitives.push([entry.host, primitive]);
        entry.shapes.set(output.id, primitive);
      }
    }
    entry.drawings = new DrawingsPrimitive(this.engine);
    entry.host.attachPrimitive(entry.drawings);
    entry.primitives.push([entry.host, entry.drawings]);
    if (!script.overlay) {
      const panes = this.chart.panes();
      if (panes[pane]) panes[pane].setStretchFactor(1);
    }
    return entry;
  }

  update(entry, script) {
    const byId = new Map(script.outputs.map((o) => [o.id, o]));
    for (const [id, plot] of entry.plots) {
      const output = byId.get(id);
      const data = seriesData(output);
      const diff = diffSeries(plot.data, data, samePlotPoint);
      if (diff.kind === "tail") diff.updates.forEach((point) => plot.api.update(point));
      else if (diff.kind === "replace") plot.api.setData(data);
      plot.data = data;
      plot.raw = output;
    }
    for (const [id, primitive] of entry.fills) {
      const output = byId.get(id);
      const [a, b] = output.between;
      if (entry.hlines.has(a)) {
        const color = output.data.length ? output.data[output.data.length - 1].color : null;
        primitive.set({ kind: "hline", a: entry.hlines.get(a), b: entry.hlines.get(b), color });
      } else {
        const colors = new Map(output.data.map((p) => [p.time, p.color]));
        const pa = byId.get(a).data, pb = byId.get(b).data;
        const points = [];
        for (let i = 0; i < pa.length; i += 1) {
          const j = indexOfTime(pb, pa[i].time);
          if (j < 0 || pa[i].value === null || pb[j].value === null) continue;
          points.push({ time: pa[i].time, a: pa[i].value, b: pb[j].value, color: colors.get(pa[i].time) || null });
        }
        primitive.set({ kind: "plot", points });
      }
    }
    for (const [id, primitive] of entry.bg || []) primitive.set(byId.get(id).data);
    entry.drawings.set(script.drawings || null);
    for (const [id, primitive] of entry.shapes) {
      const output = byId.get(id);
      const reference = entry.overlay ? null : entry.plots.values().next().value;
      const points = output.data.map((p) => {
        if (entry.overlay) {
          const index = this.engine.findIndex(p.time);
          const bar = index >= 0 ? this.engine.bars[index] : null;
          return { ...p, high: bar?.high, low: bar?.low };
        }
        const value = reference ? reference.raw.data[indexOfTime(reference.raw.data, p.time)]?.value : null;
        return { ...p, high: value, low: value };
      });
      primitive.set({ points, location: output.location, size: output.size, style: output.style, char: output.char,
                      textcolor: output.textcolor });
    }
  }

  // Legend values at a bar time: overlay scripts join the main legend, others their pane.
  legend(time) {
    return this.scripts.map((entry) => ({
      id: entry.id, name: entry.title, pane: entry.pane,
      values: [...entry.plots.values()].map((plot) => {
        const data = plot.raw.data;
        const index = time === null ? data.length - 1 : indexOfTime(data, time);
        const point = index >= 0 ? data[index] : null;
        return { name: plot.title, color: point?.color || firstColor(plot.raw), value: point?.value ?? undefined };
      }),
    }));
  }
}

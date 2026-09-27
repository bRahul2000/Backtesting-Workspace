// Renders Pine script outputs (Python's render protocol) on the chart.
// Knows output KINDS (plot, shape, char, hline, fill, bgcolor, barcolor), never
// any particular indicator. Drawing objects (line/label/box/table) will be one
// more kind handled here.
import { AreaSeries, HistogramSeries, LineSeries, LineStyle, LineType } from "lightweight-charts";
import { diffSeries, indexOfTime } from "./chartView.js";
import { firstColor, seriesData } from "./pineData.js";

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

// ---- layer --------------------------------------------------------------------------------

export class PineLayer {
  constructor(engine) {
    this.engine = engine;
    this.chart = engine.chart;
    this.sig = null;
    this.scripts = [];          // [{ id, overlay, pane, plots: Map, hosts, primitives: [], priceLines: [] }]
    this.barColors = new Map(); // time -> css color (barcolor)
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
                    bg: null, host: null, hostOwned: false };
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

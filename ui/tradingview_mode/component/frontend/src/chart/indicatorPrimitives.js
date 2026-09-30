// Generic presentation primitives for Zoneflow indicators (ui/tradingview_mode/indicators.py). Independent of Pine:
// any Python indicator can emit fills between two outputs or two levels, and markers.
import { LineStyle } from "lightweight-charts";

export const LINE_STYLES = { solid: LineStyle.Solid, dashed: LineStyle.Dashed, dotted: LineStyle.Dotted };

// A band between two outputs (per time) or two constant levels, drawn under the series it is attached to.
export class BandFill {
  constructor(fill, seriesByName) {
    this.fill = fill;
    this.visible = true;
    this.setData(seriesByName);
    this.view = { zOrder: () => "bottom", renderer: () => ({ draw: (target) => this.draw(target) }) };
  }

  attached({ chart, series, requestUpdate }) { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; }
  detached() { this.chart = null; this.series = null; }
  paneViews() { return [this.view]; }
  updateAllViews() {}

  setVisible(visible) { this.visible = visible; this.requestUpdate?.(); }

  // seriesByName: name -> [{time, value}]
  setData(seriesByName) {
    const { upper, lower } = this.fill;
    this.constant = typeof upper === "number" && typeof lower === "number";
    if (this.constant) { this.points = null; return; }
    const at = (end) => (typeof end === "number" ? null : new Map((seriesByName[end] || []).map((p) => [p.time, p.value])));
    const a = at(upper), b = at(lower);
    const times = [...(a || b).keys()];
    this.points = times.map((time) => ({ time, a: a ? a.get(time) : upper, b: b ? b.get(time) : lower }))
      .filter((p) => Number.isFinite(p.a) && Number.isFinite(p.b));
    this.requestUpdate?.();
  }

  draw(target) {
    if (!this.visible || !this.chart || !this.series) return;
    target.useMediaCoordinateSpace(({ context, mediaSize }) => {
      const y = (price) => this.series.priceToCoordinate(price);
      context.fillStyle = this.fill.color;
      if (this.constant) {
        const y1 = y(this.fill.upper), y2 = y(this.fill.lower);
        if (y1 !== null && y2 !== null) context.fillRect(0, Math.min(y1, y2), mediaSize.width, Math.abs(y2 - y1));
        return;
      }
      const scale = this.chart.timeScale();
      context.beginPath();
      let open = false;
      const lowerPath = [];
      for (const p of this.points) {
        const x = scale.timeToCoordinate(p.time);
        const ya = y(p.a), yb = y(p.b);
        if (x === null || ya === null || yb === null) continue;
        if (!open) { context.moveTo(x, ya); open = true; } else context.lineTo(x, ya);
        lowerPath.push([x, yb]);
      }
      for (let i = lowerPath.length - 1; i >= 0; i -= 1) context.lineTo(lowerPath[i][0], lowerPath[i][1]);
      if (open) { context.closePath(); context.fill(); }
    });
  }
}

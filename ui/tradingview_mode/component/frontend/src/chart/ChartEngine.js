// Imperative Lightweight Charts wrapper. It only renders Python-provided data
// and diffs by revision so reruns never reset the user's zoom/pan.
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
} from "lightweight-charts";

export const COLORS = {
  bg: "#0b0e14",
  grid: "#161b24",
  border: "#232a36",
  text: "#8b95a7",
  up: "#22ab94",
  down: "#f23645",
  crosshair: "#5d6778",
};

const DEFAULT_VISIBLE_BARS = 180;
const RANGE_STORAGE = "tvterm:range:";

function storageGet(key) {
  try { return JSON.parse(window.sessionStorage.getItem(key)); } catch { return null; }
}

function storageSet(key, value) {
  try { window.sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

function seriesSignature(item, barsRev) {
  return `${barsRev}|${JSON.stringify(item.params)}|${item.series.map((s) => `${s.name}:${s.color}:${s.data.length}`).join(",")}`;
}

function histogramData(points) {
  return points.map((p) => ({ time: p.time, value: p.value, color: p.value >= 0 ? `${COLORS.up}99` : `${COLORS.down}99` }));
}

export class ChartEngine {
  constructor(container) {
    this.container = container;
    this.viewKey = null;
    this.barsRev = null;
    this.bars = [];
    this.overlays = new Map(); // id -> { sig, series: [{name, api, color}] , name }
    this.paneSig = null;
    this.panes = []; // [{ id, name, series: [{name, api, color}] }]
    this.crosshairListeners = new Set();
    this.saveTimer = null;

    this.chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: COLORS.bg },
        textColor: COLORS.text,
        fontSize: 11,
        fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        attributionLogo: false, // attribution is shown in the status bar instead
        panes: { separatorColor: COLORS.border, separatorHoverColor: "#2d3748", enableResize: true },
      },
      grid: { vertLines: { color: COLORS.grid }, horzLines: { color: COLORS.grid } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: COLORS.crosshair, labelBackgroundColor: "#2a3140" },
        horzLine: { color: COLORS.crosshair, labelBackgroundColor: "#2a3140" },
      },
      rightPriceScale: { borderColor: COLORS.border, scaleMargins: { top: 0.08, bottom: 0.2 } },
      timeScale: { borderColor: COLORS.border, timeVisible: true, secondsVisible: false, rightOffset: 6, barSpacing: 7 },
      localization: { dateFormat: "yyyy-MM-dd" },
    });

    this.candles = this.chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up, downColor: COLORS.down, borderVisible: false,
      wickUpColor: COLORS.up, wickDownColor: COLORS.down,
    }, 0);
    this.volume = this.chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false,
    }, 0);
    this.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    this.chart.subscribeCrosshairMove((param) => this.emitCrosshair(param));
    this.chart.timeScale().subscribeVisibleTimeRangeChange((range) => this.rememberRange(range));
    // Pane legends are positioned from the laid-out pane elements.
    this.resizeObserver = new ResizeObserver(() => this.emitSoon());
    this.resizeObserver.observe(container);
  }

  // ---- public -----------------------------------------------------------

  update(payload) {
    const newView = payload.view_key !== this.viewKey;
    const newBars = payload.bars_rev !== this.barsRev;
    const precision = payload.price_precision ?? 2;
    const keepRange = !newView && newBars ? this.chart.timeScale().getVisibleRange() : null;

    if (precision !== this.precision) {
      this.precision = precision;
      this.candles.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
    }
    if (newBars) {
      this.bars = payload.bars;
      this.candles.setData(payload.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
      this.volume.setData(payload.bars.map((b) => ({
        time: b.time, value: b.volume, color: b.close >= b.open ? `${COLORS.up}55` : `${COLORS.down}55`,
      })));
    }
    this.volume.applyOptions({ visible: !!payload.ui.show_volume });
    this.syncOverlays(payload.overlays, payload.bars_rev, precision);
    this.syncPanes(payload.panes, payload.bars_rev);

    this.viewKey = payload.view_key;
    this.barsRev = payload.bars_rev;
    if (newView) this.restoreOrDefaultRange();
    else if (newBars) this.applyRange(keepRange);
    this.emitSoon();
  }

  setCrosshairMode(mode) {
    this.chart.applyOptions({ crosshair: { mode: mode === "magnet" ? CrosshairMode.MagnetOHLC : CrosshairMode.Normal } });
  }

  fit() { this.chart.timeScale().fitContent(); }

  goToLatest() { this.showLatest(); }

  resetPriceScale() {
    this.chart.priceScale("right").applyOptions({ autoScale: true });
  }

  onCrosshair(listener) {
    this.crosshairListeners.add(listener);
    return () => this.crosshairListeners.delete(listener);
  }

  emitSoon() {
    cancelAnimationFrame(this.emitFrame);
    this.emitFrame = requestAnimationFrame(() => this.emitCrosshair({}));
  }

  destroy() {
    clearTimeout(this.saveTimer);
    cancelAnimationFrame(this.emitFrame);
    this.resizeObserver.disconnect();
    this.chart.remove();
  }

  // ---- visible range ----------------------------------------------------

  showLatest() {
    const n = this.bars.length;
    if (!n) return;
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - DEFAULT_VISIBLE_BARS), to: n + 6 });
  }

  applyRange(range) {
    const n = this.bars.length;
    if (!n) return;
    const first = this.bars[0].time;
    const last = this.bars[n - 1].time;
    if (range && range.to >= first && range.from <= last) {
      this.chart.timeScale().setVisibleRange({ from: Math.max(range.from, first), to: Math.min(range.to, last) });
    } else {
      this.showLatest();
    }
  }

  restoreOrDefaultRange() {
    this.applyRange(storageGet(RANGE_STORAGE + this.viewKey));
  }

  rememberRange(range) {
    if (!range || !this.viewKey) return;
    clearTimeout(this.saveTimer);
    const key = RANGE_STORAGE + this.viewKey;
    this.saveTimer = setTimeout(() => storageSet(key, { from: range.from, to: range.to }), 250);
  }

  // ---- indicators -------------------------------------------------------

  syncOverlays(overlays, barsRev, precision) {
    const wanted = new Set(overlays.map((o) => o.id));
    for (const [id, entry] of this.overlays) {
      if (!wanted.has(id)) {
        entry.series.forEach((s) => this.chart.removeSeries(s.api));
        this.overlays.delete(id);
      }
    }
    for (const item of overlays) {
      const sig = seriesSignature(item, barsRev);
      let entry = this.overlays.get(item.id);
      if (entry && entry.sig === sig) continue;
      if (entry) entry.series.forEach((s) => this.chart.removeSeries(s.api));
      entry = {
        sig, name: item.name, params: item.params,
        series: item.series.map((s) => {
          const api = this.chart.addSeries(LineSeries, {
            color: s.color, lineWidth: s.name === "value" || s.name === "basis" ? 2 : 1,
            lineStyle: s.name === "basis" ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
            priceFormat: { type: "price", precision, minMove: 10 ** -precision },
          }, 0);
          api.setData(s.data);
          return { name: s.name, api, color: s.color };
        }),
      };
      this.overlays.set(item.id, entry);
    }
  }

  syncPanes(panes, barsRev) {
    const sig = panes.map((p) => `${p.id}:${seriesSignature(p, barsRev)}`).join("|");
    if (sig === this.paneSig) return;
    this.paneSig = sig;
    // Rebuild lower panes. Empty panes are removed by the library automatically.
    this.panes.forEach((pane) => pane.series.forEach((s) => this.chart.removeSeries(s.api)));
    this.panes = panes.map((item, index) => {
      const paneIndex = index + 1;
      const series = item.series.map((s) => {
        const isHistogram = s.type === "histogram";
        const api = this.chart.addSeries(isHistogram ? HistogramSeries : LineSeries, isHistogram
          ? { priceLineVisible: false, lastValueVisible: false }
          : { color: s.color, lineWidth: s.name === "value" || s.name === "macd" ? 2 : 1, priceLineVisible: false, lastValueVisible: true, crosshairMarkerVisible: false },
        paneIndex);
        api.setData(isHistogram ? histogramData(s.data) : s.data);
        return { name: s.name, api, color: s.color };
      });
      (item.levels || []).forEach((level) => series[0]?.api.createPriceLine({
        price: level, color: "#3a4354", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: false,
      }));
      return { id: item.id, name: item.name, params: item.params, series };
    });
    const allPanes = this.chart.panes();
    allPanes.forEach((pane, index) => pane.setStretchFactor(index === 0 ? 3 : 1));
  }

  // ---- legend -----------------------------------------------------------

  emitCrosshair(param) {
    const n = this.bars.length;
    let bar = null;
    let time = null;
    if (param && param.time !== undefined && param.seriesData) {
      time = param.time;
      const data = param.seriesData.get(this.candles);
      const index = this.findIndex(time);
      if (data && index >= 0) bar = { ...this.bars[index], index };
    } else if (n) {
      bar = { ...this.bars[n - 1], index: n - 1 };
      time = bar.time;
    }
    const previous = bar && bar.index > 0 ? this.bars[bar.index - 1] : null;
    const valueAt = (api) => {
      if (param && param.seriesData && param.time !== undefined) return param.seriesData.get(api)?.value;
      const data = api.data();
      return data.length ? data[data.length - 1].value : undefined;
    };
    const containerTop = this.container.getBoundingClientRect().top;
    const legend = {
      time,
      bar,
      change: bar && previous ? bar.close - previous.close : null,
      changePct: bar && previous && previous.close ? ((bar.close - previous.close) / previous.close) * 100 : null,
      volume: bar ? bar.volume : null,
      overlays: [...this.overlays.entries()].map(([id, entry]) => ({
        id, name: entry.name, params: entry.params,
        values: entry.series.map((s) => ({ name: s.name, color: s.color, value: valueAt(s.api) })),
      })),
      panes: this.panes.map((pane, index) => {
        const element = this.chart.panes()[index + 1]?.getHTMLElement();
        return {
          id: pane.id, name: pane.name, params: pane.params,
          top: element ? element.getBoundingClientRect().top - containerTop : null,
          values: pane.series.map((s) => ({ name: s.name, color: s.color, value: valueAt(s.api) })),
        };
      }),
    };
    this.crosshairListeners.forEach((listener) => listener(legend));
  }

  findIndex(time) {
    let low = 0;
    let high = this.bars.length - 1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      const value = this.bars[mid].time;
      if (value === time) return mid;
      if (value < time) low = mid + 1;
      else high = mid - 1;
    }
    return -1;
  }
}

// Imperative Lightweight Charts wrapper. It only renders Python-provided data.
//
// View stability (live and replay): a payload is diffed against what is drawn.
// An unchanged history with a changed/appended last bar is applied with
// series.update(); anything else is setData() followed by restoring the exact
// logical range (shifted by any prepended history). Nothing here calls
// fitContent or re-applies price-scale options on a data update. The view only
// follows the newest bar while it is in view (follow mode); "Go to latest"
// re-enables following. A new market/source/timeframe (view_key) resets.
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
} from "lightweight-charts";
import {
  diffSeries, indexOfTime, isAtLatest, samePoint, shiftedRange, tickLabel, utcLabel, wantsOlderHistory,
} from "./chartView.js";
import { PineLayer } from "./PineLayer.js";

export const COLORS = {
  bg: "#0b0e14",
  grid: "#161b24",
  border: "#232a36",
  text: "#8b95a7",
  up: "#22ab94",
  down: "#f23645",
  crosshair: "#5d6778",
  entry: "#4aa3ff",
  stop: "#f23645",
  target: "#22ab94",
};

const DEFAULT_VISIBLE_BARS = 180;
const RANGE_STORAGE = "tvterm:range:";

function storageGet(key) {
  try { return JSON.parse(window.sessionStorage.getItem(key)); } catch { return null; }
}

function storageSet(key, value) {
  try { window.sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

// What an indicator *is* (not its values): only a change here rebuilds its series.
function structureSignature(item, precision) {
  return `${precision}|${JSON.stringify(item.params)}|${item.series.map((s) => `${s.name}:${s.type}:${s.color}`).join(",")}`;
}

const plainCandle = (b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });
const volumeBar = (b) => ({ time: b.time, value: b.volume, color: b.close >= b.open ? `${COLORS.up}55` : `${COLORS.down}55` });

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
    this.followListeners = new Set();
    this.saveTimer = null;
    this.follow = true;        // newest bar in view: live/replay updates may move the view with it
    this.hoverTime = null;     // bar time under the crosshair (null: none)
    this.historyRequestedFor = null;
    this.moreHistory = false;
    this.onNeedHistory = null; // set by the React panel (sends load_live_history)
    this.volumeVisible = null;
    this.stats = { updates: 0, setData: 0, incremental: 0 }; // for browser regression tests

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
      // All times are UTC epoch seconds; labels never use the browser time zone.
      timeScale: {
        borderColor: COLORS.border, timeVisible: true, secondsVisible: false, rightOffset: 6, barSpacing: 7,
        shiftVisibleRangeOnNewBar: true, tickMarkFormatter: (time, type) => tickLabel(time, type),
      },
      localization: { dateFormat: "yyyy-MM-dd", timeFormatter: (time) => utcLabel(time) },
    });

    this.candles = this.chart.addSeries(CandlestickSeries, {
      upColor: COLORS.up, downColor: COLORS.down, borderVisible: false,
      wickUpColor: COLORS.up, wickDownColor: COLORS.down,
    }, 0);
    this.volume = this.chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" }, priceScaleId: "volume", lastValueVisible: false, priceLineVisible: false,
    }, 0);
    this.volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    this.markers = createSeriesMarkers(this.candles, []);
    this.pine = new PineLayer(this);
    this.barColorSig = "";
    this.tradeSig = null;
    this.tradeLines = null; // lazily created entry / SL / TP segments

    this.chart.subscribeCrosshairMove((param) => {
      this.hoverTime = param && param.time !== undefined && param.point ? param.time : null;
      this.hoverPoint = param && param.point ? { x: param.point.x, y: param.point.y } : null;
      this.emitCrosshair();
    });
    this.chart.timeScale().subscribeVisibleTimeRangeChange((range) => this.rememberRange(range));
    this.chart.timeScale().subscribeVisibleLogicalRangeChange((logical) => this.onLogicalRange(logical));
    // Pane legends are positioned from the laid-out pane elements.
    this.resizeObserver = new ResizeObserver(() => this.emitSoon());
    this.resizeObserver.observe(container);
  }

  // ---- public -----------------------------------------------------------

  update(payload) {
    const timeScale = this.chart.timeScale();
    const newView = payload.view_key !== this.viewKey;
    const newBars = payload.bars_rev !== this.barsRev;
    const precision = payload.price_precision ?? 2;
    const streaming = !!payload.replay?.enabled || payload.live?.phase === "streaming";
    const before = newView ? null : timeScale.getVisibleLogicalRange();
    const beforeTime = newView ? null : timeScale.getVisibleRange();
    const wasFollowing = this.follow;
    const previousLast = this.bars.length ? this.bars[this.bars.length - 1].time : null;
    this.stats.updates += 1;

    if (precision !== this.precision) {
      this.precision = precision;
      this.candles.applyOptions({ priceFormat: { type: "price", precision, minMove: 10 ** -precision } });
    }
    let replaced = null; // {shift} when the data was replaced
    // Pine barcolor() recolors candles; a change on any earlier bar forces a reload.
    const barColors = barColorMap(payload.pine);
    const barColorSig = [...barColors].slice(0, -1).join("|");
    const recolor = barColorSig !== this.barColorSig;
    this.barColors = barColors;
    this.barColorSig = barColorSig;
    if (newBars || recolor) {
      let diff;
      if (newView) diff = { kind: "replace", shift: null };
      else {
        diff = newBars ? diffSeries(this.bars, payload.bars) : { kind: "none" };
        if (recolor) diff = { kind: "replace", shift: diff.kind === "replace" ? diff.shift : 0 };   // keep the view
      }
      if (diff.kind === "tail") this.stats.incremental += 1;
      else if (diff.kind === "replace") this.stats.setData += 1;
      if (diff.kind === "tail") {
        for (const b of diff.updates) {
          this.candles.update(this.candle(b));
          this.volume.update(volumeBar(b));
        }
      } else if (diff.kind === "replace") {
        this.candles.setData(payload.bars.map((b) => this.candle(b)));
        this.volume.setData(payload.bars.map(volumeBar));
        replaced = { shift: diff.shift };
      }
      this.bars = payload.bars;
    }
    if (this.volumeVisible !== !!payload.ui.show_volume) {
      this.volumeVisible = !!payload.ui.show_volume;
      this.volume.applyOptions({ visible: this.volumeVisible });
    }
    this.syncOverlays(payload.overlays, precision);
    if (this.panesSignature(payload.panes) !== this.paneSig) this.pine.clear();  // pane indices are about to move
    this.syncPanes(payload.panes);
    this.pine.sync(payload.pine?.scripts || [], 1 + this.panes.length);

    this.viewKey = payload.view_key;
    this.barsRev = payload.bars_rev;
    this.moreHistory = payload.live?.phase === "streaming" && !!payload.live.more_history;
    if (newView) {
      this.historyRequestedFor = null;
      if (streaming) this.showLatest();
      else this.restoreOrDefaultRange();
      this.setFollow(true);
    } else if (replaced) {
      // Keep exactly what the user was looking at, unless they were following the newest bar.
      const range = shiftedRange(before, replaced.shift);
      if (range) timeScale.setVisibleLogicalRange(range);
      else this.applyRange(beforeTime);
      // Following the newest bar and newer bars arrived (streaming, or a Historical data refresh): keep following.
      const grew = previousLast !== null && this.bars.length && this.bars[this.bars.length - 1].time > previousLast;
      if (wasFollowing && (streaming || grew)) timeScale.scrollToRealTime();
    }
    // (Incremental updates need nothing: an appended bar shifts the view only while the
    //  newest bar is visible - Lightweight Charts' shiftVisibleRangeOnNewBar.)
    this.maybeRequestHistory(timeScale.getVisibleLogicalRange());
    this.emitSoon();
  }

  // ---- Strategy Tester trades (all values from Python) -------------------

  // overlay: [{key, entry_bar, exit_bar}] (Python-placed chart bars)
  // tradesByKey: Map of Python trade objects by unique key; selectedKey: highlighted trade or null
  setTrades(overlay, tradesByKey, selectedKey) {
    const sig = `${this.barsRev}|${overlay.map((o) => o.key).join(",")}|${selectedKey ?? ""}|${tradesByKey.size}|${tradesByKey.values().next().value?.entry_time ?? ""}`;
    if (sig === this.tradeSig) return;
    this.tradeSig = sig;
    const markers = [];
    let selected = null;
    for (const item of overlay) {
      const trade = tradesByKey.get(item.key);
      if (!trade) continue;
      const isSelected = trade.key === selectedKey;
      const long = trade.direction === "LONG";
      const win = trade.pnl > 0;
      const size = isSelected ? 2 : 1;
      const label = trade.segment ? `${trade.segment}/${trade.trade_id}` : `#${trade.trade_id}`;
      markers.push({
        time: item.entry_bar, position: long ? "belowBar" : "aboveBar", shape: long ? "arrowUp" : "arrowDown",
        color: isSelected ? "#ffffff" : long ? COLORS.up : COLORS.down, size,
        text: `${long ? "L" : "S"}${isSelected ? ` ${label}` : ""}`,
      });
      markers.push({
        time: item.exit_bar, position: long ? "aboveBar" : "belowBar", shape: "circle",
        color: isSelected ? "#ffffff" : win ? COLORS.target : COLORS.stop, size,
        text: trade.exit_label,
      });
      if (isSelected) selected = { trade, item };
    }
    markers.sort((a, b) => a.time - b.time);
    this.markers.setMarkers(markers);
    this.drawSelectedTrade(selected);
  }

  drawSelectedTrade(selected) {
    if (!this.tradeLines) {
      const line = (color, title, style) => this.chart.addSeries(LineSeries, {
        color, lineWidth: 2, lineStyle: style, title, priceLineVisible: false, lastValueVisible: true,
        crosshairMarkerVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2,
      }, 0);
      this.tradeLines = {
        entry: line(COLORS.entry, "Entry", LineStyle.Solid),
        stop: line(COLORS.stop, "SL", LineStyle.Dashed),
        target: line(COLORS.target, "TP", LineStyle.Dashed),
      };
    }
    const precision = this.precision ?? 2;
    Object.values(this.tradeLines).forEach((series) => series.applyOptions({
      priceFormat: { type: "price", precision, minMove: 10 ** -precision },
    }));
    if (!selected) {
      Object.values(this.tradeLines).forEach((series) => series.setData([]));
      return;
    }
    // Limited segments from the entry bar to the exit bar at the exact trade prices.
    const { trade, item } = selected;
    const points = (value) => (item.entry_bar === item.exit_bar
      ? [{ time: item.entry_bar, value }]
      : [{ time: item.entry_bar, value }, { time: item.exit_bar, value }]);
    this.tradeLines.entry.setData(points(trade.entry_price));
    this.tradeLines.stop.setData(points(trade.stop_loss));
    this.tradeLines.target.setData(points(trade.take_profit));
  }

  // Centre the view on a trade that is placed on this chart.
  focusBars(entryBar, exitBar) {
    const entryIndex = this.findIndex(entryBar);
    const exitIndex = this.findIndex(exitBar);
    if (entryIndex < 0 || exitIndex < 0) return false;
    const span = Math.max(exitIndex - entryIndex, 1);
    const pad = Math.max(40, span);
    this.chart.timeScale().setVisibleLogicalRange({ from: entryIndex - pad, to: exitIndex + pad });
    return true;
  }

  setCrosshairMode(mode) {
    this.chart.applyOptions({ crosshair: { mode: mode === "magnet" ? CrosshairMode.MagnetOHLC : CrosshairMode.Normal } });
  }

  fit() { this.chart.timeScale().fitContent(); }

  goToLatest() { this.showLatest(); this.setFollow(true); }

  // Keep the current zoom (bar spacing) and bring the newest bar into view; follow it again.
  scrollToLatest() { this.chart.timeScale().scrollToRealTime(); this.setFollow(true); }

  onFollow(listener) {
    this.followListeners.add(listener);
    listener(this.follow);
    return () => this.followListeners.delete(listener);
  }

  setFollow(value) {
    if (value === this.follow) return;
    this.follow = value;
    this.followListeners.forEach((listener) => listener(value));
  }

  onLogicalRange(logical) {
    this.setFollow(isAtLatest(logical, this.bars.length));
    this.maybeRequestHistory(logical);
  }

  maybeRequestHistory(logical) {
    const firstTime = this.bars.length ? this.bars[0].time : null;
    if (!this.onNeedHistory || !wantsOlderHistory(logical, { more: this.moreHistory, firstTime, requestedFor: this.historyRequestedFor })) return;
    if (this.onNeedHistory()) this.historyRequestedFor = firstTime; // once per left edge
  }

  // Read-only state for browser regression tests.
  debugState() {
    const timeScale = this.chart.timeScale();
    return {
      logical: timeScale.getVisibleLogicalRange(), time: timeScale.getVisibleRange(),
      price: this.chart.priceScale("right").getVisibleRange(), barSpacing: timeScale.options().barSpacing,
      count: this.bars.length, first: this.bars[0]?.time ?? null, last: this.bars[this.bars.length - 1] ?? null,
      follow: this.follow, viewKey: this.viewKey, stats: { ...this.stats },
      strategyAudit: { ...this.pine.strategyAudit }, selectedPineTrade: this.pine.selectedTrade?.key ?? null,
    };
  }

  coordinateOf(time) { return this.chart.timeScale().timeToCoordinate(time); }

  // Pine strategy trade selection (Strategy Tester rows): highlight it; returns false if its entry is not loaded.
  selectPineTrade(trade) {
    this.pine.selectTrade(trade);
    return !trade || this.findIndex(trade.entry_time) >= 0;
  }

  resetPriceScale() {
    this.chart.priceScale("right").applyOptions({ autoScale: true });
  }

  onCrosshair(listener) {
    this.crosshairListeners.add(listener);
    return () => this.crosshairListeners.delete(listener);
  }

  emitSoon() {
    cancelAnimationFrame(this.emitFrame);
    this.emitFrame = requestAnimationFrame(() => this.emitCrosshair());
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
    if (!range || !this.viewKey || this.viewKey.endsWith("|replay")) return;
    clearTimeout(this.saveTimer);
    const key = RANGE_STORAGE + this.viewKey;
    this.saveTimer = setTimeout(() => storageSet(key, { from: range.from, to: range.to }), 250);
  }

  // ---- indicators -------------------------------------------------------

  // Indicator values change every tick; the series only change when the indicator does.
  applyPoints(target, data) {
    const toSeries = target.histogram ? histogramData : (points) => points;
    const diff = diffSeries(target.data, data, samePoint);
    if (diff.kind === "tail") toSeries(diff.updates).forEach((point) => target.api.update(point));
    else if (diff.kind === "replace") target.api.setData(toSeries(data));
    target.data = data;
  }

  syncOverlays(overlays, precision) {
    const wanted = new Set(overlays.map((o) => o.id));
    for (const [id, entry] of this.overlays) {
      if (!wanted.has(id)) {
        entry.series.forEach((s) => this.chart.removeSeries(s.api));
        this.overlays.delete(id);
      }
    }
    for (const item of overlays) {
      const sig = structureSignature(item, precision);
      let entry = this.overlays.get(item.id);
      if (entry && entry.sig === sig) {
        item.series.forEach((s, i) => this.applyPoints(entry.series[i], s.data));
        continue;
      }
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
          return { name: s.name, api, color: s.color, data: s.data, histogram: false };
        }),
      };
      this.overlays.set(item.id, entry);
    }
  }

  candle(b) {
    const color = this.barColors?.get(b.time);
    return color ? { ...plainCandle(b), color, borderColor: color, wickColor: color } : plainCandle(b);
  }

  panesSignature(panes) {
    return panes.map((p) => `${p.id}:${structureSignature(p, "")}:${(p.levels || []).join(",")}`).join("|");
  }

  syncPanes(panes) {
    const sig = this.panesSignature(panes);
    if (sig === this.paneSig) {
      // Same panes: update values in place (a rebuild would reset pane layout and scales).
      panes.forEach((item, index) => item.series.forEach((s, i) => this.applyPoints(this.panes[index].series[i], s.data)));
      return;
    }
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
        return { name: s.name, api, color: s.color, data: s.data, histogram: isHistogram };
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

  // Legend: the candle under the crosshair (by its bar time), else the newest candle.
  // Every value is looked up in the Python data by time.
  emitCrosshair() {
    const n = this.bars.length;
    let index = this.hoverTime !== null ? this.findIndex(this.hoverTime) : -1;
    const hovering = index >= 0;
    if (!hovering && n) index = n - 1;
    const bar = index >= 0 ? { ...this.bars[index], index } : null;
    const time = bar ? bar.time : null;
    const previous = bar && bar.index > 0 ? this.bars[bar.index - 1] : null;
    const valueAt = (series) => {
      if (time === null) return undefined;
      const at = indexOfTime(series.data, time);
      return at >= 0 ? series.data[at].value : undefined;
    };
    const containerTop = this.container.getBoundingClientRect().top;
    const pineLegend = this.pine.legend(hovering ? time : null);
    const pineTop = (pane) => {
      const element = this.chart.panes()[pane]?.getHTMLElement();
      return element ? element.getBoundingClientRect().top - containerTop : null;
    };
    const legend = {
      time,
      hovering,
      point: hovering ? this.hoverPoint : null,
      fills: hovering ? this.pine.fillsAt(time) : [],
      trades: this.pine.strategyTrades,
      bar,
      change: bar && previous ? bar.close - previous.close : null,
      changePct: bar && previous && previous.close ? ((bar.close - previous.close) / previous.close) * 100 : null,
      volume: bar ? bar.volume : null,
      overlays: [...this.overlays.entries()].map(([id, entry]) => ({
        id, name: entry.name, params: entry.params,
        values: entry.series.map((s) => ({ name: s.name, color: s.color, value: valueAt(s) })),
      })).concat(pineLegend.filter((p) => p.pane === 0).map((p) => ({ id: p.id, name: p.name, params: "", values: p.values }))),
      panes: this.panes.map((pane, i) => {
        const element = this.chart.panes()[i + 1]?.getHTMLElement();
        return {
          id: pane.id, name: pane.name, params: pane.params,
          top: element ? element.getBoundingClientRect().top - containerTop : null,
          values: pane.series.map((s) => ({ name: s.name, color: s.color, value: valueAt(s) })),
        };
      }).concat(pineLegend.filter((p) => p.pane > 0).map((p) => ({ id: p.id, name: p.name, params: "", top: pineTop(p.pane), values: p.values }))),
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

function barColorMap(pine) {
  const map = new Map();
  (pine?.scripts || []).filter((s) => s.enabled && !s.error).forEach((script) => script.outputs
    .filter((o) => o.kind === "barcolor").forEach((o) => o.data.forEach((p) => map.set(p.time, p.color))));
  return map;
}

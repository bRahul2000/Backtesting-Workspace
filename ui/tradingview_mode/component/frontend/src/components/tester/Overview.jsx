import React, { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart } from "lightweight-charts";
import { COLORS } from "../../chart/ChartEngine.js";
import { formatMetric, formatMoney, signClass } from "../../format.js";

// Equity (top pane) and drawdown (bottom pane) straight from result.equity_curve.
function CurvesChart({ curves }) {
  const host = useRef(null);
  const chart = useRef(null);
  useEffect(() => {
    const instance = createChart(host.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: COLORS.bg }, textColor: COLORS.text, fontSize: 10,
        attributionLogo: false, panes: { separatorColor: COLORS.border } },
      grid: { vertLines: { visible: false }, horzLines: { color: COLORS.grid } },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: { borderColor: COLORS.border, timeVisible: true, secondsVisible: false },
      localization: { dateFormat: "yyyy-MM-dd" },
    });
    const equity = instance.addSeries(AreaSeries, {
      lineColor: COLORS.entry, topColor: "rgba(74,163,255,0.28)", bottomColor: "rgba(74,163,255,0.02)",
      lineWidth: 2, priceLineVisible: false, title: "Equity",
    }, 0);
    const drawdown = instance.addSeries(AreaSeries, {
      lineColor: COLORS.down, topColor: "rgba(242,54,69,0.02)", bottomColor: "rgba(242,54,69,0.3)",
      lineWidth: 1, priceLineVisible: false, title: "DD %", invertFilledArea: true,
      priceFormat: { type: "custom", formatter: (v) => `${v.toFixed(2)}%` },
    }, 1);
    instance.panes()[0].setStretchFactor(2);
    chart.current = { instance, equity, drawdown };
    return () => { instance.remove(); chart.current = null; };
  }, []);
  useEffect(() => {
    if (!chart.current) return;
    chart.current.equity.setData(curves.equity);
    chart.current.drawdown.setData(curves.drawdown);
    chart.current.instance.timeScale().fitContent();
  }, [curves]);
  return <div className="curves-host" ref={host} />;
}

function Metric({ label, value, className = "", sub }) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value mono ${className}`}>{value}</span>
      {sub && <span className="metric-sub mono">{sub}</span>}
    </div>
  );
}

export function Overview({ run }) {
  if (!run) return <div className="empty">No backtest result yet. Configure a strategy and press <b>Run backtest</b>.</div>;
  const s = run.summary;
  return (
    <div className="overview">
      <div className="metric-row">
        <Metric label="Net P&L" value={formatMoney(s.pnl)} className={signClass(s.pnl)} sub={formatMetric(s.pnl_percent, 2, "%")} />
        <Metric label="Total trades" value={s.total_trades.toLocaleString()} sub={`${formatMetric(s.trades_per_month, 1)} / month`} />
        <Metric label="Win rate" value={formatMetric(s.win_rate, 2, "%")} sub={`${s.winning_trades} W · ${s.losing_trades} L`} />
        <Metric label="Profit factor" value={formatMetric(s.profit_factor, 3)} />
        <Metric label="Average R" value={formatMetric(s.average_r, 3)} className={signClass(s.average_r)} />
        <Metric label="Max drawdown" value={formatMetric(s.max_drawdown_percent, 2, "%")} className="down" sub={`losing streak ${s.max_losing_streak}`} />
      </div>
      <div className="curves">
        <CurvesChart curves={run.curves} />
        {run.curves.downsampled && <span className="curves-note">Curve drawn from {run.curves.equity.length} of {run.curves.points_total} points; metrics use the full result.</span>}
      </div>
    </div>
  );
}

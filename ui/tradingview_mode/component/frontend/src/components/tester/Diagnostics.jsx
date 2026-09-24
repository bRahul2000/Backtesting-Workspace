import React from "react";
import { formatMetric, formatUtc } from "../../format.js";

function Section({ title, children, open = false, count }) {
  return (
    <details className="diag-section" open={open}>
      <summary>{title}{count !== undefined && <span className="count">{count}</span>}</summary>
      <div className="diag-body">{children}</div>
    </details>
  );
}

const KV = ({ rows }) => rows.map(([label, value]) => (
  <div key={label} className="kv"><span>{label}</span><span className="mono">{value ?? "—"}</span></div>
));

// Only fields present in execution_diagnostics / execution_ambiguities, plus
// clearly labelled counts Python derived from the trade log.
export function Diagnostics({ run }) {
  if (!run) return <div className="empty">No backtest result yet.</div>;
  const d = run.diagnostics;
  const derived = run.python_derived;
  const events = Object.entries(d.order_events || {});
  return (
    <div className="diagnostics">
      <Section title="Order events" open>
        {events.length ? <KV rows={events.map(([status, count]) => [status, count])} /> : <div className="muted">No order events recorded.</div>}
        <div className="footnote">Counts from execution_diagnostics.order_events.</div>
      </Section>
      <Section title="Execution model & costs" open>
        <KV rows={[
          ["Execution adapter", d.execution_adapter],
          ["Continuous segments", d.segments],
          ["Spread setting (price)", formatMetric(d.spread_price, 2)],
          ["Effective spread (price)", formatMetric(d.effective_spread_price, 2)],
          ["Spread multiplier", formatMetric(d.spread_multiplier, 2)],
          ["Commission (%)", formatMetric(d.commission_percent, 4)],
          ["Slippage (%)", formatMetric(d.slippage_percent, 4)],
          ["Excursion model", d.excursion_model],
        ]} />
        <div className="footnote">Spread, slippage and total execution cost in money are not recorded by the engine, so they are not shown.</div>
      </Section>
      <Section title="From the trade log (Python-derived)">
        <KV rows={[
          ["Gap-through fills", derived.gap_through_fills],
          ["Leverage-capped trades", derived.leverage_capped_trades],
          ["Total entry commission", formatMetric(derived.total_entry_commission, 2)],
          ["Total exit commission", formatMetric(derived.total_exit_commission, 2)],
          ...Object.entries(derived.entry_models).map(([model, count]) => [`Entry model ${model}`, count]),
        ]} />
      </Section>
      <Section title="Same-bar ambiguities" count={d.execution_ambiguities}>
        {d.ambiguities.length ? (
          <table className="grid-table compact">
            <thead><tr><th>Time (UTC)</th><th>Type</th><th>Order</th><th>Levels</th><th>Resolution</th></tr></thead>
            <tbody>
              {d.ambiguities.map((a, i) => (
                <tr key={i}>
                  <td className="mono">{a.timestamp ? formatUtc(Date.parse(a.timestamp) / 1000) : "—"}</td>
                  <td>{a.ambiguity_type}</td>
                  <td className="mono muted">{a.order_id || a.trade_id || "—"}</td>
                  <td className="mono">{a.levels ? Object.entries(a.levels).map(([k, v]) => `${k} ${formatMetric(v, 2)}`).join(" · ") : "—"}</td>
                  <td>{a.resolution_policy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <div className="muted">No execution ambiguities.</div>}
        {d.execution_ambiguities > d.ambiguities.length && <div className="footnote">Showing first {d.ambiguities.length} of {d.execution_ambiguities}; the summary JSON export has all of them.</div>}
      </Section>
      <Section title="Validation exposure">
        <KV rows={[
          ["Forward runs for strategy (this ledger)", d.forward_runs_for_strategy],
          ["Forward validation warning", d.forward_validation_warning || "none"],
          ["Forward exposure warning", d.forward_exposure_warning || "none"],
        ]} />
      </Section>
    </div>
  );
}

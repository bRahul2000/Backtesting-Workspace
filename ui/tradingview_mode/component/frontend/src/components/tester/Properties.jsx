import React from "react";
import { formatUtc } from "../../format.js";

const SETTING_LABELS = {
  initial_capital: "Initial capital ($)",
  risk_mode: "Risk mode",
  risk_per_trade_percent: "Risk per trade (%)",
  fixed_risk_dollars: "Fixed risk ($)",
  risk_reward_ratio: "Reward : risk (R target)",
  spread: "Spread (price)",
  spread_multiplier: "Spread multiplier",
  commission_percent: "Commission (%)",
  slippage_percent: "Slippage (%)",
  leverage: "Leverage cap",
};

function Input({ value, onChange, disabled, type = "text" }) {
  return <input className="mono" type={type} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />;
}

function ParameterField({ spec, value, onChange, locked }) {
  const disabled = spec.frozen || locked;
  let control;
  if (spec.type === "boolean") {
    control = <input type="checkbox" checked={!!value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />;
  } else if (spec.choices.length) {
    control = (
      <select value={value} disabled={disabled} onChange={(e) => onChange(spec.choices.find((c) => String(c) === e.target.value))}>
        {spec.choices.map((choice) => <option key={String(choice)} value={String(choice)}>{String(choice)}</option>)}
      </select>
    );
  } else {
    control = <Input value={value} onChange={onChange} disabled={disabled} />;
  }
  const range = [spec.min !== null ? `≥ ${spec.min}` : null, spec.max !== null ? `≤ ${spec.max}` : null].filter(Boolean).join(" · ");
  return (
    <label className="prop-row" title={spec.description || undefined}>
      <span className="prop-label" title={spec.label}>{spec.label}</span>
      {control}
      <span className="prop-hint muted">{spec.frozen && <span className="lock">frozen</span>}{range}</span>
    </label>
  );
}

function Group({ title, rows }) {
  return (
    <div className="prop-group">
      <div className="group-title">{title}</div>
      {rows.map(([label, value]) => (
        <div key={label} className="kv"><span>{label}</span><span className="mono">{value ?? "—"}</span></div>
      ))}
    </div>
  );
}

// Exact configuration Python executed for the shown run.
function TestedConfiguration({ run, payload }) {
  const c = run.config;
  const params = Object.entries(c.strategy_parameters);
  return (
    <div className="prop-groups">
      <Group title="Strategy" rows={[
        ["Name", run.strategy.name], ["Id", run.strategy.strategy_id], ["Version", run.strategy.version],
        ["Status", `${run.strategy.status}${run.strategy.frozen ? " · read-only" : ""}`],
      ]} />
      <Group title="Market data" rows={[
        ["Dataset", run.dataset.label], ["Key", run.dataset.dataset_key], ["Provider", run.dataset.provider],
        ["Symbol / instrument", `${run.dataset.symbol} / ${c.instrument}`],
        ["Backtest timeframe", `${c.timeframe}${c.higher_timeframes.length ? ` (+ ${c.higher_timeframes.join(", ")} derived by the engine)` : ""}`],
        ["Chart timeframe", `${payload.timeframe} · ${payload.source.description}`],
        ["Range (UTC)", `${c.start.slice(0, 16)} → ${c.end.slice(0, 16)}`],
        ["Dataset role", c.dataset_role],
      ]} />
      <Group title="Broker / execution" rows={[
        ["Broker profile", c.broker_profile], ["Execution", c.execution_mode], ["Adapter", run.diagnostics.execution_adapter],
        ["Spread", c.spread_source === "BROKER_NATIVE_PER_BAR" ? `per-bar broker (median ${run.diagnostics.effective_spread_price})` : `constant ${c.spread}`],
        ["Spread multiplier", c.spread_multiplier], ["Commission / slippage", `${c.commission_percent}% / ${c.slippage_percent}%`],
      ]} />
      <Group title="Capital / risk" rows={[
        ["Initial capital", c.initial_capital],
        ["Risk", c.risk_mode === "PERCENT_EQUITY" ? `${c.risk_per_trade_percent}% of equity` : `$${c.fixed_risk_dollars} fixed`],
        ["Reward : risk", c.risk_reward_ratio], ["Leverage cap", c.leverage],
      ]} />
      <Group title="Parameters" rows={params.length ? params.map(([k, v]) => [k, String(v)]) : [["Overrides", "none (strategy defaults)"]]} />
      <Group title="Fingerprints" rows={Object.entries(run.fingerprints).map(([k, v]) => [k, v ? `${v.slice(0, 20)}…` : "—"])} />
      <Group title="Ledger" rows={[["Mode", run.ledger.label], ["File", run.ledger.path], ["Run id", run.run_id]]} />
      {run.open_positions.length > 0 && (
        <Group title="Open at dataset end" rows={run.open_positions.map((p) => [`${p.direction} ${p.trade_id}`, `${p.entry_price} @ ${formatUtc(p.entry_time)}`])} />
      )}
    </div>
  );
}

export function Properties({ tester, formApi, payload }) {
  const { form, strategy, dataset, options, setParameter, setSetting } = formApi;
  const run = tester.run;
  const locked = strategy && !strategy.overridable;
  return (
    <div className="properties">
      <section className="prop-col">
        <div className="section-title">Inputs · {strategy?.name || "—"}</div>
        {strategy && (
          <div className="muted small-text">
            {strategy.version} · {strategy.status} · {strategy.category} · runs on {strategy.supported_timeframes.join(", ")}
            {" "}(uses {strategy.required_timeframes.join(" + ")})
          </div>
        )}
        {locked && <div className="muted small-text">Frozen strategy: it exposes no parameter overrides, so inputs are read-only.</div>}
        {strategy?.parameters.length === 0 && <div className="empty small">No editable parameters.</div>}
        {strategy?.parameters.map((spec) => (
          <ParameterField key={spec.name} spec={spec} value={form.parameters[spec.name]} locked={locked}
            onChange={(value) => setParameter(spec.name, value)} />
        ))}
      </section>
      <section className="prop-col">
        <div className="section-title">Properties</div>
        {Object.keys(SETTING_LABELS).map((name) => {
          const perBar = name === "spread" && dataset?.per_bar_spread;
          return (
            <label key={name} className="prop-row">
              <span className="prop-label">{SETTING_LABELS[name]}</span>
              {name === "risk_mode" ? (
                <select value={form.settings.risk_mode} onChange={(e) => setSetting("risk_mode", e.target.value)}>
                  {options.risk_modes.map((mode) => <option key={mode} value={mode}>{mode}</option>)}
                </select>
              ) : (
                <Input value={perBar ? "per-bar" : form.settings[name]} disabled={perBar} onChange={(value) => setSetting(name, value)} />
              )}
              <span className="prop-hint muted">{perBar ? "broker spread from dataset" : `default ${options.defaults[name]}`}</span>
            </label>
          );
        })}
      </section>
      <section className="prop-col wide">
        <div className="section-title">Tested configuration {run ? `· ${run.run_id}` : ""}</div>
        {run ? <TestedConfiguration run={run} payload={payload} />
          : <div className="empty small">Run a backtest to see the exact configuration Python executed.</div>}
        {run?.diagnostics.forward_validation_warning && <div className="warn-text">{run.diagnostics.forward_validation_warning}</div>}
        {run?.diagnostics.forward_exposure_warning && <div className="warn-text">{run.diagnostics.forward_exposure_warning}</div>}
      </section>
    </div>
  );
}

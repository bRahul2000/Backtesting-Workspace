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

function Readout({ rows }) {
  return (
    <div className="readout">
      {rows.map(([label, value]) => (
        <div key={label} className="kv"><span>{label}</span><span className="mono">{value ?? "—"}</span></div>
      ))}
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
        {locked && <div className="muted small-text">This strategy exposes no constructor overrides; inputs are shown read-only.</div>}
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
      <section className="prop-col">
        <div className="section-title">Tested configuration {run ? `· ${run.run_id}` : ""}</div>
        {run ? (
          <Readout rows={[
            ["Strategy", `${run.strategy.name} (${run.strategy.version})`],
            ["Dataset", run.dataset.label],
            ["Market data provider", run.dataset.provider],
            ["Broker profile", run.config.broker_profile],
            ["Instrument", run.config.instrument],
            ["Backtest timeframe", `${run.config.timeframe}${run.config.higher_timeframes.length ? ` (+ ${run.config.higher_timeframes.join(", ")} derived by the engine)` : ""}`],
            ["Chart timeframe", `${payload.timeframe} · ${payload.source.description}`],
            ["Range (UTC)", `${run.config.start.slice(0, 16)} → ${run.config.end.slice(0, 16)}`],
            ["Dataset role", run.config.dataset_role],
            ["Execution", `${run.config.execution_mode} · ${run.diagnostics.execution_adapter}`],
            ["Spread", run.config.spread_source === "BROKER_NATIVE_PER_BAR" ? `per-bar broker (median ${run.diagnostics.effective_spread_price})` : `constant ${run.config.spread}`],
            ["Initial capital", run.config.initial_capital],
            ["Risk", run.config.risk_mode === "PERCENT_EQUITY" ? `${run.config.risk_per_trade_percent}% equity` : `$${run.config.fixed_risk_dollars} fixed`],
            ["Reward : risk", run.config.risk_reward_ratio],
            ["Commission / slippage", `${run.config.commission_percent}% / ${run.config.slippage_percent}%`],
            ["Leverage cap", run.config.leverage],
            ["Parameter overrides", Object.keys(run.config.strategy_parameters).length ? JSON.stringify(run.config.strategy_parameters) : "none (defaults)"],
            ["Strategy fingerprint", run.fingerprints.strategy.slice(0, 16)],
            ["Parameter fingerprint", run.fingerprints.parameter.slice(0, 16)],
            ["Dataset fingerprint", run.fingerprints.dataset.slice(0, 16)],
            ["Broker fingerprint", run.fingerprints.broker.slice(0, 16)],
            ["Ambiguous executions", run.diagnostics.execution_ambiguities],
            ["Open at end", run.open_positions.length ? run.open_positions.map((p) => `#${p.trade_id} ${p.direction} @ ${p.entry_price} (${formatUtc(p.entry_time)})`).join("; ") : "none"],
          ]} />
        ) : <div className="empty small">Run a backtest to see the exact configuration Python executed.</div>}
        {run?.diagnostics.forward_validation_warning && <div className="warn-text">{run.diagnostics.forward_validation_warning}</div>}
        {run?.diagnostics.forward_exposure_warning && <div className="warn-text">{run.diagnostics.forward_exposure_warning}</div>}
      </section>
    </div>
  );
}

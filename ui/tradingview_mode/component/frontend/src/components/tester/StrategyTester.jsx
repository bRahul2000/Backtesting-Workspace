import React, { useState } from "react";
import { sendEvent } from "../../events.js";
import { providerShort } from "../../format.js";
import { Diagnostics } from "./Diagnostics.jsx";
import { History } from "./History.jsx";
import { Overview } from "./Overview.jsx";
import { Performance } from "./Performance.jsx";
import { Properties } from "./Properties.jsx";
import { TradesWorkspace } from "./TradesTable.jsx";
import { useTesterForm } from "./useTesterForm.js";

const SUBTABS = [["overview", "Overview"], ["performance", "Performance"], ["trades", "Trades"],
  ["execution", "Execution"], ["properties", "Properties"], ["runs", "Runs"]];

function Status({ tester, running }) {
  if (running) return <span className="run-status running"><span className="spinner" />Running backtest…</span>;
  if (tester.status === "completed") {
    return (
      <span className="run-status ok" title={`${tester.run.run_id} · ${tester.run.ledger.path}`}>
        Completed · {tester.run.run_id} · {tester.run.duration_seconds}s
        <span className={`ledger-badge ${tester.run.ledger.mode}`}>{tester.run.ledger.mode}</span>
      </span>
    );
  }
  if (tester.status === "failed") return <span className="run-status failed" title={tester.error}>Failed</span>;
  return <span className="run-status muted">Not run</span>;
}

function LedgerControl({ form, options, setField }) {
  const research = form.ledger_mode === "research";
  const path = options.ledger_modes.find((m) => m.mode === form.ledger_mode)?.path;
  return (
    <div className={`ledger-control ${research ? "is-research" : ""}`} title={`Next run is recorded in ${path}`}>
      <span className="muted small-text">Ledger</span>
      <div className="segmented small">
        {options.ledger_modes.map((m) => (
          <button key={m.mode} type="button" className={form.ledger_mode === m.mode ? "is-active" : ""}
            onClick={() => setField("ledger_mode", m.mode)}>{m.mode === "scratch" ? "Scratch" : "Research"}</button>
        ))}
      </div>
    </div>
  );
}

export function StrategyTester({ payload, pending, selectedKey, onSelectTrade, focusNote }) {
  const tester = payload.tester;
  const formApi = useTesterForm(tester, payload.dataset_key);
  const { form, strategies, datasets, options, showRejected, setShowRejected, selectStrategy, selectDataset, setField, run } = formApi;
  const [tab, setTab] = useState("overview");
  const running = pending?.type === "run_backtest";
  const canRun = !running && form.strategy_id && form.dataset_key && form.start && form.end && form.ledger_mode;
  const researchPath = options.ledger_modes.find((m) => m.mode === "research")?.path;

  return (
    <div className="tester">
      <div className="tester-bar">
        <select className="tb-strategy" value={form.strategy_id} onChange={(e) => selectStrategy(e.target.value)} title="Strategy (from the strategy registry)">
          {strategies.map((s) => <option key={s.strategy_id} value={s.strategy_id}>{s.name}</option>)}
        </select>
        <label className="check small" title="Include strategies with status REJECTED"><input type="checkbox" checked={showRejected} onChange={(e) => setShowRejected(e.target.checked)} /><span>rejected</span></label>
        <select value={form.dataset_key} onChange={(e) => selectDataset(e.target.value)} title="Backtest dataset (runs natively; never derived from the chart timeframe)">
          {datasets.map((d) => <option key={d.dataset_key} value={d.dataset_key}>{d.symbol} · {providerShort(d.provider)} · {d.timeframe}</option>)}
        </select>
        <select value={form.broker_profile} onChange={(e) => setField("broker_profile", e.target.value)} title="Broker profile">
          {options.broker_profiles.map((b) => <option key={b.broker_id} value={b.broker_id}>{b.broker_id}</option>)}
        </select>
        <select value={form.dataset_role} onChange={(e) => setField("dataset_role", e.target.value)} title="Dataset role (recorded in the experiment ledger)">
          {options.dataset_roles.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <input type="date" className="mono" value={form.start} min={formApi.dataset?.min} max={formApi.dataset?.max} onChange={(e) => setField("start", e.target.value)} />
        <span className="muted">→</span>
        <input type="date" className="mono" value={form.end} min={formApi.dataset?.min} max={formApi.dataset?.max} onChange={(e) => setField("end", e.target.value)} />
        <LedgerControl form={form} options={options} setField={setField} />
        <button type="button" className="btn primary" disabled={!canRun} onClick={run}>{running ? "Running…" : "Run backtest"}</button>
        <Status tester={tester} running={running} />
        <div className="spacer" />
        {tester.run && !running && (
          <button type="button" className="btn ghost small" onClick={() => sendEvent("clear_backtest")} title="Clear the displayed result (session runs are kept)">Clear</button>
        )}
      </div>
      {form.ledger_mode === "research" && (
        <div className="tester-warn">Research Ledger selected: the next run is recorded in <span className="mono">{researchPath}</span> and counts toward forward-validation exposure.</div>
      )}
      {tester.status === "failed" && !running && <div className="tester-error">{tester.error}</div>}
      {focusNote && <div className="tester-note">{focusNote}</div>}
      <div className="subtabs">
        {SUBTABS.map(([key, label]) => (
          <button key={key} type="button" className={`subtab ${tab === key ? "is-active" : ""}`} onClick={() => setTab(key)}>
            {label}
            {key === "trades" && tester.run ? <span className="count">{tester.run.trades.length}</span> : null}
            {key === "runs" && tester.history?.length ? <span className="count">{tester.history.length}</span> : null}
          </button>
        ))}
        {tester.run && (
          <span className="tested-on muted">
            Tested: {tester.run.dataset.symbol} · {providerShort(tester.run.dataset.provider)} · {tester.run.config.timeframe} · {tester.run.config.broker_profile}
            {"  ·  "}Chart: {payload.symbol} · {providerShort(payload.provider)} · {payload.timeframe}
          </span>
        )}
      </div>
      <div className="subtab-body">
        {tab === "overview" && <Overview run={tester.run} />}
        {tab === "performance" && <Performance run={tester.run} />}
        {tab === "trades" && (
          <TradesWorkspace run={tester.run} precision={tester.run?.price_precision ?? payload.price_precision}
            selectedKey={selectedKey} onSelect={onSelectTrade} />
        )}
        {tab === "execution" && <Diagnostics run={tester.run} />}
        {tab === "properties" && <Properties tester={tester} formApi={formApi} payload={payload} />}
        {tab === "runs" && <History tester={tester} />}
      </div>
    </div>
  );
}

import { useEffect, useMemo, useState } from "react";
import { sendEvent } from "../../events.js";

// Draft of a run request. Everything here is a *request*: Python validates it,
// builds the authoritative BacktestConfig and may reject it.

function strategyDefaults(strategy) {
  return Object.fromEntries((strategy?.parameters || []).map((p) => [p.name, p.default]));
}

function datasetFor(options, strategy, preferredKey) {
  const keys = strategy?.datasets || [];
  const key = keys.includes(preferredKey) ? preferredKey : keys[0];
  return options.datasets.find((d) => d.dataset_key === key) || null;
}

function initialForm(options, lastRequest, chartDatasetKey) {
  if (lastRequest) {
    const strategy = options.strategies.find((s) => s.strategy_id === lastRequest.strategy_id);
    return {
      ...lastRequest,
      parameters: { ...strategyDefaults(strategy), ...(lastRequest.parameters || {}) },
      settings: { ...options.defaults, ...(lastRequest.settings || {}) },
      // The mode is always the one Python recorded for that request.
      ledger_mode: lastRequest.ledger_mode,
    };
  }
  const selectable = options.strategies.filter((s) => s.status !== "REJECTED" && s.datasets.length);
  const strategy = selectable.find((s) => s.datasets.includes(chartDatasetKey)) || selectable[0] || options.strategies[0];
  const dataset = datasetFor(options, strategy, chartDatasetKey);
  return {
    strategy_id: strategy?.strategy_id || "",
    dataset_key: dataset?.dataset_key || "",
    broker_profile: options.broker_profiles[0]?.broker_id || "",
    dataset_role: options.dataset_roles[0] || "",
    start: dataset?.default_start || "",
    end: dataset?.max || "",
    parameters: strategyDefaults(strategy),
    settings: { ...options.defaults },
    ledger_mode: options.default_ledger_mode,
  };
}

export function useTesterForm(tester, chartDatasetKey) {
  const options = tester.options;
  const [form, setForm] = useState(() => initialForm(options, tester.form, chartDatasetKey));
  const [showRejected, setShowRejected] = useState(() => {
    const current = options.strategies.find((s) => s.strategy_id === form.strategy_id);
    return current?.status === "REJECTED";
  });
  // Python's echo of the last submitted request wins after each run.
  useEffect(() => { if (tester.form) setForm(initialForm(options, tester.form, chartDatasetKey)); },
    [tester.form]); // eslint-disable-line react-hooks/exhaustive-deps

  const strategy = useMemo(() => options.strategies.find((s) => s.strategy_id === form.strategy_id) || null,
    [options.strategies, form.strategy_id]);
  const dataset = useMemo(() => options.datasets.find((d) => d.dataset_key === form.dataset_key) || null,
    [options.datasets, form.dataset_key]);
  const strategies = options.strategies.filter((s) => showRejected || s.status !== "REJECTED" || s.strategy_id === form.strategy_id);
  const datasets = options.datasets.filter((d) => strategy?.datasets.includes(d.dataset_key));

  const selectStrategy = (strategyId) => {
    const next = options.strategies.find((s) => s.strategy_id === strategyId);
    const nextDataset = datasetFor(options, next, form.dataset_key);
    setForm((prev) => ({
      ...prev, strategy_id: strategyId, parameters: strategyDefaults(next),
      dataset_key: nextDataset?.dataset_key || "",
      ...(nextDataset && nextDataset.dataset_key !== prev.dataset_key
        ? { start: nextDataset.default_start, end: nextDataset.max } : {}),
    }));
  };
  const selectDataset = (key) => {
    const next = options.datasets.find((d) => d.dataset_key === key);
    setForm((prev) => ({ ...prev, dataset_key: key, start: next?.default_start || "", end: next?.max || "" }));
  };
  const setField = (name, value) => setForm((prev) => ({ ...prev, [name]: value }));
  const setParameter = (name, value) => setForm((prev) => ({ ...prev, parameters: { ...prev.parameters, [name]: value } }));
  const setSetting = (name, value) => setForm((prev) => ({ ...prev, settings: { ...prev.settings, [name]: value } }));

  const run = () => {
    const settings = { ...form.settings };
    if (dataset?.per_bar_spread) delete settings.spread; // the dataset's own spread is used
    // Numbers typed as text are sent as numbers when they parse; anything else is
    // sent as-is so Python rejects it visibly instead of it being guessed here.
    const toValue = (value) => (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value)) ? Number(value) : value);
    sendEvent("run_backtest", {
      strategy_id: form.strategy_id, dataset_key: form.dataset_key, broker_profile: form.broker_profile,
      dataset_role: form.dataset_role, start: form.start, end: form.end, ledger_mode: form.ledger_mode,
      parameters: Object.fromEntries(Object.entries(form.parameters).map(([k, v]) => [k, toValue(v)])),
      settings: Object.fromEntries(Object.entries(settings).map(([k, v]) => [k, toValue(v)])),
    });
  };

  return {
    form, strategy, dataset, strategies, datasets, options, showRejected, setShowRejected,
    selectStrategy, selectDataset, setField, setParameter, setSetting, run,
  };
}

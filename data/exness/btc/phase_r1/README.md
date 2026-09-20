# Phase R1 — Exness BTCUSDm broker-native dataset

Mirrors the Gold Phase 2A layout (`data/exness/gold/phase2a/`).

```
raw/         immutable MT5 exports, never rewritten
  btcusd_mt5_spec.json          <- mt5/Export_BTCUSD_Spec.mq5
  btcusd_BTCUSDm_M15.csv        <- mt5/Export_BTCUSD_History.mq5
  btcusd_BTCUSDm_M15.csv.metadata.json
  btcusd_BTCUSDm_H1.csv         <- mt5/Export_BTCUSD_History.mq5
  btcusd_BTCUSDm_H1.csv.metadata.json
processed/   canonicalized output written by the pipeline
  btcusdm_M15.csv
  btcusdm_H1.csv
manifest.json
```

Build with:

```bash
python -m services.btc_broker_data
```

It prints the gate status and, only when all three raw exports exist, ingests,
validates, reconciles M15 against H1, fingerprints everything and writes
`manifest.json`. It refuses to produce a partial manifest: a Phase R1 result
built from missing inputs would be indistinguishable from an inferred one.

The existing `data/exness/raw/BTCUSDm_M15_202311090000_202609171715.csv` is an
MT5 terminal "Save as CSV" dump of the same symbol. The pipeline reads that
layout too, but it carries no specification and no H1 companion, so it cannot
by itself complete Phase R1.

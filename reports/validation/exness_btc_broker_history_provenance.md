# Broker history provenance check — BTCUSDm

**Conclusion: EXPORTER/TESTER COUNTING DIFFERENCE.** The broker did not revise
history. Two independent `CopyRates` exports taken 4h45m apart are byte-identical
across every one of the 100,239 M15 bars and 25,158 H1 bars they share. Both
record `tick_volume` 271 for `2026-04-19T07:30:00Z`; only the Strategy Tester
reads 270.

## Inputs

| | SHA-256 |
|---|---|
| R1 M15 (validated, captured 2026.09.20 07:44:51) | `b5ce7d60ab3b30490e42d26614e1ff4b9200b198bee71ea033e21b79d680f43a` |
| R1 H1 | `24c0c04ae05900c9b62e9046e497924be4dd15efd1497c006b05a9dfb133250a` |
| Fresh M15 (captured 2026.09.20 12:28:30) | `541818991625333136d38d92747bf72d259968ca018fba82a45d15e231d4bc82` |
| Fresh M15 metadata | `142b87e7d409cd9e867a13cf9071b41ff04f7d83accc9df875c1f89aca3fc6d6` |
| Fresh H1 | `37207bc80215d07928f70c469e6d0c26331a58df3b47b3ab2afd933ff3bef98f` |
| Fresh H1 metadata | `6fe642b98994d16c9a68db27417bf07e91cd2331019e84d72eb42aabd7d6d7d3` |

All five R1 files verified against `R1_BASELINE_HASHES.txt` before and after the
analysis. Nothing in `data/exness/btc/phase_r1/` was written to.

## Bar-by-bar comparison

| | M15 | H1 |
|---|---|---|
| Old bars | 100,239 | 25,158 |
| Fresh bars | 100,258 | 25,163 |
| Shared bars | 100,239 | 25,158 |
| Bars added | 19 | 5 |
| Bars removed | **0** | **0** |
| Bars revised | **0** | **0** |
| Reformatted only | **0** | **0** |

Every added bar is at the tail — M15 `2026-09-20 07:30Z` … `12:00Z`, H1
`07:00Z` … `11:00Z` — which is simply the 4h45m that elapsed between the two
captures. The first bar is unchanged on both timeframes.

### Revisions by field

| Field | M15 | H1 |
|---|---|---|
| timestamp | 0 | 0 |
| open | 0 | 0 |
| high | 0 | 0 |
| low | 0 | 0 |
| close | 0 | 0 |
| tick_volume | **0** | **0** |
| spread | 0 | 0 |
| real_volume | 0 | 0 |

No field changed on any shared bar, on either timeframe. Not prices, not spread,
not volume.

### Gap and segment structure

Unchanged on both timeframes. M15: 6 gaps before and after, identical
boundaries. H1: 1 gap before and after.

```
M15  2023-12-21 02:00 -> 02:30        2024-01-31 19:45 -> 20:30
     2024-12-21 06:15 -> 07:15        2024-12-21 09:30 -> 10:00
     2025-04-14 14:00 -> 14:30        2025-10-16 15:00 -> 17:45
H1   2025-10-16 15:00 -> 17:00
```

## The disputed bar

```
R1 export       2026.04.19 07:30:00,75019.57,75133.98,75019.57,75062.29,271,1400,0
fresh re-export 2026.04.19 07:30:00,75019.57,75133.98,75019.57,75062.29,271,1400,0
MT5 tester      2026-04-19T07:30:00Z,...,75019.57,75133.98,75019.57,75062.29,270,1400,14
```

Two history exports 4h45m apart both say **271**. The Strategy Tester says
**270**. OHLC and spread agree everywhere.

## Certified windows

| Window | M15 | H1 |
|---|---|---|
| Window 1 — 2026-01-01 → 2026-03-01 | CLEAN — 0 revised, 0 added, 0 removed | CLEAN |
| Window 2 — 2025-09-01 → 2025-12-01 | CLEAN | CLEAN |
| Window 3 — 2026-03-01 → 2026-05-10 | CLEAN | CLEAN |

**No revised OHLC or spread bar exists anywhere in the dataset**, so none exists
inside either certified window. Both Stage 2 certifications rest on data that is
provably unchanged.

## Re-derived audit and re-run parity

The fresh M15 snapshot was ingested through the same path that built R1
(`read_broker_ohlcv` + `validate_candles`, validation passed, 100,258 rows) into
`data/exness/btc/provenance/processed/btcusdm_M15_reexport.csv`. Over the 100,239
shared rows the processed frames differ in no column.

The Python audit regenerated from that snapshot is **byte-identical** to the one
derived from R1 — same SHA-256
`89a1a2f61a9b1f6ed35935937e68f7430070b0a3dbf81829102c6ecb9355b3cd`.

Re-running the third window against the unchanged MT5 audit reproduces the
earlier result exactly: 6,719 aligned bars, 1 mismatch, `tick_volume` on
`2026-04-19T07:30:00Z`, every other dimension 100%, 16/16 trades matching.
Tolerances and comparator rules unchanged.

## Conclusion

**EXPORTER/TESTER COUNTING DIFFERENCE.** What is established from the evidence:

* the broker did not revise history — two independent captures agree on every
  shared bar of both timeframes;
* the Python side is faithful to both captures;
* the disagreement is between MT5's stored M15 bar record, which `CopyRates`
  exports, and the Strategy Tester's reconstruction of that bar from the tick
  stream in *every tick based on real ticks* mode.

What is **not** established: the mechanism inside MT5 that produces the one-tick
difference. A boundary tick attributed to the adjacent bar would explain it, but
that is an inference, not an observation, and nothing in the exported evidence
confirms it.

The canary was worth following and it has come back clean. The risk that
motivated this check — that broker history was silently changing under the
certified windows — does not exist in this dataset.

## Status of the third window

Still **NOT CERTIFIED**, deliberately. The `DATA_MISMATCH` is unchanged and the
comparator rules were not touched. What has changed is that the cause is now
known and bounded rather than unexplained.

Certifying it would require a scoped rule — something like "`tick_volume` may
differ when every other raw field on that bar is identical" — which does weaken
the raw-data standard. That is a decision to take deliberately, not something to
fold into a provenance check.

The two Stage 2 certifications are unaffected and remain valid.

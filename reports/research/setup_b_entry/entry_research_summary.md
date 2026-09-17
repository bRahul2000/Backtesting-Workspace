# Setup B entry-quality research

**RESEARCH ONLY — active Setup B remains at original V2.2 defaults and fixed 3R.**

All one-factor and combination selection used only 2021–2024 candles. The frozen candidate file was written before any 2025–2026 run.

Protocol note: the initial mechanical screen required at least 50% retention for a factor shortlist and produced no shortlist. Before viewing forward data, the screen was revised to admit adjacent development plateaus with at least 250 trades and 40% retention; the initial result and protocol are archived in this folder. Final candidate qualification still uses the stricter rule.

Segments reset account, indicators, pending orders and positions; no data gap is bridged.

H1 slope levels are quantiles of the absolute normalized signal-time H1 EMA200 slope among Phase 4C development completed trades. Long and short use the same magnitude threshold.

## Development control

| Trades | PF | Avg R | Net PnL $ | Worst segment DD % | Zero-cost PF |
|---:|---:|---:|---:|---:|---:|
| 639 | 0.874 | -0.089 | -1454.46 | 4.82 | 1.091 |

## Factor trends

- minimum_adx: Stable adjacent-value plateau; not necessarily monotonic
- maximum_extension_atr: Broad monotonic improvement across tested values
- minimum_body_percent: Stable adjacent-value plateau; not necessarily monotonic
- minimum_range_atr: No joint PF and average-R improvement
- maximum_range_atr: Broad monotonic improvement across tested values
- minimum_structure_break_atr: No joint PF and average-R improvement
- minimum_stop_atr: No joint PF and average-R improvement
- maximum_stop_atr: POSSIBLE OVERFIT: isolated single-value improvement
- long_rsi_min: No joint PF and average-R improvement
- long_rsi_max: Broad monotonic improvement across tested values
- short_rsi_max: Stable adjacent-value plateau; not necessarily monotonic
- short_rsi_min: Stable adjacent-value plateau; not necessarily monotonic
- minimum_h1_slope_percent: Broad monotonic improvement across tested values

## Shortlist

- minimum_adx = 25: adjacent qualifying development settings
- maximum_extension_atr = 1.75: adjacent qualifying development settings
- minimum_body_percent = 0.6: adjacent qualifying development settings
- minimum_h1_slope_percent = 0.0778787: adjacent qualifying development settings

## Predefined combinations

- C1: {"maximum_extension_atr": 1.75, "minimum_adx": 25.0}
- C2: {"minimum_adx": 25.0, "minimum_body_percent": 0.6}
- C3: {"maximum_extension_atr": 1.75, "minimum_body_percent": 0.6}
- C4: {"maximum_extension_atr": 1.75, "minimum_adx": 25.0, "minimum_body_percent": 0.6}

## Development combinations

| Model | Trades | Retention % | WR % | PF | Avg R | Net PnL $ | Worst segment DD % | Low sample |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| C1 | 239 | 37.4 | 27.20 | 0.851 | -0.106 | -643.70 | 3.32 | True |
| C2 | 326 | 51.0 | 28.83 | 0.968 | -0.021 | -186.34 | 3.80 | False |
| C3 | 388 | 60.7 | 29.64 | 0.994 | -0.003 | -38.52 | 3.04 | False |
| C4 | 198 | 31.0 | 28.79 | 0.936 | -0.043 | -222.94 | 2.11 | True |

## Frozen candidates

- C2: {"minimum_adx": 25.0, "minimum_body_percent": 0.6}
- C3: {"maximum_extension_atr": 1.75, "minimum_body_percent": 0.6}
- minimum_adx=25: {"minimum_adx": 25.0}

The forward-validation set was previously viewed in aggregate and is not a pristine holdout.

## Forward validation · current costs

| Model | Side | Trades | WR % | PF | Avg R | Net PnL $ | Worst segment DD % |
|---|---|---:|---:|---:|---:|---:|---:|
| CONTROL | All | 316 | 25.63 | 0.793 | -0.153 | -1182.16 | 9.07 |
| CONTROL | LONG | 151 | 25.83 | 0.759 | -0.174 | -656.93 | 3.77 |
| CONTROL | SHORT | 165 | 25.45 | 0.824 | -0.133 | -525.23 | 5.95 |
| C2 | All | 163 | 26.38 | 0.834 | -0.120 | -492.33 | 4.22 |
| C2 | LONG | 75 | 24.00 | 0.713 | -0.216 | -405.48 | 1.75 |
| C2 | SHORT | 88 | 28.41 | 0.944 | -0.039 | -86.85 | 3.22 |
| C3 | All | 176 | 25.00 | 0.748 | -0.188 | -814.61 | 5.87 |
| C3 | LONG | 85 | 23.53 | 0.665 | -0.254 | -531.96 | 3.65 |
| C3 | SHORT | 91 | 26.37 | 0.828 | -0.126 | -282.65 | 3.10 |
| minimum_adx=25 | All | 179 | 26.26 | 0.826 | -0.127 | -569.44 | 4.70 |
| minimum_adx=25 | LONG | 81 | 23.46 | 0.688 | -0.237 | -480.77 | 2.21 |
| minimum_adx=25 | SHORT | 98 | 28.57 | 0.949 | -0.036 | -88.67 | 3.21 |

Cost sensitivity uses the same forward trades and exits under alternate commissions; see `cost_crosscheck.csv`. Zero cost is diagnostic context only.

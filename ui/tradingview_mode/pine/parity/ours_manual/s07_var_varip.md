# Expected table values — `s07_var_varip` (var / varip (historical))

Paste `manual/s07_var_varip.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: udf_var_b counts only on even bars (its own call site); no_var is always 1.

## Page 0 · Columns 1 — bars 0-9: first bars

| bar | var_count | varip_count | var_last_cross | var_resets | udf_var_a | udf_var_b | no_var |
|---|---|---|---|---|---|---|---|
| 0 | 1 | 1 | na | 0 | 1 | 1 | 1 |
| 1 | 2 | 2 | na | 1 | 2 | -1 | 1 |
| 2 | 3 | 3 | na | 2 | 3 | 2 | 1 |
| 3 | 4 | 4 | na | 3 | 4 | -1 | 1 |
| 4 | 5 | 5 | na | 4 | 5 | 3 | 1 |
| 5 | 6 | 6 | na | 5 | 6 | -1 | 1 |
| 6 | 7 | 7 | na | 6 | 7 | 4 | 1 |
| 7 | 8 | 8 | na | 7 | 8 | -1 | 1 |
| 8 | 9 | 9 | na | 8 | 9 | 5 | 1 |
| 9 | 10 | 10 | na | 9 | 10 | -1 | 1 |

## Page 1 · Columns 1 — bars 45-54: var_resets goes back to 0 at bar 50

| bar | var_count | varip_count | var_last_cross | var_resets | udf_var_a | udf_var_b | no_var |
|---|---|---|---|---|---|---|---|
| 45 | 46 | 46 | na | 45 | 46 | -1 | 1 |
| 46 | 47 | 47 | na | 46 | 47 | 24 | 1 |
| 47 | 48 | 48 | na | 47 | 48 | -1 | 1 |
| 48 | 49 | 49 | na | 48 | 49 | 25 | 1 |
| 49 | 50 | 50 | na | 49 | 50 | -1 | 1 |
| 50 | 51 | 51 | na | 0 | 51 | 26 | 1 |
| 51 | 52 | 52 | na | 1 | 52 | -1 | 1 |
| 52 | 53 | 53 | na | 2 | 53 | 27 | 1 |
| 53 | 54 | 54 | na | 3 | 54 | -1 | 1 |
| 54 | 55 | 55 | na | 4 | 55 | 28 | 1 |

## Page 2 · Columns 1 — bars 84-93: var_last_cross is set at bar 88

| bar | var_count | varip_count | var_last_cross | var_resets | udf_var_a | udf_var_b | no_var |
|---|---|---|---|---|---|---|---|
| 84 | 85 | 85 | na | 34 | 85 | 43 | 1 |
| 85 | 86 | 86 | na | 35 | 86 | -1 | 1 |
| 86 | 87 | 87 | na | 36 | 87 | 44 | 1 |
| 87 | 88 | 88 | na | 37 | 88 | -1 | 1 |
| 88 | 89 | 89 | 102.75 | 38 | 89 | 45 | 1 |
| 89 | 90 | 90 | 102.75 | 39 | 90 | -1 | 1 |
| 90 | 91 | 91 | 102.75 | 40 | 91 | 46 | 1 |
| 91 | 92 | 92 | 102.75 | 41 | 92 | -1 | 1 |
| 92 | 93 | 93 | 102.75 | 42 | 93 | 47 | 1 |
| 93 | 94 | 94 | 102.75 | 43 | 94 | -1 | 1 |

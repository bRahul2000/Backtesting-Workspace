# Expected table values — `s08_loops_v6` (loops (v6 semantics))

Paste `manual/s08_loops_v6.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: v6: for_dynamic_end = 7 (end re-read every iteration), div_const = 3.5, and_stateful = 1 on bar 6.

## Page 0 · Columns 1 — bars 0-9: first bars

| bar | for_dynamic_end | div_const | and_stateful | for_value | for_desc_by2 |
|---|---|---|---|---|---|
| 0 | 7 | 3.5 | 0 | 8 | 30 |
| 1 | 7 | 3.5 | 0 | 8 | 30 |
| 2 | 7 | 3.5 | 0 | 8 | 30 |
| 3 | 7 | 3.5 | 0 | 8 | 30 |
| 4 | 7 | 3.5 | 0 | 8 | 30 |
| 5 | 7 | 3.5 | 0 | 8 | 30 |
| 6 | 7 | 3.5 | 1 | 8 | 30 |
| 7 | 7 | 3.5 | 0 | 8 | 30 |
| 8 | 7 | 3.5 | 0 | 8 | 30 |
| 9 | 7 | 3.5 | 0 | 8 | 30 |

## Page 0 · Columns 2 — bars 0-9: first bars

| bar | for_sum10 | for_break | while_steps | div_series |
|---|---|---|---|---|
| 0 | na | 0 | 1 | 0 |
| 1 | na | 0 | 1 | 0.5 |
| 2 | na | 1 | 0 | 1 |
| 3 | na | 0 | 1 | 1.5 |
| 4 | na | 0 | 1 | 2 |
| 5 | na | 0 | 1 | 2.5 |
| 6 | na | 0 | 2 | 3 |
| 7 | na | 0 | 2 | 3.5 |
| 8 | na | 1 | 1 | 4 |
| 9 | 1021.25 | 0 | 1 | 4.5 |

## Page 1 · Columns 1 — bars 10-19: later bars

| bar | for_dynamic_end | div_const | and_stateful | for_value | for_desc_by2 |
|---|---|---|---|---|---|
| 10 | 7 | 3.5 | 0 | 8 | 30 |
| 11 | 7 | 3.5 | 0 | 8 | 30 |
| 12 | 7 | 3.5 | 0 | 8 | 30 |
| 13 | 7 | 3.5 | 0 | 8 | 30 |
| 14 | 7 | 3.5 | 1 | 8 | 30 |
| 15 | 7 | 3.5 | 0 | 8 | 30 |
| 16 | 7 | 3.5 | 0 | 8 | 30 |
| 17 | 7 | 3.5 | 0 | 8 | 30 |
| 18 | 7 | 3.5 | 0 | 8 | 30 |
| 19 | 7 | 3.5 | 0 | 8 | 30 |

## Page 1 · Columns 2 — bars 10-19: later bars

| bar | for_sum10 | for_break | while_steps | div_series |
|---|---|---|---|---|
| 10 | 1025.25 | 0 | 2 | 5 |
| 11 | 1029.25 | 0 | 2 | 5.5 |
| 12 | 1037.5 | 0 | 3 | 6 |
| 13 | 1045.75 | 0 | 3 | 6.5 |
| 14 | 1049.75 | 1 | 2 | 7 |
| 15 | 1053.75 | 0 | 2 | 7.5 |
| 16 | 1057.75 | 0 | 3 | 8 |
| 17 | 1061.75 | 0 | 3 | 8.5 |
| 18 | 1070 | 0 | 3 | 9 |
| 19 | 1074 | 1 | 3 | 9.5 |

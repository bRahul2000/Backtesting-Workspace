# Expected table values — `s09_loops_v5` (loops (v5 semantics))

Paste `manual/s09_loops_v5.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: v5: for_dynamic_end = 4 (end fixed before the loop), div_const = 3, and_stateful always 0.

## Page 0 · Columns 1 — bars 0-9: first bars

| bar | for_dynamic_end | div_const | and_stateful | for_value | for_desc_by2 |
|---|---|---|---|---|---|
| 0 | 4 | 3 | 0 | 8 | 30 |
| 1 | 4 | 3 | 0 | 8 | 30 |
| 2 | 4 | 3 | 0 | 8 | 30 |
| 3 | 4 | 3 | 0 | 8 | 30 |
| 4 | 4 | 3 | 0 | 8 | 30 |
| 5 | 4 | 3 | 0 | 8 | 30 |
| 6 | 4 | 3 | 0 | 8 | 30 |
| 7 | 4 | 3 | 0 | 8 | 30 |
| 8 | 4 | 3 | 0 | 8 | 30 |
| 9 | 4 | 3 | 0 | 8 | 30 |

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
| 10 | 4 | 3 | 0 | 8 | 30 |
| 11 | 4 | 3 | 0 | 8 | 30 |
| 12 | 4 | 3 | 0 | 8 | 30 |
| 13 | 4 | 3 | 0 | 8 | 30 |
| 14 | 4 | 3 | 0 | 8 | 30 |
| 15 | 4 | 3 | 0 | 8 | 30 |
| 16 | 4 | 3 | 0 | 8 | 30 |
| 17 | 4 | 3 | 0 | 8 | 30 |
| 18 | 4 | 3 | 0 | 8 | 30 |
| 19 | 4 | 3 | 0 | 8 | 30 |

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

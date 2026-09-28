# Expected table values — `s10_control` (switch / ternary / functions / tuples)

Paste `manual/s10_control.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: switch_subject is na every 4th bar; if_noelse_na is na unless bar % 3 == 0.

## Page 0 · Columns 1 — bars 0-9: first bars

| bar | switch_nosubject | switch_subject | ternary_chain | ternary_na | if_expr | if_noelse_na |
|---|---|---|---|---|---|---|
| 0 | 1 | 10 | 1 | na | 1 | 100.75 |
| 1 | 1 | 20 | 1 | na | 1 | na |
| 2 | -1 | 30 | -1 | na | -1 | na |
| 3 | 1 | na | 1 | na | 1 | 100.25 |
| 4 | 1 | 10 | 1 | na | 1 | na |
| 5 | 1 | 20 | 1 | na | 1 | na |
| 6 | 1 | 30 | 1 | na | 1 | 104 |
| 7 | 1 | na | 1 | na | 1 | na |
| 8 | -1 | 10 | -1 | na | -1 | na |
| 9 | 1 | 20 | 1 | na | 1 | 103.5 |

## Page 0 · Columns 2 — bars 0-9: first bars

| bar | udf_default | udf_arg | tuple_mid | tuple_up | tuple_lo | tuple2_up |
|---|---|---|---|---|---|---|
| 0 | 0.5 | 0.25 | na | na | na | na |
| 1 | 5.25 | 2.625 | na | na | na | na |
| 2 | 6.25 | 3.125 | na | na | na | na |
| 3 | 3.75 | 1.875 | na | na | na | na |
| 4 | 5.75 | 2.875 | na | na | na | 105.13238076 |
| 5 | 5 | 2.5 | na | na | na | 105.6078784 |
| 6 | 4.25 | 2.125 | na | na | na | 107.40941171 |
| 7 | 6.25 | 3.125 | na | na | na | 109.49264069 |
| 8 | 4 | 2 | na | na | na | 108.90941171 |
| 9 | 1.5 | 0.75 | 102.125 | 105.65522662 | 98.59477338 | 108.90941171 |

## Page 1 · Columns 1 — bars 14-23: ternary_na becomes a number from bar 18

| bar | switch_nosubject | switch_subject | ternary_chain | ternary_na | if_expr | if_noelse_na |
|---|---|---|---|---|---|---|
| 14 | -1 | 30 | -1 | na | -1 | na |
| 15 | 1 | na | 1 | na | 1 | 106.75 |
| 16 | 1 | 10 | 1 | na | 1 | na |
| 17 | 1 | 20 | 1 | na | 1 | na |
| 18 | 1 | 30 | 1 | 110.5 | 1 | 110.5 |
| 19 | -1 | na | -1 | na | -1 | na |
| 20 | 1 | 10 | 1 | na | 1 | na |
| 21 | 1 | 20 | 1 | na | 1 | 110 |
| 22 | 1 | 30 | 1 | 111.25 | 1 | na |
| 23 | 1 | na | 1 | 112.5 | 1 | na |

## Page 1 · Columns 2 — bars 14-23: ternary_na becomes a number from bar 18

| bar | udf_default | udf_arg | tuple_mid | tuple_up | tuple_lo | tuple2_up |
|---|---|---|---|---|---|---|
| 14 | 5 | 2.5 | 104.975 | 108.69286229 | 101.25713771 | 111.60555128 |
| 15 | 5.25 | 2.625 | 105.375 | 108.90522662 | 101.84477338 | 110.98666429 |
| 16 | 4.5 | 2.25 | 105.775 | 109.49286229 | 102.05713771 | 110.82970585 |
| 17 | 3.75 | 1.875 | 106.175 | 110.4061346 | 101.9438654 | 111.8578784 |
| 18 | 5.75 | 2.875 | 107 | 111.0620192 | 102.9379808 | 113.65941171 |
| 19 | 6.75 | 3.375 | 107.4 | 110.72565783 | 104.07434217 | 114.85555128 |
| 20 | 4.25 | 2.125 | 107.8 | 110.68790582 | 104.91209418 | 114.23666429 |
| 21 | 3 | 1.5 | 108.2 | 111.08790582 | 105.31209418 | 114.23666429 |
| 22 | 2.25 | 1.125 | 108.6 | 111.92565783 | 105.27434217 | 114.23666429 |
| 23 | 4.25 | 2.125 | 109 | 113.0620192 | 104.9379808 | 114.23666429 |

# Expected table values — `s04_cross` (crossovers)

Paste `manual/s04_cross.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: the exact bar each 1 appears on (xover_touch must be 1 on bar 101 only).

## Page 0 · Columns 1 — bars 84-93: first ema/sma crossover at bar 88

| bar | xover | xunder | xany | xover_touch | xunder_touch | xover_flat |
|---|---|---|---|---|---|---|
| 84 | 0 | 0 | 0 | 0 | 0 | 0 |
| 85 | 0 | 0 | 0 | 0 | 0 | 0 |
| 86 | 0 | 0 | 0 | 0 | 0 | 0 |
| 87 | 0 | 0 | 0 | 0 | 0 | 0 |
| 88 | 1 | 0 | 1 | 0 | 0 | 0 |
| 89 | 0 | 0 | 0 | 0 | 0 | 0 |
| 90 | 0 | 0 | 0 | 0 | 0 | 0 |
| 91 | 0 | 0 | 0 | 0 | 0 | 0 |
| 92 | 0 | 0 | 0 | 0 | 0 | 0 |
| 93 | 0 | 0 | 0 | 0 | 0 | 0 |

## Page 0 · Columns 2 — bars 84-93: first ema/sma crossover at bar 88

| bar | rising3 | falling3 | since_xover | valuewhen0 | valuewhen1 |
|---|---|---|---|---|---|
| 84 | 0 | 0 | na | na | na |
| 85 | 1 | 0 | na | na | na |
| 86 | 1 | 0 | na | na | na |
| 87 | 0 | 1 | na | na | na |
| 88 | 0 | 0 | 0 | 102.75 | na |
| 89 | 0 | 0 | 1 | 102.75 | na |
| 90 | 1 | 0 | 2 | 102.75 | na |
| 91 | 1 | 0 | 3 | 102.75 | na |
| 92 | 1 | 0 | 4 | 102.75 | na |
| 93 | 0 | 1 | 5 | 102.75 | na |

## Page 1 · Columns 1 — bars 96-105: k - 100 touches 0 at bar 100, crosses at 101

| bar | xover | xunder | xany | xover_touch | xunder_touch | xover_flat |
|---|---|---|---|---|---|---|
| 96 | 0 | 0 | 0 | 0 | 0 | 0 |
| 97 | 0 | 0 | 0 | 0 | 0 | 0 |
| 98 | 0 | 0 | 0 | 0 | 0 | 1 |
| 99 | 0 | 0 | 0 | 0 | 0 | 0 |
| 100 | 0 | 0 | 0 | 0 | 0 | 0 |
| 101 | 0 | 0 | 0 | 1 | 1 | 1 |
| 102 | 0 | 0 | 0 | 0 | 0 | 0 |
| 103 | 0 | 0 | 0 | 0 | 0 | 0 |
| 104 | 0 | 0 | 0 | 0 | 0 | 0 |
| 105 | 0 | 0 | 0 | 0 | 0 | 1 |

## Page 1 · Columns 2 — bars 96-105: k - 100 touches 0 at bar 100, crosses at 101

| bar | rising3 | falling3 | since_xover | valuewhen0 | valuewhen1 |
|---|---|---|---|---|---|
| 96 | 1 | 0 | 8 | 102.75 | na |
| 97 | 1 | 0 | 9 | 102.75 | na |
| 98 | 1 | 0 | 10 | 102.75 | na |
| 99 | 0 | 1 | 11 | 102.75 | na |
| 100 | 0 | 0 | 12 | 102.75 | na |
| 101 | 0 | 0 | 13 | 102.75 | na |
| 102 | 1 | 0 | 14 | 102.75 | na |
| 103 | 1 | 0 | 15 | 102.75 | na |
| 104 | 0 | 1 | 16 | 102.75 | na |
| 105 | 0 | 0 | 17 | 102.75 | na |

## Page 2 · Columns 1 — bars 150-159: volatility: crosses at 154, 155, 160, 161, 165

| bar | xover | xunder | xany | xover_touch | xunder_touch | xover_flat |
|---|---|---|---|---|---|---|
| 150 | 0 | 0 | 0 | 0 | 0 | 0 |
| 151 | 0 | 0 | 0 | 0 | 0 | 0 |
| 152 | 0 | 0 | 0 | 0 | 0 | 0 |
| 153 | 0 | 0 | 0 | 0 | 0 | 0 |
| 154 | 1 | 0 | 1 | 0 | 0 | 1 |
| 155 | 0 | 1 | 1 | 0 | 0 | 0 |
| 156 | 0 | 0 | 0 | 0 | 0 | 0 |
| 157 | 0 | 0 | 0 | 0 | 0 | 0 |
| 158 | 0 | 0 | 0 | 0 | 0 | 0 |
| 159 | 0 | 0 | 0 | 0 | 0 | 0 |

## Page 2 · Columns 2 — bars 150-159: volatility: crosses at 154, 155, 160, 161, 165

| bar | rising3 | falling3 | since_xover | valuewhen0 | valuewhen1 |
|---|---|---|---|---|---|
| 150 | 0 | 1 | 62 | 102.75 | na |
| 151 | 0 | 0 | 63 | 102.75 | na |
| 152 | 0 | 0 | 64 | 102.75 | na |
| 153 | 1 | 0 | 65 | 102.75 | na |
| 154 | 1 | 0 | 0 | 115 | 102.75 |
| 155 | 0 | 1 | 1 | 115 | 102.75 |
| 156 | 0 | 0 | 2 | 115 | 102.75 |
| 157 | 0 | 0 | 3 | 115 | 102.75 |
| 158 | 1 | 0 | 4 | 115 | 102.75 |
| 159 | 1 | 0 | 5 | 115 | 102.75 |

## Page 3 · Columns 1 — bars 203-212: crossunder at 207; closes sit exactly on 110 from 210

| bar | xover | xunder | xany | xover_touch | xunder_touch | xover_flat |
|---|---|---|---|---|---|---|
| 203 | 0 | 0 | 0 | 0 | 0 | 0 |
| 204 | 0 | 0 | 0 | 0 | 0 | 0 |
| 205 | 0 | 0 | 0 | 0 | 0 | 0 |
| 206 | 0 | 0 | 0 | 0 | 0 | 0 |
| 207 | 0 | 1 | 1 | 0 | 0 | 0 |
| 208 | 0 | 0 | 0 | 0 | 0 | 0 |
| 209 | 0 | 0 | 0 | 0 | 0 | 0 |
| 210 | 0 | 0 | 0 | 0 | 0 | 0 |
| 211 | 0 | 0 | 0 | 0 | 0 | 0 |
| 212 | 0 | 0 | 0 | 0 | 0 | 0 |

## Page 3 · Columns 2 — bars 203-212: crossunder at 207; closes sit exactly on 110 from 210

| bar | rising3 | falling3 | since_xover | valuewhen0 | valuewhen1 |
|---|---|---|---|---|---|
| 203 | 0 | 0 | 34 | 104.5 | 112.5 |
| 204 | 1 | 0 | 35 | 104.5 | 112.5 |
| 205 | 1 | 0 | 36 | 104.5 | 112.5 |
| 206 | 0 | 1 | 37 | 104.5 | 112.5 |
| 207 | 0 | 0 | 38 | 104.5 | 112.5 |
| 208 | 0 | 0 | 39 | 104.5 | 112.5 |
| 209 | 1 | 0 | 40 | 104.5 | 112.5 |
| 210 | 0 | 1 | 41 | 104.5 | 112.5 |
| 211 | 0 | 0 | 42 | 104.5 | 112.5 |
| 212 | 0 | 0 | 43 | 104.5 | 112.5 |

## Page 4 · Columns 1 — bars 216-225: crossover of 110 at bar 222

| bar | xover | xunder | xany | xover_touch | xunder_touch | xover_flat |
|---|---|---|---|---|---|---|
| 216 | 0 | 0 | 0 | 0 | 0 | 0 |
| 217 | 0 | 0 | 0 | 0 | 0 | 0 |
| 218 | 0 | 0 | 0 | 0 | 0 | 0 |
| 219 | 0 | 0 | 0 | 0 | 0 | 0 |
| 220 | 0 | 0 | 0 | 0 | 0 | 0 |
| 221 | 0 | 0 | 0 | 0 | 0 | 0 |
| 222 | 0 | 0 | 0 | 0 | 0 | 1 |
| 223 | 0 | 0 | 0 | 0 | 0 | 0 |
| 224 | 0 | 0 | 0 | 0 | 0 | 0 |
| 225 | 0 | 0 | 0 | 0 | 0 | 0 |

## Page 4 · Columns 2 — bars 216-225: crossover of 110 at bar 222

| bar | rising3 | falling3 | since_xover | valuewhen0 | valuewhen1 |
|---|---|---|---|---|---|
| 216 | 0 | 0 | 47 | 104.5 | 112.5 |
| 217 | 0 | 0 | 48 | 104.5 | 112.5 |
| 218 | 0 | 0 | 49 | 104.5 | 112.5 |
| 219 | 0 | 0 | 50 | 104.5 | 112.5 |
| 220 | 0 | 0 | 51 | 104.5 | 112.5 |
| 221 | 0 | 0 | 52 | 104.5 | 112.5 |
| 222 | 1 | 0 | 53 | 104.5 | 112.5 |
| 223 | 0 | 1 | 54 | 104.5 | 112.5 |
| 224 | 0 | 0 | 55 | 104.5 | 112.5 |
| 225 | 0 | 0 | 56 | 104.5 | 112.5 |

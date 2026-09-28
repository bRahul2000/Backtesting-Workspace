# Expected table values — `s06_pivots` (pivots with ties)

Paste `manual/s06_pivots.pine` into TradingView. Each block below is one **Page** / **Columns** setting; the numbers must match TradingView's table.

Look at first: which of two equal values becomes the pivot (3/3, 2/1 and 1/3 are not yet confirmed anywhere).

## Page 0 · Columns 1 — bars 0-9: tie pattern, first pivots

| bar | tp | ph33 | pl33 | ph21 | pl13 |
|---|---|---|---|---|---|
| 0 | 3 | na | na | na | na |
| 1 | 5 | na | na | na | na |
| 2 | 5 | na | na | na | na |
| 3 | 2 | na | na | 5 | na |
| 4 | 6 | na | na | na | na |
| 5 | 6 | na | na | na | na |
| 6 | 6 | na | 2 | na | 2 |
| 7 | 1 | na | na | 6 | na |
| 8 | 4 | na | na | na | na |
| 9 | 7 | na | na | na | na |

## Page 0 · Columns 2 — bars 0-9: tie pattern, first pivots

| bar | tp | ph11 | pl11 | ph22 | pl22 |
|---|---|---|---|---|---|
| 0 | 3 | na | na | na | na |
| 1 | 5 | na | na | na | na |
| 2 | 5 | na | na | na | na |
| 3 | 2 | 5 | na | na | na |
| 4 | 6 | na | 2 | na | na |
| 5 | 6 | na | na | na | 2 |
| 6 | 6 | na | na | na | na |
| 7 | 1 | 6 | na | na | na |
| 8 | 4 | na | 1 | 6 | na |
| 9 | 7 | na | na | na | 1 |

## Page 0 · Columns 3 — bars 0-9: tie pattern, first pivots

| bar | ph22_h | pl22_l | ph33_h | pl33_l |
|---|---|---|---|---|
| 0 | na | na | na | na |
| 1 | na | na | na | na |
| 2 | na | na | na | na |
| 3 | na | na | na | na |
| 4 | na | 97.5 | na | na |
| 5 | na | na | na | na |
| 6 | na | na | na | na |
| 7 | na | na | na | na |
| 8 | na | na | na | na |
| 9 | 108.25 | na | na | na |

## Page 1 · Columns 1 — bars 10-19: tie pattern continued

| bar | tp | ph33 | pl33 | ph21 | pl13 |
|---|---|---|---|---|---|
| 10 | 2 | na | 1 | 7 | 1 |
| 11 | 7 | na | na | na | na |
| 12 | 3 | na | na | 7 | na |
| 13 | 9 | na | na | na | 2 |
| 14 | 1 | na | na | 9 | na |
| 15 | 1 | na | na | na | na |
| 16 | 9 | na | na | na | na |
| 17 | 2 | na | na | 9 | na |
| 18 | 4 | na | 1 | na | 1 |
| 19 | 8 | 9 | na | na | na |

## Page 1 · Columns 2 — bars 10-19: tie pattern continued

| bar | tp | ph11 | pl11 | ph22 | pl22 |
|---|---|---|---|---|---|
| 10 | 2 | 7 | na | na | na |
| 11 | 7 | na | 2 | na | na |
| 12 | 3 | 7 | na | na | 2 |
| 13 | 9 | na | 3 | na | na |
| 14 | 1 | 9 | na | na | na |
| 15 | 1 | na | na | 9 | na |
| 16 | 9 | na | 1 | na | na |
| 17 | 2 | 9 | na | na | 1 |
| 18 | 4 | na | 2 | 9 | na |
| 19 | 8 | na | na | na | na |

## Page 1 · Columns 3 — bars 10-19: tie pattern continued

| bar | ph22_h | pl22_l | ph33_h | pl33_l |
|---|---|---|---|---|
| 10 | na | 101.25 | 108.25 | na |
| 11 | na | na | na | na |
| 12 | na | na | na | na |
| 13 | na | na | na | na |
| 14 | na | na | na | na |
| 15 | na | na | na | na |
| 16 | na | na | na | na |
| 17 | na | 103.25 | na | na |
| 18 | na | na | na | 103.25 |
| 19 | na | na | na | na |

## Page 2 · Columns 1 — bars 16-25: first 3/3 pivot high at bar 19

| bar | tp | ph33 | pl33 | ph21 | pl13 |
|---|---|---|---|---|---|
| 16 | 9 | na | na | na | na |
| 17 | 2 | na | na | 9 | na |
| 18 | 4 | na | 1 | na | 1 |
| 19 | 8 | 9 | na | na | na |
| 20 | 3 | na | na | 8 | 2 |
| 21 | 4 | na | na | na | na |
| 22 | 8 | na | na | na | na |
| 23 | 1 | na | na | 8 | na |
| 24 | 3 | na | na | na | na |
| 25 | 5 | 8 | na | na | na |

## Page 2 · Columns 2 — bars 16-25: first 3/3 pivot high at bar 19

| bar | tp | ph11 | pl11 | ph22 | pl22 |
|---|---|---|---|---|---|
| 16 | 9 | na | 1 | na | na |
| 17 | 2 | 9 | na | na | 1 |
| 18 | 4 | na | 2 | 9 | na |
| 19 | 8 | na | na | na | na |
| 20 | 3 | 8 | na | na | na |
| 21 | 4 | na | 3 | 8 | na |
| 22 | 8 | na | na | na | 3 |
| 23 | 1 | 8 | na | na | na |
| 24 | 3 | na | 1 | 8 | na |
| 25 | 5 | na | na | na | 1 |

## Page 2 · Columns 3 — bars 16-25: first 3/3 pivot high at bar 19

| bar | ph22_h | pl22_l | ph33_h | pl33_l |
|---|---|---|---|---|
| 16 | na | na | na | na |
| 17 | na | 103.25 | na | na |
| 18 | na | na | na | 103.25 |
| 19 | na | na | na | na |
| 20 | na | na | na | na |
| 21 | 113.25 | 106.5 | na | na |
| 22 | na | na | 113.25 | na |
| 23 | na | na | na | na |
| 24 | na | na | na | na |
| 25 | na | na | na | na |

## Page 3 · Columns 1 — bars 184-193: 2/2 pivot highs on equal highs 184/186 (reported at 188) and 190/191 (at 193)

| bar | tp | ph33 | pl33 | ph21 | pl13 |
|---|---|---|---|---|---|
| 184 | 9 | na | na | na | na |
| 185 | 2 | na | na | 9 | na |
| 186 | 4 | na | 1 | na | 1 |
| 187 | 8 | 9 | na | na | na |
| 188 | 3 | na | na | 8 | 2 |
| 189 | 4 | na | na | na | na |
| 190 | 8 | na | na | na | na |
| 191 | 1 | na | na | 8 | na |
| 192 | 3 | na | na | na | na |
| 193 | 5 | 8 | na | na | na |

## Page 3 · Columns 2 — bars 184-193: 2/2 pivot highs on equal highs 184/186 (reported at 188) and 190/191 (at 193)

| bar | tp | ph11 | pl11 | ph22 | pl22 |
|---|---|---|---|---|---|
| 184 | 9 | na | 1 | na | na |
| 185 | 2 | 9 | na | na | 1 |
| 186 | 4 | na | 2 | 9 | na |
| 187 | 8 | na | na | na | na |
| 188 | 3 | 8 | na | na | na |
| 189 | 4 | na | 3 | 8 | na |
| 190 | 8 | na | na | na | 3 |
| 191 | 1 | 8 | na | na | na |
| 192 | 3 | na | 1 | 8 | na |
| 193 | 5 | na | na | na | 1 |

## Page 3 · Columns 3 — bars 184-193: 2/2 pivot highs on equal highs 184/186 (reported at 188) and 190/191 (at 193)

| bar | ph22_h | pl22_l | ph33_h | pl33_l |
|---|---|---|---|---|
| 184 | na | na | na | na |
| 185 | na | na | na | na |
| 186 | na | 109.5 | na | na |
| 187 | na | na | na | na |
| 188 | 120 | na | na | na |
| 189 | na | na | 120 | na |
| 190 | na | na | na | na |
| 191 | na | 111 | na | na |
| 192 | na | na | na | na |
| 193 | 120 | na | na | na |

## Page 4 · Columns 1 — bars 200-209: equal lows 95 at 203/205: 2/2 pivot low reported at 207, 3/3 at 208

| bar | tp | ph33 | pl33 | ph21 | pl13 |
|---|---|---|---|---|---|
| 200 | 4 | na | na | na | na |
| 201 | 7 | na | na | na | na |
| 202 | 2 | na | 1 | 7 | 1 |
| 203 | 7 | na | na | na | na |
| 204 | 3 | na | na | 7 | na |
| 205 | 9 | na | na | na | 2 |
| 206 | 1 | na | na | 9 | na |
| 207 | 1 | na | na | na | na |
| 208 | 9 | na | na | na | na |
| 209 | 2 | na | na | 9 | na |

## Page 4 · Columns 2 — bars 200-209: equal lows 95 at 203/205: 2/2 pivot low reported at 207, 3/3 at 208

| bar | tp | ph11 | pl11 | ph22 | pl22 |
|---|---|---|---|---|---|
| 200 | 4 | na | 1 | 6 | na |
| 201 | 7 | na | na | na | 1 |
| 202 | 2 | 7 | na | na | na |
| 203 | 7 | na | 2 | na | na |
| 204 | 3 | 7 | na | na | 2 |
| 205 | 9 | na | 3 | na | na |
| 206 | 1 | 9 | na | na | na |
| 207 | 1 | na | na | 9 | na |
| 208 | 9 | na | 1 | na | na |
| 209 | 2 | 9 | na | na | 1 |

## Page 4 · Columns 3 — bars 200-209: equal lows 95 at 203/205: 2/2 pivot low reported at 207, 3/3 at 208

| bar | ph22_h | pl22_l | ph33_h | pl33_l |
|---|---|---|---|---|
| 200 | na | na | na | na |
| 201 | na | na | na | na |
| 202 | na | na | na | na |
| 203 | 124.75 | na | na | na |
| 204 | na | na | 124.75 | na |
| 205 | na | na | na | na |
| 206 | na | na | na | na |
| 207 | na | 95 | na | na |
| 208 | 119.75 | na | na | 95 |
| 209 | na | na | 119.75 | na |

# P2.2 — real-Live validation of `request.security_lower_tf()`

Recorded 2026-09-28. Required before the final P2.2 tag (P22_LOWER_TF_RESEARCH.md §8). Frozen A1–A4 evidence is not
changed by this file.

## 1. Method

The real app runs as a user would run it: `app.py` via Streamlit with the production frontend build, driven by headless
Chrome with real mouse clicks (`live/live_lower_tf.mjs`), on the real data sources (Binance USD-M public market data;
Exness through this machine's MT5 bridge files). The harness adds the live oracle scripts through the Pine Editor,
goes Live, samples every ~3 s what the terminal shows, then exits and re-enters Live. `live/run_live_validation.py`
starts the app, runs the harness and evaluates every property from the samples; results are written to
`live/results/`. Read-only market data only: execution stays disabled, and no order path exists in this code.

```
venv/bin/python ui/tradingview_mode/pine/parity/live/run_live_validation.py binance   # MT5 switched off
venv/bin/python ui/tradingview_mode/pine/parity/live/run_live_validation.py exness    # the real MT5 bridge
```

Each sample records: the Live state and reason; the chart's own stream counters (`setData` = chart reloads,
`updates` = polls applied); the last Pine plot values on the forming and the previous chart bar; each script's
requested-context provenance (symbol, timeframe, provider, native/aggregated, bar count, `forming bar`, data
identity); script errors; and the wall clock.

| script | purpose | sha256 |
|---|---|---|
| `live/l1_binance_lower_tf.pine` | Binance 15m chart: 1m and 10m intrabars, the same timeframe, `request.security` 60 | `fd59e193e299092323628b565803ca957c361c48d35205b4348d85c19c8ee6af` |
| `live/l2_exness_lower_tf.pine` | Exness 1h and 30m charts: 15m and 30m intrabars, the same timeframe | `97ae23c46696eef6ad7b1b8658c981c0f0ccf7e938612dd28e879358cc64a106` |
| `live/l3_exness_below_m15.pine` | Exness: a 5m request (must fail explicitly) | `ea5f219a72491be859a5685b3151ee2b22117b17b5ae216d9b8a34e75f31f92f` |
| `live/live_lower_tf.mjs` | the browser harness | `88ae4a93472c5a2b73d4580a15a914f2ec27230839cc9ed12c88f9dc9a9ca900` |
| `live/run_live_validation.py` | the runner and the property evaluation | `6406f9041b57222cdc5dec60c4b367f6dc2aa581736c59d707b08bc2fa3f6b5b` |

## 2. Code under test

A4 commit `4fcef2cd82074d412c08f7e3316fa16f44a9fc76` **plus three fixes found by this validation** (uncommitted when
the final Binance run was made; `git diff HEAD` fingerprint `e02b61c52e9e73e9`; whole repository on that tree: 2121
passed, only the 4 accepted baseline failures):

| # | found by | defect | fix |
|---|---|---|---|
| F1 | Binance smoke run, 08:49–08:51 UTC | a same-timeframe request could be one tick off the chart close (1 of 20 samples: −0.1): the chart frame and the received bars were read at two moments of one rerun | the chart's own symbol/timeframe is received from the very frame the payload shows; Exness takes every period from the MT5 snapshot the chart applied in the same rerun (`providers.lower_tf_received`, `terminal.pine_section`) |
| F2 | Exness harness dry run (synthetic MT5 feed) | Exness Live: the whole terminal payload was rejected ("request.security() context bar_count is invalid"): a dataset ending days before the live chart plus the received bars exceeded the validator's 10,001-bar store limit. The same arithmetic applied to P2.1 `request.security()` contexts on Exness Live (latent; P2.1's terminal checks ran Live on Binance only) | every context store is kept within `MAX_BARS_PER_CONTEXT`: the oldest provider bars are dropped (never received ones) and the cut-off time is remembered, so later provider answers are trimmed identically — one rebuild, not one per rerun (`SecurityManager._fit`) |
| F3 | the F2 regression test | Live: confirmed chart bars between the end of the provider's data and the forming bar got empty arrays although their intrabars had been received | in knowable Live mode every chart bar uses the received intrabars closed by its close once the provider's coverage ends; the received bars are fetched once per run |

Each fix has regression tests in `tests/tradingview_mode/pine/test_lower_tf.py`.

## 3. Binance — real Live, **PASS**

Final run on the tree in §2: `live/results/binance_20260928T101607Z.json` (sha256
`a22504c16794ca429454bbbd4ad94e965be391f04fde6d88052677c07fb30d78`).

* Setup: BINANCE BTCUSDT Perpetual, Live, 15m chart; requests `"1"`, `"10"` (custom: aggregated from the received 5m
  stream), `"15"` (same timeframe) and `request.security(…, "60", close)`. MT5 was switched off (an empty MT5 folder),
  so no Exness data could take part.
* Window: Live from 09:57:41 to 10:14:41 UTC (340 samples), then exit Live and re-enter Live (12 more samples) until
  10:16:00 UTC.
* Contexts shown by the terminal: `BINANCE:BTCUSDT 1 · Binance Futures · native · 9983 bars · forming bar ·
  binance:fapi:klines:BTCUSDT:1m:…`, `… 10 · aggregated from 5m …`, `… 15 · native … · forming bar`,
  `… 60 · native … · forming bar`.

| # | required property | result | observed |
|---|---|---|---|
| 1 | the dedicated lower-interval stream is acquired | PASS | the 1m context is present in 340/340 samples, with `forming bar` in 335/340 (the others while a new minute was being received); the last intrabar is the current minute in 327/339 samples, otherwise the minute that has just ended (sampling at the minute boundary) |
| 2 | it does not replace or disturb the chart stream | PASS | Live state LIVE in every sample; chart reloads (`setData`) constant (4) the whole time; chart polls applied 10 → 1023 |
| 3 | completed intrabars appear in order | PASS | 1-minute steps in every sample (forming and previous bar); the first intrabar is always at the chart bar's open (offset 0) |
| 4 | the forming received intrabar appears last | PASS | see 1; its close equals the chart close in 336/339 samples (the others ±0.1 or +0.4: the 1m and 15m streams are separate sockets, so they can be a tick apart; a same-timeframe request is always exact, see 10) |
| 5 | the last element updates with new kline updates | PASS | the last value changed within every one of the 18 minutes observed |
| 6 | a new lower-TF bar is appended at the proper boundary | PASS | 16 minute boundaries seen inside chart bars, each adding exactly one element (`n` +1, last offset +1) |
| 7 | chart-bar rollover produces the correct new array | PASS | 10:00 UTC rollover: the closed bar kept `n=15, first=0, last=14`, in order; the new bar started with `n=1, first=0, last=0` |
| 8 | no future / unreceived intrabar is synthesised | PASS | the last intrabar's open was always before `timenow` (at most −0.587 s); never ahead of the wall-clock minute |
| 9 | disconnect / reconnect / lease cleanup does not corrupt the chart source | PASS | after Exit Live the Live bar is gone; after Go Live again: LIVE in 12/12 samples, forming arrays correct and in order |
| 10 | existing `request.security` and chart behaviour intact | PASS | same timeframe: `n=1`, last − close = 0 in every sample; `request.security(…, "60", close)` equals the P2.1 `lookahead_off` value (TradingView q4: the forming hour only on the hour's last 15m bar, else the previous hour's close) in 339/339 samples; 10m custom intrabars `n ∈ {1, 2}`, last offset 0 or 5 as expected for a non-dividing timeframe (q7) |

Earlier Binance runs (not the evidence of record): run 1, 08:53–09:11 UTC on the tree with only F1: properties 1–9
PASS; its property-10 check was wrong (it compared the 60-minute `request.security` value with the chart close on
every bar, ignoring `lookahead_off`; the engine values were the P2.1 ones), so the check was corrected and the run
repeated. Run 2, 09:13–09:32 UTC on the same tree: 10/10 PASS, two rollovers (09:15, 09:30). Run 3 above is on the
final tree.

## 4. Exness — real Live, **PASS**

Run on the tree in §2 (`git diff HEAD` fingerprint `e02b61c52e9e73e9`): `live/results/exness_20260928T105327Z.json`
(sha256 `70a97ba59def37063f9afc0468c8539c02c0a1142712e20caee4aeefcc29630d`).

* Bridge checked first: `tv_live_BTCUSDm_quote.json` / `tv_live_XAUUSDm_quote.json` rewritten every ~0.3 s (sequence
  numbers increasing), `connected` true, last tick < 2 s old, server − GMT offset 0, M15 / M30 / H1 bars present. The
  user confirmed: Exness MT5 authorised and synchronised, the TradingViewLiveFeed service running.
* Setup: EXNESS BTCUSDm, Live 1h chart from 10:33:11 to 10:51:11 UTC (360 samples), then Live 30m (20 samples), then
  exit and re-enter Live 1h (12 samples), finished 10:53:19 UTC. Scripts L2 (15m, 30m, same timeframe) and L3 (5m).
* Contexts shown by the terminal: `EXNESS:BTCUSDm 15 · Exness MT5 · native · 9975 bars · forming bar ·
  EXNESS_BTCUSDM_M15 · data/exness/btc/phase_r1/processed/btcusdm_M15.csv`, `… 30 · … native · 9756 bars · forming bar ·
  EXNESS_BTCUSDM_M30 …`, `… 60 · … native · 9936 bars · forming bar · EXNESS_BTCUSDM_H1 …`.

| # | required property | result | observed |
|---|---|---|---|
| 1 | reads the MT5 snapshot path | PASS | the 15m context carries `forming bar`; the last 15m intrabar is the current M15 slot in 359/360 samples (the other at the boundary instant) |
| 2 | only received Exness M15/M30/H1 data | PASS | every context's provider is `Exness MT5` with an Exness dataset identity (M15, M30, H1 files) |
| 3 | no Binance fallback | PASS | no Binance context anywhere; the 5m request fails with an Exness message (6) |
| 4 | 15m in 30m, 15m in 1h, 30m in 1h | PASS | closed 1h bars `n15=4, n30=2`; closed 30m bars `n15=2`; the forming 30m bar (10:30) `n15=2`. M15 boundary crossed live at 10:45:04 UTC inside the 10:00 1h bar: `n15` 3 → 4, last offset 30 → 45, while `n30` stayed 2 (the 10:30 M30 bar still forming) |
| 5 | same timeframe | PASS | 1h in 1h and 30m in 30m: `n=1`, last − close = 0 in every sample |
| 6 | below-M15 fails explicitly | PASS | L3: `request.security_lower_tf(): no Exness MT5 source for `BTCUSDm` at 5: the finest dataset is 15m, and 5 is not a multiple of it.` |
| 7 | latest received / forming intrabar | PASS | the last 15m close equals the chart close in 360/360 samples (one MT5 snapshot per rerun, F1); it took 234 distinct values in the 10:30 M15 slot and 121 in the 10:45 slot |
| 8 | chart and lower-TF source in the same family | PASS | chart `BTCUSDm · Exness MT5`, every context `Exness MT5` |
| 9 | MT5 snapshot updates reflected safely; reconnect | PASS | LIVE in 360/360 samples; chart reloads (`setData`) constant (3) while Live; after Exit Live the Live bar is gone; Live 30m, then Live 1h again: LIVE with correct arrays (12/12 samples) |

Execution stayed disabled: the terminal and the MT5 service are read-only; no order path was used.

## 5. Status

| path | status |
|---|---|
| Binance lower-interval stream in an actual Live terminal session | **VERIFIED** (§3) |
| Exness lower-timeframe MT5 snapshot path in an actual Live terminal session | **VERIFIED** (§4) |

Both real-Live paths required before the final P2.2 tag are verified, on A4 plus the live-validation fixes F1–F3
(§2), which form their own checkpoint after A4.

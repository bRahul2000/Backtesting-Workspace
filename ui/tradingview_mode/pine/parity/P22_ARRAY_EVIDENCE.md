# P2.2 arrays — real TradingView evidence (reference and persistence semantics)

Recorded 2026-09-27. Every observation below was produced by **real TradingView** (Pine v6,
BINANCE:BTCUSDT, 1-minute chart) running the frozen oracle scripts listed at the end, and reported by the
user. The engine does **not** implement arrays yet; nothing here is engine output. These scripts are frozen:
they must not be edited (their SHA-256 hashes are recorded below).

## 1. m04 — realtime rollback of arrays (`manual/m04_live_array_rollback.pine`)

Pushes happen on realtime executions only; each pushed value is `bar_index × 1,000,000 + execution number`.

Around bar 9461, realtime tick ≈ 10:

| case | slots | observed |
|---|---|---|
| A | `var a`, mutated through `a` | size BEFORE 3 → AFTER 4; this-bar elements 1; BEFORE stays 3 across ticks 5–10 |
| B | `varip b`, mutated through `b` | size BEFORE 35 → AFTER 36; this-bar elements 10; BEFORE grows every realtime execution |
| C | `varip cOrigin`, `var cAlias = cOrigin`, mutated only through `cAlias` | `cOrigin` stays size 0 (before and after the push in the same execution); `cAlias` behaves like A (3 → 4, this-bar elements 1) |
| D | `var dOrigin`, `varip dAlias = dOrigin`, mutated only through `dAlias` | `dOrigin` stays size 0; `dAlias` behaves like B (35 → 36, this-bar elements 10) |
| E | `varip e := <fresh array>` every realtime execution | BEFORE always size 1 holding the PREVIOUS execution's value; AFTER size 1 with the current value |
| E2 | `varip e2 = na`, allocated once when `na`, then pushed every execution | created only once; grows every tick like B |

First realtime execution of bar 9461 (what each slot held before pushing):
A `3 / b9460:9485` · B `26 / b9460:9485` · C origin `0 / -` · C alias `3 / b9460:9485` ·
D origin `0 / -` · D alias `26 / b9460:9485` · E `1 / b9460:9485` · E2 `26 / b9460:9485`.

## 2. q5 family — historical bars (`quick/q5*.pine`)

| question | observed |
|---|---|
| Q1 persistent aliases (`var origin`, `var alias = origin`; and the varip/var, var/varip combinations) | the slots are **separate** across historical executions: mutating the alias does not mutate the origin on later bars |
| Q2 local alias `x = a` | shares the same mutable array within the execution |
| Q2b `B := A` | B and A share for the rest of that execution; on the next historical bar the persistent slots are separate again, each keeping the contents it had at the previous execution boundary |
| Q4 `a[1]` | exposes the **previous bar's** array state |
| Q4 mutation of `a[1]` (q5c) | runtime error **RE10051**: "Cannot modify the elements of a historical array or any slices of that array. Instead of modifying an array referenced by an ID retrieved with the `[]` operator, create a shallow copy of the array with `array.copy()`, then modify the copy or a slice of that copy." |
| Q5 `==` / `!=` on arrays (q5d) | **does not compile**: TradingView rejects `array<float>` operands for operator `==` (exact compiler text not captured) |
| Q7 function-local `var` array, two call sites | persists across bars, **independently per call site** |
| Q8 pushing through an array parameter | mutates the **caller's** array |
| Q8 `prm := array.new_float()` in a function (q5e) | compile error **CE10175**: Function arguments cannot be mutable ("prm") |
| Q9 `direct = a` vs `array.copy(a)` | direct assignment aliases; `array.copy()` creates an independent array |
| non-`var` baseline | a fresh array every bar; aliases normally within the execution; `nv[1]` is the previous bar's array (q5b) |

## 3. m05 — explicit re-aliasing on every realtime execution (`manual/m05_live_realias_each_tick.pine`)

Every realtime execution: read, `alias := origin`, read, push through `alias`, read.
Format: `BEFORE origin/alias > after alias := origin > after push through alias`.

Observed bar transition: bar 9515 tick 13 exec **9545** → bar 9516 tick 1 exec **9546** NEW (consecutive
execution numbers: no extra execution was observed at *this* transition).

First tick of bar 9516, BEFORE `:=` (size / last element):

| case | origin | alias |
|---|---|---|
| A var / var | 3 / b9515:9545 | 3 / b9515:9545 |
| B varip / varip | 31 / b9515:9545 | 31 / b9515:9545 |
| C var / varip | 3 / b9515:9545 | 3 / b9515:9545 |
| D varip / var | 31 / b9515:9545 | 31 / b9515:9545 |

Bar 9516, tick 4, exec 9549:

| case | BEFORE | after `:=` | after push |
|---|---|---|---|
| A var / var | 3/3 | 3/3 | 4/4 |
| B varip / varip | 34/34 | 34/34 | 35/35 |
| C var origin / varip alias | 3/4 | 3/3 | 4/4 |
| D varip origin / var alias | 34/31 | 34/34 | 35/35 |

## 4. What the evidence establishes (and what it does not)

Established:

1. At the start of an execution, persistent (`var`/`varip`) slots are restored **independently**: two slots
   never share an object across an execution boundary, even if one was initialised from the other (m04 C/D,
   q5 Q1, Q2b).
2. Within one execution, arrays have ordinary reference semantics: `=`, `:=` and function parameters share
   one object, and a mutation through any of them is visible through all (q5 Q2/Q2b/Q8/Q9, m05 "after push").
3. At the end of an execution each persistent slot keeps the contents of the object **it** references at that
   moment (m05 C: the varip alias keeps S+1; m05 D: the varip origin keeps a push made through the var alias).
4. Realtime: `var` slots restore the committed state (last execution of the previous bar) on every tick;
   `varip` slots keep the latest execution's state (m04 A/B, m05).
5. Persistence does not depend on the declaration that created the object, on object ownership, on `varip`
   reachability, or on the variable used to perform the mutation (m04 C/D, m05 D).
6. At the observed transitions, the last execution of the old bar was the committed state seen by the new bar
   (m04 F, m05 bar 9516).
7. `a[1]` is the previous bar's array state and is read-only (RE10051); array equality does not compile;
   array parameters cannot be rebound (CE10175); function-local `var` arrays are per call site;
   `array.copy()` is independent.

Limitations:

* One symbol (BINANCE:BTCUSDT), one timeframe (1 minute), a few minutes of realtime, two observed bar
  transitions with consecutive execution numbers. This does **not** prove there is never an extra execution
  at bar close.
* Only `array<float>` with primitive elements; nested / object elements untested.
* The exact compiler text of the array `==` rejection was not captured.
* CE10175 was observed for an **array** parameter only; scalar parameters untested.
* History (`[1]`) was observed on historical bars only; `varip` array history during realtime is untested.
* `array.slice` (mentioned by RE10051) and every array builtin beyond push/size/last/copy/shift are untested.
* No evidence about maps, matrices, drawings or user-defined types.

## 5. Frozen oracle scripts (SHA-256)

| script | sha256 |
|---|---|
| `manual/m04_live_array_rollback.pine` | `335f79c9ac7b1b6b56dc961aa8c87fa1063a0b495f91b5110e22170e72740699` |
| `manual/m05_live_realias_each_tick.pine` | `3ca8087b72f74ff61e4782a677757943f36b3d563d679ad49d931b262ae93e4e` |
| `quick/q5_array_reference_historical.pine` | `5ee35a93b769161c577a78bf63c002ef8704b946a39d38e29f7f93cc7223bb73` |
| `quick/q5b_array_history.pine` | `99a7119d76b0c0e7d0f0122e8f3f76f606ae0d587f963974b30f465ef2b86105` |
| `quick/q5c_array_history_mutation.pine` | `c327985a4f1e833bf3d879b7197cd31c858c2ab58658ecd73c3953ebef0b6317` |
| `quick/q5d_array_equality.pine` | `310cd4f88da836a3f6a71a02a3619f6b4b545359786b73e02c24bbc2e022e24f` |
| `quick/q5e_array_param_reassign.pine` | `8149ab2103e1fa6320eb1d3a80db1a0479d4fb46f2bcba2099781083f0f6458a` |

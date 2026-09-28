# P2.3b — arrays of drawing IDs, `*.all`, `chart.point`, oracle-support tables-core (research, design, implementation)

Base: P2.3a `767397dcc5f31b9599f032094703af5a1f6d8018` (pushed). Frozen P2.3a model: `P23_DRAWING_RESEARCH.md` §15.
Labels: **doc** (TradingView manual), **obs** (real TradingView run of a frozen oracle), **P2.2** (frozen P2.2 array
evidence), *policy* (engine decision), **U** (unknown; oracle `quick/q9_collections_points.pine`).

## 1. Documentation findings

| # | finding | source |
|---|---|---|
| D1 | `line.all` / `box.all`: "a read-only array containing the IDs of all lines (boxes) displayed by the script"; size depends on `max_*_count` and on how many were drawn | doc, Lines and boxes |
| D2 | `label.all`: "always contains the IDs of all the visible labels"; example deletes `array.get(label.all, 0)` = "the oldest visible label ID"; the array is "automatically maintained by the Pine Script runtime" | doc, Text and shapes |
| D3 | `box.all.last()` used as "the last box drawn" | doc, Lines and boxes |
| D4 | `var` IDs are cheaper than searching `line.all` + `array.last()` for the latest line | doc, Variable declarations |
| D5 | Linefill: "Any pair of line instances can only have one linefill between them. Successive calls to `linefill.new()` using the same line1 and line2 arguments will create a new linefill ID that replaces the previous one associated with them." | doc, Fills |
| D6 | `chart.point` is a reference type (like UDTs, drawings, collections); fields `time`, `index`, `price`; read with `p.price`, written with `p.price := v` and compound operators | doc, Type system |
| D7 | Constructors: `chart.point.new(time, index, price)`, `now(price)` (time/index of the current bar), `from_index(index, price)` (time na), `from_time(time, price)` (index na), `copy(id)` | doc, Type system |
| D8 | Drawings read `index` for `xloc.bar_index` (default) and `time` for `xloc.bar_time`; "the function copies the information from these chart points" | doc, Lines and boxes |
| D9 | Overloads: `line.new(first_point, second_point, xloc, extend, color, style, width, force_overlay)`; `label.new(point, text, xloc, yloc, …)`; `box.new(top_left, bottom_right, border_color, border_width, border_style, extend, xloc, bgcolor, text, …)` beside the x/y forms. Point setters: `line.set_first_point`, `line.set_second_point`, `label.set_point`, `box.set_top_left_point`, `box.set_bottom_right_point` | doc |
| D10 | `array.copy` of reference elements is shallow: the copy stores the same IDs; a deep copy loops `item.copy()` + `set` and works for "user-defined types, drawing types, and chart points" | doc, Arrays |
| D11 | `varip` is allowed for chart.point IDs and for collections of fundamental types / chart.point / qualifying UDTs; NOT for drawing types or collections of drawings | doc, Variable declarations + Arrays |
| D12 | `varip chart.point`: field changes persist across realtime ticks; the same holds for chart points referenced by a `varip` array | doc, Variable declarations |
| D13 | Rollback removes objects created on the open bar (unless referenced by `varip`) and reverts changes to objects referenced by `var` variables | doc, Execution model |
| D14 | `request.security()` accepts `chart.point` IDs, tuples of them, and collections of fundamental types / chart points / qualifying UDTs; drawing types are not requestable | doc, Other timeframes and data |
| D15 | v6 migration guide: no change to `*.all`, arrays of drawings or `chart.point` (only UDT-field history syntax) | doc, v6 migration |
| D16 | `polyline.all`, `table.all` exist | doc |

Not found in the downloaded pages (reference manual is a JS application): whether `chart.point.now()` has a default
`price`; the exact read-only error text of `*.all`; whether `*.all` is a live view.

## 2. Array-of-drawing-IDs model

Composition of two frozen, observed models: the container follows P2.2 (execution-local `PineArray`, per-slot
`ArraySnapshot`, `a[n]` read-only copy with RE10051); the elements are `DrawingRef` values, which are immutable, so a
snapshot of them is exact and stays pointed at the live store.

* Types: `array<line|label|box|linefill>`, `line[]`, `array.new<line>(size, initial)`, `array.new_line/label/box/linefill`,
  `array.from(ids…)` (kind from the non-na values; mixing kinds is an error; all-na stays the P2.2 `float` rule).
* Element check: `coerce_element` accepts `DrawingRef` of the matching kind or na. Dead IDs are ordinary values.
* A1/A2/A3 functions and methods unchanged: get/set/push/pop/shift/unshift/first/last/size/copy/clear/remove, for…in.
* History: `held[1]` is a read-only array of the IDs held then (RE10051 on container mutation, **P2.2**); the objects
  reached through it are live and mutable (**obs** q8 Case 5 for scalar IDs; q9 row B confirms the composition).
* Aliasing: shared container inside one execution; by value across executions (**P2.2** q5 Q1).
* `copy()`: shallow — same IDs (**doc** D10). Deep copy = user loop with `line.copy`.
* GC: arrays are NOT roots (**obs** q8g r3); a collected ID stays in the array and reads as na (**obs** q8g r4).
* `varip array<line>`: compile error worded after CE10128 (**doc** D11; *policy* wording).
* Realtime: container rolls back by P1 buffer truncation; objects by the store journal; the oid counter is restored,
  so a re-executed tick recreates the same IDs and the committed array snapshot stays consistent.
* Unchanged gaps: `array.includes/indexof/sort/slice/fill/…` on drawings; `==` between arrays (**P2.2** q5d).

## 3. `*.all` model

* `line.all`, `label.all`, `box.all`, `linefill.all`: built-in variables of type `series array<kind>`.
* Content: the IDs of the live objects of that kind, **oldest-created first** (**doc** D2 + **obs** q8g r3 order
  U31…U40, first B37…B40).
* Read-only: every mutating array function raises an error (**doc** D1); wording from q9 Case 2, else engine wording.
  `array.copy(label.all)` gives an ordinary mutable array.
* Snapshot vs view (**U-A1**, q9 row A): *proposed default* — each read returns a new read-only array built from the
  store at that moment (a copy, not a view). If q9 shows a live view, the read returns a read-only view object backed
  by the store (the only divergence from P2.2 containers). Repeated reads are independent under the default.
* `var a = label.all` (**U-A2**, q9 row A2): under the default the slot keeps P2.2 by-value semantics (bar-0 contents).
* History `line.all[1]`: compile-time gap (*policy*; not needed by any oracle).
* Delete / GC / linefill replacement / cascade / realtime rollback change the store, hence the next read.
* Replay: one execution per revealed bar (P2.3a §15.13), so `*.all` at the cursor contains only objects knowable then.
* `label.all.size()`, `for id in line.all`, `id.get_y1()`: the analyzer must treat `ns.all` as a variable receiver in
  method calls (today `label.all.size` is looked up as a function name — seen when compiling q8g).
* `polyline.all`, `table.all`: stay gaps.

## 4. `linefill.all` size 2 (q8 Case 0) — resolution plan

The observation and the manual are both kept. Hypotheses consistent with both:

| id | hypothesis | q9 signature |
|---|---|---|
| H1 | replacement is at the pair/display level; the replaced ID stays listed in `linefill.all` (and may stay non-na) but is not drawn | band A size +2, band A light blue, na(red) no |
| H2 | the manual is inaccurate: both fills live and are drawn | +2, band A purple |
| H3 | the replaced ID is removed later (end of execution or next bar), not at the call | same-bar +2 but later-bar rows show red na / fewer IDs |
| H4 | an artefact of the realtime last bar where q8 ran | historical band A +1, last-bar row +2 |
| H0 | documented replacement, immediate | +1, na(red) yes, light blue |

Band B tests reversed argument order (does `(l2, l1)` count as the same pair?); band C tests whether deleting the
replacement revives the replaced fill (visual). Engine plan per outcome: H0 → P2.3a store unchanged; H1/H3 → the store
keeps a *superseded* linefill entry that `linefill.all` lists (and, for H3, drops at the observed point) but the
renderer skips; H2 → no replacement, both drawn; H4 → P2.3a behaviour historically, the realtime difference recorded
as unexplained. The documented replacement stays the rendering rule unless H2.

## 5. `chart.point` model

Not `DrawingRef`: a chart point has no store, no limit, no GC, no `delete`, is drawn by nobody, is allowed in `varip`
and in `request.security`. Docs group it with collections for `varip` (D11, D12). Two candidate models:

* **M1 collection model (proposed default)** — exactly the P2.2 array model: `ChartPoint(time, index, price)` is a
  mutable Python object shared by every reference inside one execution; each slot stores an immutable
  `PointSnapshot` at the end of the execution and materialises a fresh object at the start. `var` rolls back by
  buffer truncation, `varip` persists (D12) with no extra machinery. Arrays of points snapshot their elements
  (deep, preserving identity between elements of the same array — *policy*).
* **M2 heap model** — a point store with identity across bars and a rollback journal (like `DrawingStore`), with a
  `varip` exemption for points reachable from `varip` slots.

q9 row D1 (`var pb = pa`) and D2 (`var array.from(pc)`) decide: by-value (pb.price = 1) → M1; shared → M2.
Row D3 decides history: `(ph[1]).price` = bar_index−1 → snapshot (M1); = bar_index → live (M2, like drawings).
Case 1 decides writes through history: an error (RE10051-like, text recorded) → read-only historical points; no
error → mutable copy (M1) or live write (M2).

Common to both: fields `time` (int), `index` (int), `price` (float); `p.f := v`, `p.f += v`; field access on an na
point → runtime error with engine wording (*policy*); `copy` → independent object (D7); constructors D7;
`chart.point.now()` without `price` → compile-time gap until verified (*policy*); `==` / `!=` on points → gap;
drawing constructors and point setters copy coordinates at call time (D8: later field changes do not move drawings);
field assignment on other types stays the UDT gap.

## 6. Constructor overloads and defaults (`line.new`, `label.new`, `box.new`)

* Point form: first argument statically typed `chart.point` → point overload; any named argument unique to one form
  (`first_point`, `top_left`, `point` / `x1`, `left`, `x`) selects it; otherwise (na literal, numbers) the x/y form.
  If the analyzer cannot type the first argument, a runtime overload dispatch on the value reuses the P2.3a
  `dispatch` mechanism.
* x from `index` (bar_index xloc) or `time` (bar_time xloc); y from `price`; box: left/top from `top_left`,
  right/bottom from `bottom_right`. A point missing the needed field gives na x (the existing na-coordinate path).
* Defaults, `force_overlay`/font/format restrictions and the v5 label text colour: unchanged from P2.3a. No v5/v6
  difference documented (D15); no v5 oracle.
* Point setters (D9) set both coordinates per the object's current `xloc`.

## 7. Realtime and Replay

* Arrays of drawings: container = P1 truncation, objects = store journal (§2). `*.all` = store view; rollback-safe.
* Points (M1): `var` truncation, `varip` persistence (D12). M2 would need a varip-aware journal.
* Incremental == fresh for `var`; `varip` points differ only when ticks were observed (the P1/P2.2 caveat).
* Replay unchanged: KNOWABLE AT CURSOR; one execution per revealed bar; nothing reads beyond the cursor.

## 8. request.security / request.security_lower_tf

* Arrays of drawings, `*.all`, drawing IDs: rejected (TradingView cannot request drawings, D14; P2.3a slice rule).
* `chart.point` and arrays of points: TradingView accepts them (D14); the engine rejects them as an ENGINE LIMIT,
  exactly like the frozen P2.2 array restriction (documented divergence).
* Frozen P2.1/P2.2/P2.3a restrictions unchanged.

## 9. P2.3b oracle-support tables-core (scope APPROVED; implemented, §17)

**Decision (user, P2.3b scope review):** P2.3b adds a MINIMAL table core so the frozen P2.3 / q9 oracle scripts run
in full at script level without a test-only capture. It is named **"P2.3b oracle-support tables-core"** and is **not**
TradingView table parity; broad table parity is P2.4.

Exact subset used by the frozen P2.3 oracles (q8, q8g r4, q8c, q8e, m07) and q9 — nothing else is in scope:

| item | used form |
|---|---|
| type | `table` variables (`var table t = …`, global) |
| `table.new` | `table.new(position.top_right, columns, rows, bgcolor=, border_color=, border_width=)` — columns 1–2, rows 2–14 |
| `table.cell` | `table.cell(t, column, row, text, text_color=, bgcolor=, text_size=, text_halign=)` (q8c/q8e: `text_color` only) |
| constants | `position.top_right` only; `size.small` and `text.align_left` already exist |
| state | cells written on `barstate.islast` (q8, q8g, q9) or every realtime execution (m07); the table object must follow the P2.3a store rules: created once (`var`), cell writes journaled on the forming bar and rolled back with it (m07 is live) |
| output | run result: per table `position`, grid size, frame styling, and cells `{column,row,text,text_color,bgcolor,text_size,text_halign}`; tests assert cell text |
| frontend | DOM overlay anchored top-right over the price pane; Replay/Live redraw from the payload |

Engine policy inside the subset (not TradingView parity, documented): other `position.*` constants, other
`table.*` functions (`table.delete`, `table.clear`, `table.set_*`, `table.merge_cells`, `table.cell_set_*`),
`table.all`, `frame_*`, `width`/`height`, `text_valign`, `tooltip`, fonts/formatting and non-default `force_overlay`
stay capability gaps (P2.4). Table limits and table GC are not researched; the engine caps tables per script
(ENGINE LIMIT) and never garbage-collects them. Out-of-range `column`/`row` raise an engine-worded runtime error.
Earlier oracles (q1–q6, m03, m06) also use tables; they are not claimed as P2.3b targets even if they happen to fit
the subset.

## 10. Unknowns

| id | question | how resolved |
|---|---|---|
| U-A1 | `*.all` live view or copy at read | q9 row A |
| U-A2 | `var a = label.all` keeps bar-0 contents | q9 row A2 |
| U-A3 | read-only error text | q9 Case 2 |
| U-B1 | objects reached through `held[1]` live and mutable | q9 row B |
| U-C1 | `linefill.all` bookkeeping (H0–H4) | q9 rows C1–C3, E, visual |
| U-C2 | reversed argument order is the same pair | q9 row C2 |
| U-P1 | points shared across `var` slots / arrays across bars (M1 vs M2) | q9 rows D1, D2 |
| U-P2 | `p[1]` of a point: snapshot or live | q9 row D3 |
| U-P3 | writing a field of a historical point | q9 Case 1 |
| U-P4 | default `price` of `chart.point.now()` | not tested (compile risk); gap until verified |
| U-P5 | dead-ID `==`, na-point field errors, `line.all[1]` | engine policy / gap |

## 11. Oracle package

`quick/q9_collections_points.pine`, v6 only (D15: no migration change). Three runs on any chart with more than 60
bars (BINANCE:BTCUSDT 1m): Case 0 (table + one visual answer on bands A and C), Case 1, Case 2 (runtime error text if
any).

### q9 revision 1 — did not compile; no semantic conclusions
Hash `10fdc7302ff62887085c5c7f74a3fe9b80605dccc8e299179ab422553a5afefb`. Real TradingView v6, Case 0: compile failure
at line 60, "Cannot call "operator ==" with argument "expr0"="fa1". An argument of "series linefill" type was used but
a "simple string" is expected. (CE10123)", shown as 1 of 4 problems. The script never executed: nothing about
`linefill.all`, `*.all`, arrays of drawing IDs, `chart.point` or the bands was observed.
Cause: line 60 compared linefill IDs twice (`fa1 == fa2`, `linefill.all.get(n - 1) == fa2`). `==` has no linefill
overload, so each comparison fails (CE10123); the remaining problems are inferred to be the follow-on errors of passing
those untyped results to `yn(bool)` (only the first problem text was reported). Compile fact recorded for the engine:
`==` / `!=` on `linefill` does not compile (CE10123); line `==` does (q8e).

### q9 revision 2 — authoritative, frozen
Hash `ced90e345fab9e1cf5567a218e84a7bc9095828576de7a9f9e945660a0a5e303`. Linefill identity questions are answered
without `==`: `na()` of each fill, `linefill.all` sizes, the number of listed IDs that read na (`deadListed()`), and
line identity through `linefill.get_line1(f) == m1` (line `==`, observed compiling in q8e). The engine parses it with
capability gaps only.

### q9 revision 2 — observed (real TradingView v6), Cases 1 and 2

| case | action (probe bar `last_bar_index - 3`) | observed | conclusion |
|---|---|---|---|
| 1 | `hp = ph[1]; hp.price := -5` (`var chart.point ph`, `ph.price := bar_index` every bar) | completed; `hp.price` −5; `ph.price` −5; fresh `ph[1]` read −5 | a historical chart.point is a reference to the same object: writing through `ph[1]` is allowed and is seen through the alias, the current `ph` and a fresh `ph[1]`. Rules out M1 (by-value per slot) for history; supports **M2** (identity across bars, like `DrawingRef`) (**U-P3** resolved; **U-P2** consistent with "live") |
| 2 | `la = label.all; la.push(label.new(bar_index, low, "X"))` (live labels before: A2, A3) | completed; `la.size()` 3; `label.all.size()` 3 | the array returned by `label.all` is an ordinary mutable array: no read-only error. `label.all.size()` = 3 is A2, A3 and the new X label; pushing into `la` is not inferred to change TradingView's own list (**U-A3** resolved: no error to reproduce) |

### q9 revision 2 — observed (real TradingView v6), Case 0 (as reported by the user from screenshots)

| row | observed | conclusion |
|---|---|---|
| A | `view = label.all` after A1, A2: size 2; after `label.new` A3 still 2; after `label.delete` A1 still 2; `view[0]` a deleted ID; fresh `label.all.size()` 2 | each read of `*.all` is a **snapshot array** of IDs, not a live view; the IDs inside resolve against the live store (**U-A1** resolved) |
| A2 | `var earlyAll = label.all` read on bar 0: size 0 later | a `var` slot keeps the bar-0 snapshot (P2.2 rules) (**U-A2** resolved) |
| B | `held[1]` size 2; `line.set_y1(held[1].get(0), 21)` changed the live line, seen through `held.get(0)` | historical array = the IDs held then; the objects reached through it are live and mutable (**U-B1** resolved) |
| D1, D2 | the `var` alias and the array element shared the point's state across bars | points keep identity across bars, in variables and arrays (**U-P1** resolved: **M2**) |
| D3 | `ph[1]` showed the currently mutated point | history of a point is the same live object (**U-P2** resolved) |
| C1 band A (same pair) | `linefill.all` size before / after 1st / after 2nd: 1 / 2 / 2; `na(red)` false, `na(blue)` false; both return their source line | a second `linefill.new` on a filled pair creates a new valid ID but does **not** add a listed entry: the previous ID is superseded, stays a valid reference with usable getters, and is not listed |
| C2 band B (reversed arguments) | 0 / 1 / 1; `na(first)` false, `na(second)` false | `(l2, l1)` is the same pair as `(l1, l2)`: pair identity is unordered (**U-C2** resolved) |
| C3 band C (orange, teal, teal deleted) | `na(orange)` true, `na(teal)` true | deleting the current fill does not reactivate the previous one and invalidates the pair's superseded fill |
| E (last bar) | not reported | not recorded |
| visual | not usable: other purple drawings were on the chart | unresolved → `q9v` |

Resolved model: `chart.point` follows **M2** (identity across bars and in history; mutable through any reference;
a per-bar rollback journal for `var`-held changes, `varip`-held points exempt per D12). `*.all`: a fresh snapshot
array per read, oldest first, an ordinary mutable array once returned.

### q9v — visual linefill oracle — observed (real TradingView v6)
`quick/q9v_linefill_visual.pine`, SHA-256 `9ad847725bad97bc907c2cf9bfb7f4bf6e2917468824146ee595bafd3c45948f`. Own
pane, no other drawings, created on historical bar `last_bar_index - 5`, 100 bars wide.

| band | calls | observed | conclusion |
|---|---|---|---|
| A (y 60–80) | red, then blue on the same pair | **blue** | only the newer fill is rendered (manual D5); H2 (both drawn) rejected |
| C (y 20–40) | orange, then teal on the same pair, teal deleted | **none** | deleting the replacement does not reactivate the older fill |

**U-C1 resolved (reported by the user from the q9 Case 0 screenshots and q9v):** for one line pair, the newest
`linefill.new` is the pair's single **current** fill — the only one listed in `linefill.all` and the only one
rendered. The previous ID becomes **superseded**: a valid reference (`na` false, getters usable) while the
replacement exists, not listed, not rendered, never reactivated. Deleting the current fill also invalidates the
superseded fill of that pair (q9 C3). Pair identity is unordered (q9 C2). q8 Case 0 (`linefill.all` size 2 after two
calls on one pair, observed on the chart's last bar) is not reproduced by this model; final classification (§18):
"isolated TradingView observation not reproduced by q9/q9v/q10/q11; unresolved oracle/context anomaly". The engine follows the replicated evidence (1 current fill).

## 12. Files (planned)

`pine/values.py` (ChartPoint/PointSnapshot for M1), `pine/builtins/arrays.py` (drawing and point elements,
read-only `*.all`), `pine/builtins/drawings.py` (`*.all`, overloads, point setters), new `pine/builtins/points.py`,
`pine/drawings.py` (ordered listing; linefill bookkeeping per q9), `pine/analyzer.py` (array<drawing>/chart.point
types, `ns.all` receivers, field read/write for chart.point, overload selection, varip rules, security rejection),
`pine/runtime.py` (point snapshots, field assignment, overload dispatch), `pine/slicing.py`, `pine/catalog.py`,
`pine/compat.py` + `COMPATIBILITY.md`; oracle-support tables-core (§9): new `pine/builtins/tables.py`, `pine/outputs.py`, `engine.py`,
`component/protocol.py`, `component/pine_bridge.py`, frontend table overlay + dist rebuild; tests; this file.

## 13. Test plan

* Script-level parity: q8 Cases 0–7, q8g r4 Cases 0–2, q8c, q8e and m07 (simulated ticks) run in full with the §9
  tables-core; the table strings are compared
  with the frozen observations wherever they do not depend on chart data (counts under limits, order, na flags,
  texts); q9 the same once observed.
* Arrays of drawings: element checks, history read-only container + live objects, GC not rooted, dead IDs, copy
  shallow, methods and for…in, varip rejection, realtime rollback (incremental == fresh), oid stability.
* `*.all`: order, read-only error, view/copy per q9, delete/GC/cascade/rollback reflected, Replay at cursor.
* chart.point: constructors, fields, compound assignment, aliasing, M1/M2 per q9, var rollback, varip persistence,
  arrays of points, overloads and point setters (coordinates copied), request.security rejection.
* Tables-core: the subset only; payload validation; rollback of cell writes (m07); gaps for everything else;
  a frontend unit test and the browser test render the overlay.
* Regressions: all P1 / P2.1 / P2.2 / P2.3a suites, frozen-oracle hashes, 4 accepted baseline failures unchanged.

## 14. Gaps after P2.3b

polylines, table API beyond the §9 oracle-support subset (P2.4, incl. `table.all`), `polyline.all`, UDTs, maps, matrices, user methods, non-default fonts/formatting,
`*.all[n]`, array search/sort functions on drawing IDs, `chart.point` in `request.*` (engine limit), dead-ID `==`. Engine rule to add: `==`/`!=` on `linefill` is a
compile error (q9 r1, CE10123).

## 16. Final P2.3b design (approved with corrections; supersedes §2–§9 where they differ; implemented, §17)

### 16.1 Arrays of drawing IDs
As §2: P2.2 container (per-slot snapshot of an immutable tuple of `DrawingRef`s; `a[n]` read-only copy, RE10051;
by-value across slots) holding live IDs (objects reached through `a[n]` are live and mutable — **obs** q9 B).
`array<line|label|box|linefill>`, `T[]`, `array.new<T>`, `array.new_line/label/box/linefill`, `array.from(ids)`;
kind check in `coerce_element`; dead IDs are values (`na()` true). Not GC roots (q8g r3). `copy` shallow.
`varip array<drawing>` → compile error worded after CE10128 (D11). Existing A1–A4 functions/methods and for…in only.

### 16.2 `*.all`
`line.all`, `label.all`, `box.all`, `linefill.all`: `series array<kind>`; every read builds a **new ordinary
(mutable) `PineArray`** of the live IDs of that kind, oldest-created first (**obs** q9 A, Case 2; q8g r3). No
read-only error. Pushing into it never changes the store. `var x = label.all` keeps the snapshot by P2.2 rules
(**obs** q9 A2). `label.all[1]` → compile-time gap. Method receivers: `label.all.size()`, `for id in line.all`.
Rollback, GC, delete, cascade and Replay are reflected because the list is read from the store.

### 16.3 Linefill bookkeeping (q9 C1–C3 + q9v; corrected at design review)
* `pairs[(min, max)]` → the pair's current fill (unordered pair, **obs** q9 C2). `linefill.new` on a pair with a
  current fill marks that fill **superseded** and creates the new current one (**obs** q9 C1: 1/2/2).
* Superseded: stays in the store (`na` false, `get_line1/2` return its lines — **obs** q9 C1), NOT listed in
  `linefill.all`, NOT rendered (**obs** q9v A), never reactivated (**obs** q9v C).
* Deleting the current fill (or its death by cascade) also kills every superseded fill of the pair (**obs** q9 C3).
* Explicit `line.delete` of either source line kills every fill of that line (**obs** q8 Case 4). Garbage collection
  of a source line does **not** (**obs** q11 row G): the fill stays alive (`na` false) and listed, `get_line1/2`
  return the stored, now dead, line ID (`na` true), and it is not rendered (no geometry). Rollback of a line's
  creation undoes its fills' creations through the journal. This corrects P2.3a §15.9 ("dies with either line").
* `linefill.all` = current fills, oldest current first.
* ENGINE POLICY (unobserved): `linefill.set_color` on a superseded ID stores the colour (not rendered);
  `linefill.delete` called directly on a superseded ID removes only that ID; superseded IDs count toward the 500
  engine cap.
* Journal: `supersede` entries are undone by realtime rollback.
* Equality: `linefill == linefill` → compile error **observed** (q9 r1, CE10123, exact text recorded in §11).
  `!=` is rejected too as the same type-level rule — **inferred**, its TradingView wording unverified.
* q8 Case 0 row 6 (size 2, engine 1): "isolated TradingView observation not reproduced by q9/q9v/q10/q11; unresolved oracle/context anomaly" (§18) — not an accepted engine divergence.

### 16.4 `chart.point` (point-object store; **obs** q9 D1–D3, Case 1; corrected at design review)
* Every constructor call (`new`, `now`, `from_index`, `from_time`, `copy`) creates a new point object with its own
  identity (`pid`). Variables, history slots, arrays and aliases hold **references** to point objects: `b = a`
  aliases; an array stores the same reference; `p[n]` returns the reference held n bars ago — the same object as the
  current one only if the variable still holds it (q9 D3 / Case 1), an older independent point if a new point was
  assigned since. `chart.point.copy(p)` → a new independent point with the same values.
* Fields: `time` int, `index` int, `price` float; read `p.f`, write `p.f := v` and compound assignments, through any
  reference including history (**obs** Case 1). Field access on na → engine-worded runtime error.
* `chart.point.now(price = close)`: `now()` → (time, bar_index, close) (reference manual: `price` optional, default
  `close`).
* Drawing constructors and point setters copy the selected coordinates at call time; no live dependency.
* Realtime: field writes on the forming bar are journaled (point, field, old value) in the object journal and undone
  by rollback (`var` / plain state), except writes to points **reachable at rollback time from a `varip` root** (a
  `varip chart.point` slot or an element of a `varip array<chart.point>` slot), which persist (doc D12). Mixed
  aliases: the rule is object-level — a point reachable from any `varip` root keeps all its writes, even when a
  `var` also references it (ENGINE POLICY; the mixed case was not observed). Points created on the forming bar need
  no undo: they vanish with the rolled-back slots unless a `varip` slot holds them.
* `var` / `varip` / arrays of points / `varip array<chart.point>` allowed. `==` / `!=` on points → gap.

### 16.5 Overloads (`line.new`, `label.new`, `box.new`) and point setters
First argument statically `chart.point`, or a named argument unique to a form, selects the point form; otherwise
x/y. Unknown static type → run-time selection on the first argument's value (P2.3a dispatch mechanism). The point
form copies `index` (bar_index xloc) or `time` (bar_time) and `price` at call time (D8). Setters:
`line.set_first_point`, `line.set_second_point`, `label.set_point`, `box.set_top_left_point`,
`box.set_bottom_right_point`. Defaults and v5/v6 differences unchanged from P2.3a.

### 16.6 P2.3b oracle-support tables-core
Exactly §9.

### 16.7 request.security / request.security_lower_tf
Drawing IDs, arrays of drawings and `*.all` rejected (TradingView cannot request drawings). `chart.point` and arrays
of points rejected as an ENGINE LIMIT (TradingView accepts them, D14) — the P2.2 collection boundary. P2.1 / P2.2 /
P2.3a restrictions unchanged.

### 16.8 Documented divergences / policies
* Exact limits (P2.3a §15.18): full-script q8 Case 0 gives `label.all` 50 (TV 52) and `line.all` 500 (TV 504); q8g r4
  gives 5 labels U36–U40 and 5 lines R36–R40 (TV 10: U31–U40, R31–R40). Order, survivors (oldest-created evicted)
  and every other row match (q8g boxes `first B37 B38 B39 B40`, dead-ID rows).
* q8 Case 0 row 6 (`linefill.all` 2) vs engine 1: an **isolated TradingView observation not reproduced by
  q9/q9v/q10/q11; unresolved oracle/context anomaly** (§18). Not an accepted engine divergence; the engine keeps the
  replicated model.
* Line counts under overflow: TradingView q10 C/D showed 502–504 lines alive with `max_lines_count` 500; the engine
  keeps exactly 500 (the P2.3a exact-limit divergence). Linefill counts match exactly.
* Superseded linefills: `set_color`, direct `delete` and the 500 cap (16.3) are ENGINE POLICY.
* Mixed `var` / `varip` aliases of one chart point: object-level `varip` persistence (16.4) is ENGINE POLICY.
* `chart.point` / `array<chart.point>` in `request.*`: rejected, ENGINE LIMIT (TradingView supports them).
* `linefill !=`: rejected like `==` (only `==` observed, CE10123; `!=` wording unverified).
* Tables: only the §9 oracle-support subset; table limit 100 per script (ENGINE LIMIT); out-of-range cells and
  non-default parameters raise engine-worded runtime errors. Not TradingView table parity (P2.4).
* Everything in P2.3a §15.18 is unchanged.

## 17. Implementation status (P2.3b implemented; not committed)

Implemented per §16 and §9: `values.py` (`ChartPoint`, `table` kind), `drawings.py` (superseded linefills,
`listing`, tables, point-write journal with the `varip` exemption), `builtins/arrays.py` (drawing / point elements,
`array.new_line/label/box/linefill`, `array.new<chart.point>`), `builtins/drawings.py` (point overloads and setters,
`*.all`), new `builtins/points.py`, new `builtins/tables.py`, `analyzer.py`, `runtime.py`, `slicing.py`,
`outputs.py`, `compat.py` / `catalog.py` / `COMPATIBILITY.md`, `component/protocol.py`, frontend `drawingGeometry.js`
(`tableLayout`) and `PineLayer.js` (table overlay), rebuilt `dist`.

Tests: `tests/tradingview_mode/pine/test_collections.py` (unit behaviour plus q8 Cases 0–7, q8g r4 Cases 0–2, q8c,
q8e, m07 under simulated realtime, q9 r2 Cases 0–2 and q9v as full scripts), frontend `tableLayout` test, browser
acceptance with a table / `*.all` / point-constructor script in historical, Replay and Live. P2.3a
`test_linefill_replacement_and_cascade` was updated to the corrected superseded model (q9 evidence).

## 18. q8 Case 0 `linefill.all` reconciliation (q9 row 7, q10, q11; engine fix recorded below)

Lifecycle in the frozen q8 source (`01196373…`), Case 0, executed only under `barstate.islast`:

| id | created by | source pair | state at the measurement (`put(6, …)`) under the q9 model |
|---|---|---|---|
| F1 | line 52 `linefill.new(l1, l2, color.red)` | (l1, l2), both created on the same execution (lines 50–51) | superseded by F2 |
| F2 | line 53 `linefill.new(l1, l2, color.blue)` | (l1, l2) | current |

No other `linefill.new` runs in Case 0: the only other call (line 83) is inside Case 4, which does not execute in
Case 0, and nothing in Case 0 deletes l1 or l2 (the only `line.delete` in Case 0 is `line.delete(nl)` with `nl = na`).
l1 and l2 are the two newest lines, so garbage collection (500 lines) cannot remove them: F1/F2 have no dead source.
Case 4 (a separate run) creates one fill on (x, y) and deletes x → 0, consistent with the cascade.

Result: exactly **one** line pair exists, so one-current-fill-per-pair predicts `linefill.all` = 1. TradingView
showed 2. Two different pairs are **not** an explanation. The engine reproduces the q9 model (F1 superseded, F2
current, size 1) both with a historical and with a forming last bar.

The contradiction: the same two calls on one pair gave +1 in q9 band A (historical bar `last_bar_index - 6`, few
lines) and +2 in q8 (the chart's last bar — realtime on a 24/7 BTCUSDT 1m chart — with ~500 lines alive, at the
`max_lines_count` limit). The two runs differ only in those contexts; neither is proven to be the cause.

Smallest additional evidence: **q9 revision 2 Case 0, row 7 "C last bar"** from the run already made (no new
script, no new run if the screenshot shows it). It repeats q8's two calls on the chart's last bar and prints
`isrealtime`, the size before/after and `na()` of both fills. +1 → the last-bar/realtime context is not the cause
(the line-limit context would then need a new oracle); +2 with `isrealtime yes` → realtime last-bar behaviour.


**q9 r2 Case 0 row 7 (reported from the existing screenshot):** last bar, `isrealtime yes`: `linefill.all` 2 → 3
after the two same-pair calls (+1); `na` of both fills no; listed IDs that read na 0. The realtime last bar does not
explain q8's +2. Remaining difference: line-limit / garbage-collection pressure (q8: ~500 lines alive).

**q10 — line-limit oracle (frozen, awaiting one run):** `quick/q10_linefill_line_limit.pine`, SHA-256
`edfd8eecf0f1c4639d5e295a946714adda951b7793aa85f99e4f38be6ef66ef9`. Probes A (no other lines), B (exactly 500 with the
pair), C (after forced collection, pair newest) and D (last bar, 3 more lines then the pair, at the limit), each
reporting lines before the pair, `linefill.all` before / after F1 / after F2, `na` of both lines and both fills, and
`line.all` after. Engine (current model): +1 in every probe.

**q10 — observed (real TradingView v6).** Same-pair replacement added exactly +1 in every probe: A 0/1/1 (0 lines
before the pair, 2 after), B 1/2/2 (498 → 500), C 2/3/3 (502 → 504), D realtime 3/4/4 (501 → 503); all four
`na()` flags "no" everywhere. Line-limit pressure and the realtime bar do not explain q8's +2.

**New discrepancy exposed by q10 (engine ≠ TradingView).** Engine: C 1/2/2, D 2/3/3. The 200 extra lines at
`L-25` garbage-collect probe A's lines (the oldest, not rooted) and the cascade kills A's fills; on TradingView A's
fill was still listed at C and D. Two hypotheses fit: (H-root) lines used by a linefill are protected from garbage
collection; (H-nocascade) a garbage-collected line does not kill its linefill (only explicit `line.delete` does,
q8 Case 4). Not resolved by q10 (line counts on TradingView are approximate).

**q8 Case 0 source inspection (§18 table).** (1) `linefill.all` is read by `put(6, …)` on line 62, after both calls
(lines 52–53) in the same execution. (2) No linefill exists before line 52: the only other `linefill.new` (line 83)
is in the Case 4 branch; `mkBox` / `setTop` make boxes only; nothing is created at initialization. (3) Row 6's value
is `s(array.size(linefill.all))`, no other count. (4) A stale case cannot produce row 6: only Case 0 writes rows 2–10
and a settings change re-runs the whole script. (5) `max_lines_count` / `max_boxes_count` create no objects. One
concrete source difference remains: q8 **discards** both `linefill.new` results (bare statements) with **opaque**
`color.red` / `color.blue`; q9/q10 assigned the results and used 60 %-transparent colors.

**q11 — frozen, awaiting one run:** `quick/q11_linefill_gc_discard.pine`, SHA-256
`101ff02f7fa63f441b254836479fb4eff7d99cc97298d775dfca0a23217e069f`. Row G: pair P + fill PF held only in `var` arrays,
600 unreferenced lines, then `na` of P's lines, PF, `get_line1(PF)`, `linefill.all`, `line.all` (H-root vs
H-nocascade). Rows D1 (q8's exact discarded / opaque form, historical), D2 (assigned, opaque), D3 (q8's form on the
last bar). Engine today: G all na, `linefill.all` 0; D1–D3 +1.

**q11 — observed (real TradingView v6).** Row G: after 600 more lines, `na(P line1)` yes, `na(P line2)` yes,
`na(PF)` **no**, `na(get_line1(PF))` yes, `linefill.all` 1, `line.all` 500 → **H-nocascade**: garbage collection of
a source line does not kill its linefill (explicit `line.delete` does, q8 Case 4). D1 (discarded, opaque) 1/2,
D2 (assigned, opaque) 2/3 with both fills non-na, D3 (realtime last bar, discarded, opaque) 3/4: +1 everywhere.

**Engine fix (P2.3b):** `DrawingStore._kill(drawing, cascade)` — explicit deletion cascades to linefills (and a deleted
current fill takes its pair's superseded fills); garbage collection does not. `render_drawings` skips a linefill
whose source line is no longer alive. Rollback restores a collected line through the journal; the surviving fill is
never re-created or destroyed. After the fix the engine reproduces q10 (0/1/1, 1/2/2, 2/3/3, 3/4/4, all IDs non-na)
and q11 G and D1–D3 exactly.

**Final q8 Case 0 classification:** `linefill.all` = 2 is an isolated TradingView observation not reproduced by
q9/q9v/q10/q11 (twelve controlled probes: historical, realtime last bar, reversed pair, visual, low pressure, exact
limit, overflow, discarded and assigned results, opaque colors) — an unresolved oracle/context anomaly. The frozen
observation stays documented as observed; the engine is not altered to reproduce it and it is not an accepted engine
divergence.

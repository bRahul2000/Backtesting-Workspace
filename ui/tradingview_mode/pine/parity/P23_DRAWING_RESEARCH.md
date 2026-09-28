# P2.3 drawing-object core (line, label, box, linefill) — research and proposed design (not implemented)

Recorded 2026-09-28. Sources: the official Pine v6 manual (*Lines and boxes*, *Text and shapes*, *Fills*, *Execution
model*, *Type system*, *Objects*, *Limitations*, *Other timeframes and data*, *Migration guide to v6*), the current
engine (P1 rollback, P2.1 contexts, P2.2 array snapshots, the render protocol) and the frozen P2.2 lessons. Labels:
**documented** (manual), **unknown** (needs real TradingView, section 10), **engine policy**, **engine limitation**.
Out of scope: tables, polylines, maps, matrices, UDTs, user methods, chart.point.

## 1. Official documentation findings (documented)

**Identity and aliasing.** `line`, `label`, `box`, `linefill` are *reference types*: a variable holds a reference
(an ID) to an object stored elsewhere. Every `*.new()` call creates a new object with a unique ID, so these values are
always "series". `b = a` makes both variables refer to the same object; changes through either are visible through
both. Reassigning a variable (`l := line.new(…)`) does not delete or change the previous object; it still exists and is
drawn. `const` on a drawing variable only prevents reassignment. Reference types are "not compatible with any
arithmetic or logical operators" (`==` on drawing IDs: unknown, U10).

**History.** The manual's own idiom `label.delete(lbl[1])` shows that `x[1]` is the previous bar's **ID** and that it
reaches a live object (it can be deleted). Arrays differed: `a[1]` is a read-only snapshot (P2.2, RE10051). Whether
getters through `x[1]` see the object's current state or a snapshot, and whether setters through `x[1]` are allowed:
unknown (U5, U7e).

**Realtime rollback (Execution model page).** "If a script creates objects on an open bar and does not assign their
references to variables declared with the varip keyword, the rollback process removes those objects." "For objects of
built-in or user-defined types with references assigned to var variables, the rollback process reverts any changes to
those objects that occur on the open bar. The only exception is for UDTs with fields that include the varip keyword."
Rollback "reverts all applicable variables, expressions, and objects to their last committed states as of the previous
bar's close". The committed state is the bar's final execution ("the system commits the script's data for the realtime
bar only after the bar closes"). Not settled: deletions (U2) and the exact tick-by-tick behaviour (U4).

**No `varip` drawing IDs (observed, real TradingView v6, 2026-09-28).** `varip line lineB = line.new(0, 0.0, 1, 0.0)`
does not compile: "Variables with varip modifier cannot have type "series line". (CE10128)". Drawing IDs can never be
kept by `varip`, so the manual's varip exception to object rollback does not apply to line/label/box/linefill: every
object created or changed on the open bar is subject to rollback. The analyzer must reject `varip` for these types
(CE10128-style compile error). U1 and U3 are resolved by this (no varip persistence to design or test).

**Copy.** `line.copy()` / `box.copy()` / `label.copy()` clone an object and all its properties into a new object;
"any changes to the copied line instance do not affect the original".

**Delete.** `*.delete()` removes the object and its drawing. `label.delete(lbl[1])` on the first bar (where `lbl[1]` is
na) is a working idiom: deleting `na` is a no-op. Use after delete and double delete: unknown (U7).

**Linefill.** `linefill.new(line1, line2, color)`; it fills between the two referenced lines and follows their
coordinates automatically; `linefill.set_color`, `linefill.get_line1/get_line2`, `linefill.delete`. "Any pair of line
instances can only have one linefill between them. Successive calls to linefill.new() using the same line1 and line2
arguments will create a new linefill ID that replaces the previous one." (documented; P2.3a implements this
replacement). q8 Case 0 recorded `linefill.all` size 2 after two `linefill.new()` calls on the same pair: an
**unresolved bookkeeping observation** (it does not show that two fills were active and does not disprove the manual),
to revisit with `*.all` in P2.3b. Deleting one of its lines removes the linefill (q8 Case 4).

**Signatures** (v6; both overloads each):
`line.new(first_point, second_point, xloc, extend, color, style, width, force_overlay)` /
`line.new(x1, y1, x2, y2, xloc, extend, color, style, width, force_overlay)`;
`label.new(point, text, xloc, yloc, color, style, textcolor, size, textalign, tooltip, text_font_family, force_overlay,
text_formatting)` / `label.new(x, y, text, …)`;
`box.new(top_left, bottom_right, border_color, border_width, border_style, extend, xloc, bgcolor, text, text_size,
text_color, text_halign, text_valign, text_wrap, text_font_family, force_overlay, text_formatting)` /
`box.new(left, top, right, bottom, …)`; `linefill.new(line1, line2, color)`. Setters return nothing, accept "series"
arguments and modify the object directly; getters return its values; all `set_*`, `get_*`, `copy`, `delete` work as
functions or methods.

**Coordinates.** x is a bar index (`xloc.bar_index`, default) or a UNIX time (`xloc.bar_time`). Objects can extend into
the future. Limits: "Drawings using xloc.bar_index can be positioned a maximum of 10,000 bars in the past" and "a
maximum of 500 bars in the future". A drawing whose properties are na still exists (it counts toward the limits).

**Limits and garbage collection.** Up to 500 lines, 500 labels, 500 boxes per script
(`max_lines_count` / `max_labels_count` / `max_boxes_count`, default ~50); a garbage collector deletes the **oldest**
objects when the total exceeds the limit. Linefill limits are not documented. `line.all`, `label.all`, `box.all` (and
`linefill.all`) are read-only arrays of the IDs of the displayed objects.

**v5 / v6.** The only drawing-specific change: `label.new()`'s default `textcolor` is `color.white` in v6
(`color.black` in v5). No rollback/identity change is documented, so the oracles run in v6 only.

**request.security.** The manual's examples create drawings in the calling context with requested *values*; nothing
documents drawings created inside a requested expression.

## 1b. Real TradingView observations — `manual/m07_live_drawing_rollback.pine` (v6, observed)

BINANCE:BTCUSDT, 1-minute chart, realtime ticks and one bar rollover, as reported by the user. Values are read at the
start of each execution (before it changes anything).

| moment | A.y2 (var line, y2 := exec) | R.text (var label reassigned to a new label) | lines (A + plain creations) | labels | boxes (var box deleted) |
|---|---|---|---|---|---|
| same open bar, tick 1 | 0 | 0 | 1 | 1 | 1 |
| same open bar, tick 2 | 0 | 0 | 1 | 1 | 1 |
| bar 10760 tick 1, exec 1 (its only observed realtime execution) | 0 | 0 | 1 | 1 | 1 |
| bar 10761 tick 1, exec 2 (first execution of the next bar) | 1 | 1 | 3 | 2 | 0 |

**Directly proved by m07:**

1. Before a new execution on the same open bar, every drawing change of the previous execution is rolled back:
   mutations (A), creations (plain lines, the new label), the reassignment of a `var` drawing reference (R) and
   deletions (D, **resolves U2**).
2. An execution's resulting drawing state can become the committed state at bar rollover: bar 10760's execution #1
   left y2 = 1, two plain lines, the reassigned `var` reference (text "1") and the deleted box, and all of it was kept
   when bar 10761 opened (lines 1 → 3, labels 1 → 2, boxes 1 → 0).
3. `varip` drawing IDs are impossible (CE10128), so no object escapes rollback.

**Not discriminated by this sample:** bar 10760 had only one observed realtime execution after the script was
attached (log: `bar 10760 tick 1 exec 1`, then `bar 10761 tick 1 exec 2`). m07 therefore does not by itself show that,
when a bar has several realtime executions, the committed state is the **final** one. That rule rests on the official
execution-model documentation ("The system commits the script's data for the realtime bar only after the bar closes";
rollback "reverts … objects to their last committed states as of the previous bar's close"), not on this rollover
sample. No further m07 run is required.

**Frozen realtime model (approved):** (1) each realtime execution starts from the committed drawing-store and
drawing-reference state; (2) it applies its own creates, mutations, deletions and reassignments; (3) before another
execution on the same open bar those changes are rolled back (observed, m07); (4) the bar's final execution is
committed at bar close (documented Pine execution semantics; m07 shows commitment at rollover with a single
execution); (5) the next bar starts from that committed state. CE10128: `varip` drawing variables are rejected.

## 1c. Real TradingView observations — `quick/q8_drawing_semantics.pine` (v6, observed)

BINANCE:BTCUSDT, 1-minute chart, historical bars, as reported by the user. Cases 0–5 and 7 are the same code in the
original (`97a83c16…`) and the revised (`01196373…`) script; Case 6 is authoritative only from the revised script.

| case | question | observed | conclusion |
|---|---|---|---|
| 0 | alias: set y1 = 55 through `b = a` | original y1 = 55 | assignment aliases one object |
| 0 | copy: set the copy's y1 = 77 | copy 77, original 55 | `line.copy()` is an independent object |
| 0 | history, one `var` line mutated every bar | `h[1]` y2 = 10766 = current `bar_index` | history holds IDs, not snapshots: `h[1]` resolves to the live, mutated object (**U5**) |
| 0 | history, a new line every bar | `p[1]` x1 = 10765 = `bar_index − 1` | `p[1]` is the previous bar's ID |
| 0 | garbage collection, one label per bar, default limit | `label.all` size 52; oldest label x = 0 | raw observation only; the algorithm is not inferred |
| 0 | `linefill.new` twice on the same two lines | `linefill.all` size 2 | unresolved bookkeeping observation: does not show two active fills; the documented replacement stands (revisit with `*.all`, P2.3b) |
| 0 | function-local `var box`, two call sites | `box.all` size 2 | one persistent object per call site |
| 0 | `setTop(b1, 99)` (mutation through a parameter, returns the box) | b1 top 99; returned box top 99; b2 top 21 | a drawing parameter reaches the caller's object; call sites stay separate |
| 0 | `line.delete(na)` | completed | no-op |
| 0 | `line.all` size (h, p lines, al, cp, l1, l2; `max_lines_count = 500`) | 504 | raw observation only; the limit behaviour is not generalised |
| 1 | `get_y1` after `line.delete(x)` | NaN | getter on a deleted ID returns na; no error (**U7**) |
| 2 | `line.delete(x)` twice | second delete completed | deleting a deleted object is a no-op (**U7**) |
| 3 | `set_y1` after delete, then `get_y1` | setter completed; get_y1 NaN | setter on a deleted object is a no-op; it does not resurrect it (**U7**) |
| 4 | delete line1 of a linefill | `linefill.all` size 0; `na(linefill.get_line1(lf))` true | deleting a source line removes/invalidates the linefill; its ID then reads as na (**U8**) |
| 5 | `line.set_y1(p[1], 5)` then `get_y1(p[1])` | completed; 5 | a historical drawing reference is mutable (**U7**) |
| 6 | revised: `line.new(…, last_bar_index + 501, …)` on bar K | RE10020 (section "q8 Case 6") | +500 future limit; beyond is RE10020 |
| 7 | getter on the first label (created on bar 0, assumed garbage-collected) | x = 0 | **inconclusive for GC**: the oracle did not reach a collected ID; the first label's ID still resolves. Not inferred: that TradingView does not collect, that collected IDs read 0, or any GC algorithm |

**Arrays vs drawings (critical):** `a[1]` of an array is a read-only historical copy (mutation → RE10051, P2.2);
`p[1]` of a drawing is a historical **ID** that resolves into the persistent drawing store, and mutation through it is
allowed.

## 2. Current engine assessment

* **Runtime state:** every variable/series is a `SeriesBuffer` of values per bar; `var`/`varip` carry the last value;
  `Runtime.rollback(bar)` truncates non-varip buffers and call-site states. Arrays (P2.2) are execution-local objects
  that slots snapshot at the end of every execution; nothing outlives an execution.
* **Why the array model does not fit:** drawing objects outlive executions and are shared by every reference across
  bars (`x[1]` reaches a live object; reassigning never deletes). They need an object store with stable IDs owned by
  the runtime, and rollback of that store on the realtime bar, driven by the documented rules plus U1–U3.
* **Outputs:** `outputs.py` stores per-bar series (plot family) and `render()` serialises them per payload; its
  docstring already anticipates "a second store of objects created, updated and deleted bar by bar". The frontend
  `PineLayer.js` draws Pine shapes on its own canvas over Lightweight Charts, so line/box/label/linefill primitives fit
  there. The payload is a full snapshot per run (validated by `protocol._validate_pine`).
* **Existing gaps:** every `line.*` / `label.*` / `box.*` / `linefill.*` name is a `drawing-objects` capability gap
  (compat.py). The catalog lacks `box.all` and `linefill.all` (found while parsing the oracles).
* **Method syntax (A3):** built-in method dispatch resolves by the receiver's type; drawing types extend it naturally
  (`line` → `line.*`). A3 sends receivers of unknown type to `array.*`; with drawings that is no longer safe and must
  become "known type → its namespace; unknown type → by the method name when exactly one namespace has it, else a
  diagnostic".

## 3. Proposed drawing object model (engine policy)

* **Value:** `DrawingRef(kind, oid)`: immutable, hashable; `oid` a per-runtime increasing integer, so IDs are stable
  for the life of an execution run and serialise to stable frontend keys. `na` refs allowed.
* **Store:** `DrawingStore` per runtime: `objects: oid → DrawingObject(kind, props, created_bar, alive)`, per-kind
  creation order (for garbage collection and `*.all`), per-kind limits from `indicator()` (`max_*_count`, default 50,
  capped at 500). Linefills reference two lines; a new linefill on the same pair replaces the previous one (doc);
  deleting either line removes its linefill (q8 Case 4). Superseded by section 15.
* **Builtins:** constructors, setters, getters, `copy`, `delete` operate on the store; setters/getters on a deleted
  or na ref follow U7.
* **Variables and history:** `SeriesBuffer`s hold `DrawingRef`s as plain values (no snapshots); `x[1]` returns the
  previous bar's ref, resolved against the live store (q8: getters see the current state, setters are allowed).
* **Rollback journal (realtime):** on the forming bar every store change appends to a journal (create, set property
  with its old value, delete, garbage-collect). `Runtime.rollback(bar)` asks the store to undo the journal back to the
  bar's committed state; with no varip drawing IDs (CE10128) nothing is exempt (m07: mutations, creations, deletions
  and reference reassignments all roll back). At bar commit the journal is cleared (the final execution commits:
  documented; m07 observed commitment at rollover with a single execution). Historical
  bars execute once: no journal. Replay: no rollback (one execution per revealed bar).
* **Reuse:** the store/journal is written generically (kind + property dict), so tables and polylines can join later;
  maps/matrices/UDTs are not assumed to share it until their own oracles.

## 4. Lifecycle model

| operation | model | basis |
|---|---|---|
| create | new oid, alive, counted toward its kind's limit; the oldest alive object of that kind is garbage-collected beyond the limit | documented |
| alias | refs are values; all aliases reach one object | documented |
| mutate | in place on the object; visible through every ref, including history refs (`p[1]` may be mutated) | documented / observed (q8 0, 5) |
| copy | new oid with the same properties; independent afterwards | documented |
| delete | object no longer alive / drawn; `delete(na)` and a repeated delete are no-ops; getters on a deleted ID return na; setters on it are no-ops (no resurrection); deleting a line removes its linefills | observed (q8 0–4) |
| history | `x[n]` = the ref variable's ID n bars ago, resolved against the live store (not a snapshot) | observed (q8 0, 5) |
| rollback | every open-bar change (create, mutate, delete, reassign) rolled back per tick (observed, m07); the final execution committed at bar close (documented); `varip` drawing IDs impossible (CE10128, observed) | observed / documented |

## 5. Realtime model

Each tick: P1 rollback of series and call sites, then `DrawingStore.rollback()` (journal undo per section 4), then
re-execution. At bar close the last execution's store state is committed. Incremental = full recompute holds for
everything not kept by varip (as for P1 scalars and P2.2 arrays).

## 6. Rendering / frontend model (engine policy)

Python stays authoritative; the browser only draws. After each run the payload carries, per script, a **full
snapshot of the alive objects** (bounded by the limits: at most 500 per kind), each with a stable key
(`<script>-<kind>-<oid>`), its kind, resolved coordinates and style. `xloc.bar_index` x-coordinates are converted to
times from the bar times (future bars by the timeframe; past bars beyond the loaded data dropped from display), and
`xloc.bar_time` is passed through. A full snapshot per payload avoids delta bookkeeping and makes replay-cursor changes
and reloads trivially correct; its size is bounded. `PineLayer.js` draws lines (extend left/right/both), boxes
(fill, border, text), labels (styles, text, colors) and linefills (polygon between the two lines' current coordinates) on
its canvas. The payload validator checks kinds, counts ≤ limits and coordinate types.

## 7. request.security restrictions (engine policy; P2.1/P2.2 boundaries unchanged)

Drawing constructors, setters, `delete`, `copy` inside a requested expression or its dependency slice are rejected
(side effects: the existing slicing rule gains the drawing namespaces); a requested expression returning a drawing
ID is rejected. Requested *values* used by drawings in the calling context work as today.

## 8. Replay model (engine policy)

A revealed bar executes once with knowable data only (P2.1/P2.2 rules), so every drawing is the result of executions
up to the cursor; no rollback happens in Replay. Coordinates may point into the future (the script's own output, as
TradingView allows up to +500 bars), but no drawing is created by a bar after the cursor; the validator checks
`created_bar ≤ cursor` for every drawing in a Replay payload.

## 9. Limits: TradingView vs engine

| limit | TradingView (documented) | engine |
|---|---|---|
| lines / labels / boxes per script | 500 each, default ~50, oldest garbage-collected | same (default 50) |
| linefills | no declaration (`max_linefills_count` does not exist); one per line pair, replaced by a later `linefill.new` (doc); removed with a deleted source line (q8) | lifecycle only (replacement, cascade, delete, rollback); an internal safety cap, if any, is an ENGINE LIMIT (section 15) |
| x in the future (`xloc.bar_index`) | +500 bars; beyond is runtime error RE10020 "Objects positioned using xloc.bar_index cannot be drawn further than 500 bars into the future." (observed, q8 Case 6) | same, with the same wording |
| x in the past | 10,000 bars | same |
| drawings in requested expressions | not documented | rejected (section 7) |

## 10. Unknowns requiring real TradingView

| id | question | oracle |
|---|---|---|
| U1 | ~~varip-referenced object mutations~~ — resolved: `varip` drawing IDs do not compile (CE10128) | observed |
| U2 | ~~deletion on the open bar~~ — resolved: rolled back before the next tick, committed at bar close | m07 (observed) |
| U3 | ~~superseded varip objects~~ — resolved: impossible (CE10128) | observed |
| U4 | ~~tick-by-tick rollback and commit~~ — resolved: all changes rolled back per tick (observed); commit of the final execution at bar close (documented; m07 observed commitment with a single execution) | m07 + manual |
| U5 | ~~history: live or snapshot~~ — resolved: IDs resolved against the live store | q8 Case 0 (observed) |
| U6 | ~~garbage collection~~ — resolved: oldest-created evicted in the oracles; IDs in arrays do not protect; a collected ID reads as na, setters/delete are no-ops, no resurrection; kept counts vs `max_*_count` approximate (no formula) | q8g revisions 3–4 (observed) |
| U7 | ~~use after delete~~ — resolved: getter na, setter no-op, repeat delete no-op; setter through `x[1]` allowed | q8 Cases 1, 2, 3, 5 (observed) |
| U8 | ~~linefill~~ — resolved: deleting a source line removes/invalidates the linefill (q8 Case 4); same-pair replacement follows the manual; q8 Case 0's `linefill.all` size 2 kept as an unresolved bookkeeping observation for P2.3b | q8 Cases 0, 4 + manual |
| U9 | ~~`:=` on a drawing parameter~~ — resolved: compile error **CE10175** "Function arguments cannot be mutable ("l")" on `l := line.new(bar_index, 2.0, bar_index + 1, 2.0)`; the parameter still reaches and may mutate the caller's object (q8 Case 0) | q8c (observed) |
| U10 | ~~`==` / `!=` on drawing IDs~~ — resolved: they compile and compare identity (`a == b` true for an alias, `a == copy` false, `a != copy` true); the P2.2 array restriction does not apply | q8e (observed) |

Also recorded by q8 case 0 (documented, confirmed cheaply): aliasing, copy independence, function-local `var` per call
site, mutation through a parameter, returning an ID, `delete(na)`. Case 6 records the +500 limit's error text.

## 11. Oracle package (v6 only; no documented v5/v6 difference besides the label text color)

| script | kind | runs | sha256 |
|---|---|---|---|
| `manual/m07_live_drawing_rollback.pine` (revised: no varip drawing IDs) | realtime, manual | **run (section 1b)** | `ea299e23d857c2672a366a340e26904c36655fa362ca2a8bfd3c7a368b254943` |
| `quick/q8_drawing_semantics.pine` (revised Case 6) | historical, Case input 0–7 | **run: Cases 0–7** (Case 6 authoritative from the revised script) | `01196373e4bea88f89082a162db5184ee14ed036e6d216dd54adfe5da891d700` (original: `97a83c167c88ffe4a4a71396f81e5e91b69405f0b70582bb32bf510473c5cb95`) |
| `quick/q8g_drawing_gc.pine` revision 4 (revision 3 population unchanged; Cases 1–2 now probe the collected R1 line ID) | historical, Case input 0–2 | **run** | `1b583e7ca2c3e73244bf4346b93c914cb0aa8f5c656308b938f20f02ab72620c` (history: revision 1 `71edaf0c…` inconclusive; revision 2 `658e228e…` did not compile; revision 3 `8fb33862…` run, section below) |
| `quick/q8c_drawing_param_reassign.pine` | compile | **run: CE10175** | `45a0226112f2e6effd239bf2f852144b2d43e9f099f2e84c0ea8a746868c7eea` |
| `quick/q8e_drawing_equality.pine` | compile | **run: compiles; identity** | `1f80c78d4c8442e1b2f114f528de1eb1f4efbda18056465344ac4e74229ca99a` |

### q8 Case 6 (future-bar limit) — inconclusive original run

Original Case 6 produced no table and no TradingView diagnostic; no semantic conclusion was drawn. (Setup: Case = 6;
the script stayed attached; no compile error, no runtime error, no readable diagnostic.) The original probe created
`line.new(bar_index, close, bar_index + 501, close)` inside `barstate.islast`, i.e. on the last (realtime) bar, where an
earlier oracle (q6r Case 10) also lost its table without a visible error while the same failure on a historical bar
was reported explicitly (q6n, RE10052). The revised Case 6 runs the probe once on the historical bar
`K = last_bar_index - 3` with `x2 = last_bar_index + 501` (beyond +500 from either the executing bar or the chart's last
bar) and reports success through a `var` string shown by the last-bar table; a failure is reported by TradingView as an
error on bar K. Cases 0–5 and 7 are unchanged.

**Revised Case 6 — observed (real TradingView v6, authoritative):** runtime error **RE10020**: "Error on bar 10779:
Objects positioned using xloc.bar_index cannot be drawn further than 500 bars into the future. at #main():34" (line 34 =
`line.new(bar_index, close, last_bar_index + 501, close)`, bar 10779 = K). The documented +500-bar `xloc.bar_index`
future limit is confirmed directly; exceeding it is a runtime error, RE10020, raised by the creating call.

### q8g revision 1 — inconclusive for U6 (observed)

With `max_labels_count = max_lines_count = 5`, eight labels and eight lines A–H were created on consecutive historical
bars and **every ID was kept in a `var` array**. Case 0 on real TradingView: `label.all` size 8 and `line.all` size 8,
all eight IDs of each type still valid (labels `A*@0 B@-10 C@-20 D@-5 E@-15 F@-25 G@-30 H@-35`; lines y1 1.5, 2 … 8).
Nothing was garbage-collected, so the premise of guaranteed eviction was false; no conclusion is drawn about the
eviction order or about dead IDs, and Cases 1–2 of revision 1 were not run.

Why the declared limit did not force eviction here (hypotheses, **not** conclusions): the manual describes the limit
as approximate ("~50") and as a *display* limit, and the earlier q8 Case 0 counts exceed the declared limits
(`label.all` 52 with the default; `line.all` 504 with 500), while the only label whose ID was kept in a `var`
(created on bar 0) survived among 10,000+ unreferenced ones. Either objects whose IDs are still stored in variables are
not collected, or the collector allows some slack above the limit — or both. Revision 2 separates these: unreferenced
labels, fully referenced lines, and one referenced old box among unreferenced boxes, 40 of each with limits of 5, and
it proves eviction from the `*.all` contents before interpreting the kept box ID.

### q8g revision 2 — did not compile (observed)

Real TradingView v6: "Could not find method or method reference 'id.get_text' (CE10271)" at line 59, the `box.all`
loop: boxes have no text getter. The script did not execute; no garbage-collection semantics were observed and Cases
1–2 were not run. Revision 3 identifies boxes by a unique top coordinate (`box.get_top`) set at creation instead; the
labels (`label.get_text`) and lines (`line.get_y1`) are unchanged.

### q8g revision 3 — observed (real TradingView v6); hash `8fb3386282060f6767916b04f4b1c63808c446edc7ad9fd21f913c655781af04`

Limits 5 for labels, lines and boxes; 40 objects per type created on 40 historical bars; creation order ≠ x order.

| case | population | observed | conclusion |
|---|---|---|---|
| 0 | labels U1–U40, no ID kept | `label.all` size 10: U31 … U40 | garbage collection occurs; U1–U30 collected; the survivors are the newest-created (not the rightmost/leftmost), supporting oldest-created eviction |
| 0 | lines R1–R40, every ID kept in a `var` array | `line.all` size 10; kept IDs readable 10/40; y1 31 … 40 | **IDs stored in an array do not keep objects alive**: R1–R30 collected although their IDs stay in `keptLines` |
| 0 | boxes: `first` held in a `var` box variable + B1–B40 unreferenced | `box.all` size 5: first B37 B38 B39 B40; first: listed, id not na, top 1000 | the directly held `var` box survived while older unreferenced boxes were collected (observed; not generalised) |
| 1 | `box.set_top(firstBox, 2000)` | completed; `box.all` size 5: "B1900" B37–B40; id not na; top 2000 | firstBox alive and mutable. The row "first listed: NO (evicted)" is an **oracle naming artifact** (first is recognised by top = 1000; after the setter it prints as B1900). Not a test of a collected ID |
| 2 | `box.delete(firstBox)` | completed; `box.all` size 4: B37–B40; `na(firstBox)` yes; get_top NaN | explicit deletion: removed from `box.all`, the ID reads as na, getters na. Explicit-delete behaviour, **not** garbage collection |

**Counts vs declared limits.** With every limit declared as 5, ten labels and ten lines survived but five boxes. The
manual promises no exact count: the default limit is "~50" and scripts "only display approximately the last 50
lines"; q8 Case 0 also exceeded declared limits (`label.all` 52 with the default, `line.all` 504 with 500). Recorded:
the limit is approximate and per type; no exact cap rule is inferred (engine policy for P2.3: treat `max_*_count` as
the target and keep the evidence, not a guessed formula).

### q8g revision 4 — observed (real TradingView v6); authoritative hash `1b583e7ca2c3e73244bf4346b93c914cb0aa8f5c656308b938f20f02ab72620c`

The probe reads the line ID R1, which revision 3 proved garbage-collected while its ID stays in `keptLines`.

| case | action on the collected R1 ID | na(deadLine) | get_y1 | `line.all` size before/after | R1 (y1 1 or 999) in `line.all` |
|---|---|---|---|---|---|
| 0 | none | yes | NaN | 10/10 | no |
| 1 | `line.set_y1(deadLine, 999)`: completed | yes | NaN | 10/10 | no |
| 2 | `line.delete(deadLine)`: completed | yes | NaN | 10/10 | no |

**U6 resolved — garbage-collection model (observed):**

* Garbage collection occurs; in these oracles the oldest-created objects were evicted (U1–U30 / R1–R30 collected,
  U31–U40 / R31–R40 kept), independently of their chart position.
* Keeping IDs in an array does not protect objects from collection.
* A kept ID whose object was collected behaves as na: `na(id)` is true, getters return na, setters and `delete` are
  no-ops, nothing resurrects the object, and `*.all` is unchanged by operations on it (the same as an explicitly
  deleted ID, q8 Cases 1–3 and revision 3 Case 2).
* The number of objects kept relative to the declared `max_*_count` is approximate and per type (10 labels and 10
  lines but 5 boxes with limits of 5; 52 labels with the default; 504 lines with 500): recorded as observed, no exact
  formula.
* Observed once, not generalised: a box held directly in a `var` variable survived while older unreferenced boxes
  were collected (revision 3).

### q8c — observed (real TradingView v6)

`q8c_drawing_param_reassign.pine` does not compile: "Function arguments cannot be mutable ("l") (CE10175)" at
`l := line.new(bar_index, 2.0, bar_index + 1, 2.0)`. A drawing parameter refers to the caller's object and can mutate
it (q8 Case 0: `setTop`), but the parameter binding itself is immutable. Engine policy: the analyzer's CE10175 rule
(today for array parameters, P2.2) extends to line/label/box/linefill parameters.

### q8e — observed (real TradingView v6)

`q8e_drawing_equality.pine` compiles. With `line a = line.new(…)`, `line b = a`, `line c = line.copy(a)`: `a == b` true,
`a == c` false, `a != c` true. Drawing IDs support `==` / `!=` as identity comparisons.

**All unknowns U1–U10 are resolved; every oracle above is frozen with its hash.**

## 12. Expected implementation files

`pine/values.py` (DrawingRef), new `pine/drawings.py` (store, journal, garbage collection, limits), new
`pine/builtins/drawings.py` (line/label/box/linefill constructors, setters, getters, copy, delete, constants
`xloc.*`, `yloc.*`, `extend.*`, `line.style_*`, `label.style_*`, `size.*`, `text.align_*`), `pine/runtime.py`
(store per runtime, rollback hook, history of refs), `pine/analyzer.py` (drawing types, method dispatch by type,
U9/U10 rules), `pine/slicing.py` (drawing side effects rejected), `pine/outputs.py` + `pine/engine.py` (drawing
snapshot in the render result), `pine/catalog.py` (`box.all`, `linefill.all`), `pine/compat.py` + `COMPATIBILITY.md`,
`component/protocol.py` (validation), `component/pine_bridge.py`, frontend `chart/PineLayer.js` (+ `pineData.js`),
tests, evidence.

## 13. Test plan

Engine tests reproducing every q8 / m07 observation (m07 via the simulated realtime path used for m04/m05);
lifecycle (create, alias, copy, delete, history, garbage collection, linefill pairing and line deletion); functions
(parameters, local var per call site); method syntax on drawings and the A3 unknown-receiver rule; request.security
rejection; Replay (no drawing from a bar after the cursor; incremental = fresh); payload validation and rendering
(frontend unit tests for coordinates, future bars, extend, linefill polygon); browser test adding a drawing script
(historical, replay, live); all P1/P2.1/P2.2 regressions.

## 14. Risks and compatibility gaps

* `array<line>` and friends (arrays of drawing IDs) and `*.all` are extremely common in real scripts; A1 arrays hold
  primitives only. Proposal: P2.3a = the object core (this document); P2.3b = arrays of drawing refs + `*.all`, once
  the core's reference semantics are frozen (element refs snapshot as IDs, pointing to live objects).
* `chart.point` overloads (`line.new(first_point, …)`, `label.set_point`) need a point type: deferred (gap).
* Rendering fidelity (fonts, label styles, text wrapping) is visual only and not TradingView-pixel-exact.
* The A3 unknown-receiver method rule must change with drawings (section 2).
* Tables and polylines stay gaps; `force_overlay` and `text_formatting` are accepted only with their default values
  until rendered.


## 15. Revised P2.3a object-core design (for review; not implemented)

Labels: **obs** = real TradingView observation (sections 1b, 1c, q8g, q8c, q8e), **doc** = Pine manual, **inferred** =
engine model inferred from an observation (not a proven TradingView specification), **policy** = engine choice.

### 15.1 DrawingRef
`DrawingRef(kind, oid)`: immutable, hashable; `kind` ∈ `line`, `label`, `box`, `linefill`; `oid` from a per-runtime
counter. `na` is the ordinary na value. Frontend key: `<script>:<kind>:<oid>`. *policy*

### 15.2 Object store
Per runtime (never shared with request.security child runtimes):
* `objects: oid → DrawingObject(kind, props: dict, created_bar: int, created_seq: int, alive: bool)`;
* `order[kind]`: alive oids in creation order (`created_seq`);
* `limit[kind]` for line / label / box from `indicator(max_lines_count / max_labels_count / max_boxes_count)`
  (default 50, maximum 500); no declared limit for linefills (section 15.9);
* `pair[(min(l1, l2), max(l1, l2))] → linefill oid` (the pair's active linefill) and `fills_of[line oid] → linefill
  oids` (dependency index);
* `next_oid` counter; `journal` (section 15.7).

### 15.3 Dead / deleted state
Explicit `delete`, garbage collection, linefill replacement and the linefill cascade all set `alive = False` and drop
the object from `order` / display. For a dead or na ID: `na(id)` true, getters return na, setters and `delete` are
no-ops, `copy` returns na (policy), nothing resurrects it (**obs** q8 Cases 1–3, q8g r3 Case 2, q8g r4).

### 15.4 GC roots and eligible oldest-created eviction (**inferred** from q8g r3 and q8 Case 0)
* **Roots:** the current values of scalar `var` variables of drawing types — global `var` declarations and
  function-local `var` declarations (per call site) — that hold a live ID. Nothing else is a root: IDs inside arrays
  are not (q8g r3: R1–R30 collected while kept in a `var` array), historical slots of variables are not, plain
  (non-`var`) variables are not.
* **Eviction:** after a creation makes `alive_count(kind) > limit[kind]`, evict the oldest-created **non-root** alive
  object of that kind (repeat while over the limit and an eligible object exists). If only roots remain, keep them and
  exceed the limit rather than delete a rooted object.
* Reproduces: q8g r3 (`var box firstBox` kept while old unreferenced boxes were evicted; labels/lines oldest-created
  evicted), q8 Case 0 (the `var` first label kept among thousands of unreferenced labels).
* Divergence (documented): the engine applies the declared limit exactly to eligible objects; TradingView retained
  more than declared in the oracles (10 labels / 10 lines with 5; 52 with the default ~50; 504 with 500).

### 15.5 Variables, history, aliasing, equality
* `SeriesBuffer`s hold `DrawingRef`s as plain values; `x[n]` is the ID n bars ago resolved against the live store:
  getters see the current state, setters are allowed (**obs** q8 Cases 0, 5). No snapshots.
* `b = a` shares the object; reassignment never deletes (**obs**, **doc**).
* `==` / `!=` compare `(kind, oid)` identity (**obs** q8e, live IDs). Dead IDs compare by the same rule — **unverified**
  (not observed after delete/GC; no parity claim).

### 15.6 Copy
`line.copy` / `label.copy` / `box.copy`: new oid, same properties, independent (**obs**). No `linefill.copy` in scope.

### 15.7 Realtime rollback journal and counter rollback
* Active only while executing the forming (unconfirmed) bar. Entries `(bar, op, data)`: `create(oid)`, `set(oid, key,
  old)`, `kill(oid, reason)` (delete / GC / replacement / cascade), `pair(old_value)`, and the `next_oid` value at the
  first entry of the bar.
* `Runtime.rollback(bar)` undoes that bar's entries in reverse (restoring properties, reviving killed objects,
  removing created ones, restoring pair/dependency indexes) and restores `next_oid`, so the re-execution recreates the
  same oids. Variables roll back through the existing P1 buffer truncation. Everything rolls back (**obs** m07).
* Commit: when execution moves to the next bar, the previous bar's entries are dropped — its final execution is
  committed (**doc**; m07 observed commitment at rollover for a single-execution bar). Historical and Replay bars
  execute once: no journal. Incremental live runs equal a fresh run on the same bars.
* `varip` drawing variables are rejected at compile time, worded after CE10128 (**obs**).

### 15.8 Functions
Drawing parameters reach and may mutate the caller's object (**obs** q8 Case 0); `:=` on them is a compile error
worded after CE10175 (**obs** q8c). Function-local `var` drawings persist per call site (**obs** q8 Case 0) and are
roots (15.4).

### 15.9 Linefill
* `linefill.new(l1, l2, color)`: if the pair already has an active linefill, that one is killed and replaced by the new
  ID (**doc**; implemented as documented). q8 Case 0's `linefill.all` size 2 stays an unresolved bookkeeping
  observation for P2.3b.
* When either source line dies (delete, GC, rollback of its creation), its linefill dies; `linefill.get_line1/2` of a
  dead linefill return na (**obs** q8 Case 4).
* `linefill.delete`, `linefill.set_color`, `linefill.get_line1`, `linefill.get_line2`; realtime rollback like any
  object. No `max_linefills_count` (it does not exist); ENGINE LIMIT: at most 500 alive linefills per script, beyond
  which `linefill.new` raises "Current Pine engine limit: …" (safety cap, not TradingView parity).

### 15.10 Method dispatch (A3 extended, no P2.2 regression)
* **Known receiver type** (array / line / label / box / linefill): dispatch statically to that namespace.
* **Unknown receiver type:** collect the implemented namespaces that have the method. None → compile error (as A3).
  Exactly one → static dispatch (unchanged A3 behaviour: `x.size()` → `array.size`). Several (e.g. `.copy()`,
  `.delete()`) → a **runtime-dispatched** call: the analyzer binds the arguments for each candidate; at run time the
  receiver's value kind picks the namespace (`PineArray` → array, `DrawingRef(kind)` → kind); na → the chosen
  builtin's na behaviour is not knowable, so it is a no-op returning na for drawing candidates and the A1 na-array
  error for an array-only fallback (policy); a plain scalar → the existing "`id` argument is not an array" style
  runtime error.
* All frozen A3 tests stay green. New regression tests: unknown-type array receiver with a shared name (`mk().copy()`
  returning an array), known line/label/box receivers, a plain scalar receiver (compile error when typed, runtime error
  when untyped), and no namespace shadowing (`array.copy(a)`, `line.copy(l)` and user variables named like namespaces
  keep their A3 meaning).

### 15.11 Rendering payload (raw coordinates; Python authoritative, browser presentation only)
* Per script: `drawings: {lines, labels, boxes, linefills}` = the alive objects after the run (full snapshot, bounded
  by the limits), plus `first_bar_index` (the bar_index of the first bar in the payload).
* Each item keeps Pine semantics: `key`, `xloc` (`bar_index` | `bar_time`), raw `x1`/`x2` (line, box left/right) or `x`
  (label) as given by the script, `y`s, `yloc`, `extend` and style properties; linefills reference their two line keys.
* Frontend: `xloc.bar_index` → logical index `x − first_bar_index` → Lightweight Charts logical coordinate (future
  bars through the chart's logical index space, not by adding timeframe seconds); `xloc.bar_time` → the chart's time
  coordinate; a time between bars is placed by interpolating between neighbouring bars (a documented presentation
  fallback). The validator checks kinds, per-kind counts, numeric raw coordinates, unique keys, `xloc` values and
  linefill references.

### 15.12 request.security
Drawing constructors, setters, `copy`, `delete` in a requested expression or its dependency slice, and requested
expressions returning drawing IDs, are rejected (slicing side-effect rule); P2.1 / P2.2 boundaries unchanged. *policy*

### 15.13 Replay
One execution per revealed bar with knowable data, no journal; drawings exist only from bars up to the cursor; the
validator checks `created_bar ≤ cursor`; coordinates may point up to +500 bars into the future. *policy*

### 15.14 Exact P2.3a builtin list
* **line:** `new(x1, y1, x2, y2, xloc, extend, color, style, width)`, `delete`, `copy`, `set_x1`, `set_y1`, `set_x2`,
  `set_y2`, `set_xy1`, `set_xy2`, `set_xloc`, `set_extend`, `set_color`, `set_style`, `set_width`, `get_x1`, `get_y1`,
  `get_x2`, `get_y2`, `get_price`.
* **label:** `new(x, y, text, xloc, yloc, color, style, textcolor, size, textalign, tooltip)`, `delete`, `copy`,
  `set_x`, `set_y`, `set_xy`, `set_xloc`, `set_yloc`, `set_text`, `set_color`, `set_textcolor`, `set_style`,
  `set_size`, `set_textalign`, `set_tooltip`, `get_x`, `get_y`, `get_text`. Default `textcolor`: white in v6, black in
  v5 (**doc**).
* **box:** `new(left, top, right, bottom, border_color, border_width, border_style, extend, xloc, bgcolor, text,
  text_size, text_color, text_halign, text_valign)`, `delete`, `copy`, `set_left`, `set_top`, `set_right`,
  `set_bottom`, `set_lefttop`, `set_rightbottom`, `set_bgcolor`, `set_border_color`, `set_border_width`,
  `set_border_style`, `set_extend`, `set_text`, `set_text_color`, `set_text_size`, `set_text_halign`,
  `set_text_valign`, `get_left`, `get_top`, `get_right`, `get_bottom`.
* **linefill:** `new(line1, line2, color)`, `delete`, `set_color`, `get_line1`, `get_line2`.
* All of the above as built-in methods where Pine offers them.
* **Constants:** `xloc.bar_index`, `xloc.bar_time`; `yloc.price`, `yloc.abovebar`, `yloc.belowbar`; `extend.none`,
  `extend.left`, `extend.right`, `extend.both`; `line.style_solid/_dotted/_dashed/_arrow_left/_arrow_right/_arrow_both`;
  `label.style_*` (the label styles of the manual); `size.auto/tiny/small/normal/large/huge`;
  `text.align_left/center/right/top/bottom`.
* **Declaration:** `max_lines_count`, `max_labels_count`, `max_boxes_count`.
* `force_overlay`, `text_font_family`, `text_formatting`, `text_wrap`: accepted only at their defaults (others: gap).

### 15.15 P2.3a vs P2.3b
* **P2.3a:** everything in 15.1–15.14.
* **P2.3b:** arrays of drawing IDs (`array<line>` …), `line.all` / `label.all` / `box.all` / `linefill.all` (and the
  q8 Case 0 linefill bookkeeping observation), `chart.point` overloads (`line.new(first_point, …)`, `label.set_point`,
  `box.set_top_left_point`, …).
* **Later:** tables, polylines, UDTs, maps, matrices, user methods; non-default `force_overlay` / fonts / formatting.

### 15.16 Expected files
`pine/values.py` (DrawingRef); new `pine/drawings.py` (store, roots, GC, journal, linefill pairs/cascade); new
`pine/builtins/drawings.py` (15.14); `pine/builtins/core.py` (`na()` of drawing IDs); `pine/runtime.py` (store per
runtime, rollback/commit hooks, runtime-dispatched method calls, var-slot roots); `pine/analyzer.py` (drawing types,
CE10128, CE10175 extension, `==`/`!=` on drawings, method dispatch 15.10); `pine/slicing.py` (drawing side effects);
`pine/outputs.py` + `pine/engine.py` (drawing snapshot, `first_bar_index`); `pine/catalog.py` (`box.all`,
`linefill.all` names for diagnostics); `pine/compat.py` + `COMPATIBILITY.md`; `component/protocol.py`,
`component/pine_bridge.py`; frontend `chart/PineLayer.js` (+ `pineData.js`); tests; evidence.

### 15.17 Test plan
* One engine test per frozen observation: m07 (simulated ticks/rollover via PineExecution: mutation, creation,
  deletion, reassignment rollback; commit; stable oids across ticks; incremental = fresh); q8 Cases 0–7; q8g r3 (roots:
  `var` box kept, array-held lines and unreferenced labels evicted oldest-created) and r4 (GC-dead = deleted);
  q8c (CE10175); q8e (identity); CE10128; RE10020.
* Linefill: documented replacement, cascade on line delete/GC/rollback, engine cap.
* Method dispatch regressions (15.10) and all frozen A3 tests.
* request.security rejection; Replay (`created_bar ≤ cursor`, incremental = fresh); payload validation (raw
  coordinates, xloc, keys, references); frontend unit tests (logical-index mapping incl. future bars, bar_time
  mapping/interpolation, extend, linefill polygon); a browser test (historical, replay, live).
* All P1 / P2.1 / P2.2 regressions and frozen-oracle hash tests.

### 15.18 Intentional TradingView divergences (documented)
* Exact limit for eligible objects vs TradingView's approximate retained counts.
* GC roots = current scalar `var` drawing variables: inferred from q8g r3 / q8 Case 0, not a proven reachability rule.
* Same-pair linefill replacement follows the manual; q8 Case 0's `linefill.all` size 2 unresolved (P2.3b).
* Dead-ID `==` / `!=` unverified.
* Engine linefill cap (500 alive) — engine limit.
* `xloc.bar_time` between bars rendered by interpolation (presentation fallback).
* Engine wording for errors not observed on TradingView (past-bar limit, wrong receiver types).

### 15.19 Implementation guardrails (approved with the design)
1. **Test scope.** The q8 / q8g oracle scripts use arrays of drawing IDs and `*.all` (P2.3b), so they cannot run as
   scripts in P2.3a. P2.3a reproduces their frozen observations through store, runtime and analyzer tests; full
   script-level q8/q8g parity is a P2.3b requirement. q8c, q8e and the m07 behaviour are exercised directly.
2. **Dead objects are not stored.** The live store holds live objects only. Deletion, GC, linefill replacement and the
   cascade remove the object; its `DrawingRef` stays a valid opaque value in variables, history and aliases
   (`na(ref)` true, getters na, setters/delete no-ops). Only the realtime journal keeps a removed object's full prior
   state, until the bar commits; nothing accumulates after commit. Identity comparison uses the `DrawingRef` alone
   (dead-ID equality stays unverified).
3. **`copy(dead) → na` is an engine policy**, not a TradingView observation (compatibility gap; policy test).
4. **Coordinates.** `xloc.bar_index`: x ≥ `bar_index − 10000` (documented; engine wording) and x ≤ `bar_index + 500`
   (RE10020 wording, observed). `line.get_price(id, x)` works only for `xloc.bar_index` lines and extrapolates the
   line's price beyond its endpoints; an `xloc.bar_time` line is an engine runtime error.
5. **Unknown method receivers at run time:** array → `array.*`; `DrawingRef(kind)` (live or dead) → `kind.*` (the
   builtin then applies dead-ID semantics); a bare untyped `na` cannot resolve an ambiguous method such as `.copy()` →
   a deterministic engine runtime error (engine wording); frozen A3 behaviour otherwise unchanged.
6. **GC target exclusion (engine policy):** the object being created is not evicted by its own creation (it cannot
   be a root yet, since assignment happens after the call); the count may then exceed the target. `linefill.new`
   with a dead or na source line returns na (engine policy).

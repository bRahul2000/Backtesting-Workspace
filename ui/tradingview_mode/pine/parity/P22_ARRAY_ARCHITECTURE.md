# P2.2 arrays — runtime architecture specification (frozen for implementation review)

Derived from real TradingView evidence only: `P22_ARRAY_EVIDENCE.md` (m04, m05, q5, q5b–q5e). Where the
evidence is silent the specification says **UNKNOWN** and the behaviour must be established by its own oracle
before it is implemented. Nothing here is implemented yet.

## The model in one paragraph

Arrays are ordinary mutable objects **inside one execution**. Persistence across executions is **by value,
per slot**: at the end of every execution each persistent slot (and each array value kept for history) stores
an immutable snapshot of the array it currently references; at the start of an execution a slot is
materialised as a fresh, independent array from its own snapshot. The existing P1 buffer rollback then gives
exactly TradingView's realtime behaviour: `var` slots fall back to the committed snapshot, `varip` slots keep
the latest one. No object ever outlives an execution.

## Specification

1. **Execution-local mutable array objects.** `PineArray(element_type, items, readonly=False)`. Every
   reference obtained during one execution (variables, parameters, expressions, return values) points to the
   same Python object, so mutations are visible through all of them.

2. **Persistent slot snapshots.** A `var`/`varip` slot's `SeriesBuffer` stores, per bar, either `na` or an
   immutable `ArraySnapshot(element_type, items: tuple)`. During an execution the slot's current entry holds
   the live `PineArray`; **at the end of the execution** the runtime replaces it with the snapshot of the array
   the slot references at that moment (m05 C: the varip alias keeps S+1; m05 D: the varip origin keeps a push
   made through the var alias).

3. **`var` on historical bars.** Bar *n* materialises a new array from bar *n−1*'s snapshot, mutates it, and
   snapshots it at the end. Two slots initialised from each other are independent from the next execution on
   (q5 Q1).

4. **`varip` on historical bars.** Identical to `var` (one execution per historical bar).

5. **Realtime `var` rollback.** Unchanged P1 rollback: re-running the forming bar truncates `var` buffers to
   the committed bar, so every tick materialises the committed snapshot (m04 A, m05 A/C origin/D alias). The
   committed snapshot of a bar is the one taken at the end of that bar's **last execution** (m04 F, m05 bar
   9516). An engine that sees an extra execution at bar close must commit that one instead (not observed).

6. **Realtime `varip` persistence.** `varip` buffers are not truncated; each execution overwrites the bar's
   entry with its end-of-execution snapshot, so the next tick materialises it (m04 B/E/E2, m05 B, C alias,
   D origin). Objects created during a realtime execution survive exactly when a `varip` slot references them at
   the end of that execution (m04 E/E2).

7. **Same-execution aliasing.** `x = a`, `x := a`, passing `a` to a function: all share the object for the
   rest of the execution (q5 Q2/Q2b/Q8, m05 "after push").

8. **`:=` reassignment.** Rebinds the slot to another object for the rest of the execution; the slot's
   end-of-execution snapshot is of the new target (m05 C/D).

9. **Function parameter mutation.** Parameters receive the caller's reference; mutations are visible to the
   caller (q5 Q8).

10. **Forbidden parameter rebinding.** `:=` on an **array** parameter is a compile error worded after CE10175
    ("Function arguments cannot be mutable (`prm`)."). Scalar parameters: UNKNOWN (P1 currently accepts
    `:=` on scalar parameters; not changed without evidence).

11. **`array.copy()`.** A new independent `PineArray` with a shallow copy of the items (q5 Q9). For primitive
    elements shallow = deep; object elements: UNKNOWN.

12. **Historical array references.** `a[n]` (n ≥ 1) returns a **read-only** `PineArray` materialised from the
    snapshot stored for bar −n (q5b). Every mutating array builtin on a read-only array raises a runtime error
    worded after RE10051 (q5c). RE10051 says slices of historical arrays are read-only too; `array.slice`
    itself is UNKNOWN until tested.

13. **History buffer representation.** Every array-valued variable or history-referenced expression keeps
    snapshots per bar in its existing `SeriesBuffer` (non-`var` arrays included: `nv[1]` is the previous bar's
    array, q5b). Snapshots are taken at the end of the execution (the value the variable had when the bar
    ended). Optimisation allowed: keep snapshots only for slots that are persistent or history-referenced, up
    to the history depth actually used.

14. **Function-local call-site state.** Function-local `var`/`varip` arrays are slots keyed by the existing
    `(ctx_path, node_id)` call-site keys, so each call site persists independently (q5 Q7).

15. **Allocation and object ids.** No Pine-visible identity exists: array `==`/`!=` does not compile (q5d)
    and there is no id API. Ids therefore need not be stable across executions; objects are simply Python
    objects. The analyzer rejects `==`/`!=` between arrays at compile time.

16. **Garbage and lifetime.** Objects live for one execution. Anything not snapshotted by a slot or a history
    buffer at the end of the execution is unreachable and collected by Python. Persistent state exists only as
    immutable snapshots.

17. **Nested arrays / object elements.** UNKNOWN. Pine does not allow `array<array<T>>` directly; arrays of
    user-defined types are P2.5. No semantics are assumed.

18. **Drawings, maps, matrices, user-defined types.** NOT covered. Drawings have global side effects
    (`*.all`, maximum counts, rendering) and may follow different rules; maps and matrices need their own
    realtime and historical oracles. Array semantics must not be generalised to them.

## Global object heap and rollback log — re-evaluated

**Not required for arrays.** The earlier proposal (a heap with stable ids and an undo log replayed on rollback)
assumed objects persist across executions. The evidence shows they do not: every persistent slot is restored
from its own value at the start of an execution, so there is never a shared long-lived object to roll back.
P1's existing buffer truncation plus end-of-execution snapshots reproduces m04, m05 and q5 completely. The heap
and undo log are dropped from the array design. They may be reconsidered for drawings only if the drawing
oracles require them.

Consequences for existing invariants: `incremental == full recompute` holds exactly as for P1 scalars — `var`
arrays are identical; `varip` arrays legitimately differ when ticks were observed (the same caveat P1 already
documents for `varip` scalars).

Performance note: materialising and snapshotting are O(size) per persistent array per execution. A lazy
copy-on-write materialisation (share the snapshot tuple until the first mutation) is a pure optimisation and
may be added later without any semantic change.

## Interactions

* `request.security()` (P2.1): unchanged; arrays remain rejected in security slices.
* `request.security_lower_tf()`: returns a new execution-local array (or a tuple of arrays) per chart-bar
  execution in the calling runtime; when stored in a `var`/`varip` slot it follows rules 2–6; `ltf[1]` follows
  rule 12. Its mapping and realtime content are UNKNOWN until its own oracle.
* Replay: one execution per revealed bar, no rollback: rules 3–4 apply. Live: rules 5–6.

## Minimal implementation order (array portion of P2.2)

1. `PineArray`, `ArraySnapshot`, read-only flag; end-of-execution snapshot of persistent / history slots;
   materialisation on load; read-only materialisation for `[n]`; rollback unchanged. Acceptance: deterministic
   engine tests reproduce every recorded m04 / m05 / q5 observation (simulated ticks and bar transitions).
2. Analyzer: `array<T>` and `T[]` types, `array.new<T>()` generics; the CE10175-style error for array
   parameters; compile-time rejection of array `==`/`!=`; arrays removed from the capability gaps for what is
   implemented.
3. Array builtins, first the ones the oracles exercise (`new_*`, `new<T>`, `from`, `size`, `push`, `pop`,
   `shift`, `unshift`, `get`, `set`, `first`, `last`, `copy`, `clear`) with RE10051 enforcement; then the rest,
   each confirmed by a parity checker.
4. `for … in` (after its oracle).
5. Builtin method syntax (`a.push(x)` → `array.push(a, x)`).
6. `request.security_lower_tf()` (after its oracle).

## Open real-TradingView questions

Blockers (must be answered before the named feature is implemented):

* **`for … in`:** does the loop see pushes/removals made to the array during the loop (v5 and v6)? What does
  `for [i, x] in a` do if the array shrinks? What happens for an `na` array?
* **`request.security_lower_tf()`:** which intrabars a chart bar's array contains (historical mapping, sizes
  at data gaps, empty arrays); whether the forming realtime chart bar includes the still-forming intrabar;
  behaviour beyond the intrabar limit; tuple results.

Not blocking (testable once the basic runtime exists, with parity checkers):

* v6 negative indices in `get`/`set`/`insert`/`remove` (and v5 behaviour); out-of-bounds, empty `pop`/`shift`
  and `na`-array error codes and texts; `array.new_float(n, init)` defaults; aggregates and `sort` with `na`
  elements; `array.slice` view semantics and read-only slices; the element limit; `str.tostring(array)`.
* `varip` array history (`b[1]`) during realtime executions.
* Whether CE10175 also applies to scalar parameters (P1 accepts `:=` on them today).
* Whether any symbol/timeframe shows an extra execution at bar close (two transitions observed without one).
* Method-syntax resolution edge cases (user variables shadowing namespace names, methods on read-only history
  arrays, chaining).
* Maps, matrices, drawings and user-defined types (their own oracles, later phases).

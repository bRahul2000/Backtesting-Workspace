# P2.2-A2 `for … in` — real TradingView evidence

Recorded 2026-09-27/28. Every observation below was produced by **real TradingView** running the q6 oracle scripts
(`quick/q6*.pine`) and reported by the user; nothing here is engine output. The oracle scripts are frozen (hashes
in section 6; `tests/tradingview_mode/pine/test_for_in.py` checks them). **Status: FROZEN** — the model in section 5
is what P2.2-A2 implements.

## 1. Main script `quick/q6_for_in_v5.pine` / `q6_for_in_v6.pine` — Pine v5 and v6 identical

| row | case | observed (v5 = v6) |
|---|---|---|
| Q1 | `for x in [10,20,30]` | iterations 3, sequence `10 20 30` |
| Q1b | `[10,20,30]`, `array.set(a, 0, 999)` in the 1st iteration (after `x` was bound) | sequence `10 20 30`; array after `[999 20 30]` |
| Q2 | `for [i, x] in [10,20,30]` | `0:10 1:20 2:30` |
| Q3 | `[10,20,30,40]`, `array.set(a, 2, 99)` in the 1st iteration | iterations 4, sequence `10 20 99 40`; array after `[10 20 99 40]` |
| Q9 | empty array | 0 iterations |
| Q12 | outer `[1,2]` (`x`), inner `[10,20]` (`y`) | `1/10 1/20 2/10 2/20` |
| Q13 | `[1..5]`, `continue` on 2, `break` on 4 | recorded `1 3` |
| Q14a | iterate `copy`, mutate original (set [1]=77, push 8) | sequence `1 2 3`; original `[1 77 3 8]`; copy `[1 2 3]` |
| Q14b | iterate original, mutate `copy` (set [1]=77, push 8) | sequence `1 2 3`; original `[1 2 3]`; copy `[1 77 3 8]` |

Established:

1. The loop variable is bound to the element's **scalar value** at the start of each iteration (Q1b).
2. Later elements are read **live** from the iterated array object, by index (Q3): `for … in` is not a
   snapshot-of-values iterator.
3. `[i, x]` yields the 0-based index and the element (Q2); `break`/`continue` behave as in other loops (Q13);
   nested loops with distinct names behave normally (Q12); an empty array runs 0 times (Q9).
4. A copy and its original are independent while one of them is being iterated (Q14a/b).
5. No v5/v6 difference in any of these cases.

## 2. Runtime companion `quick/q6r_for_in_runtime_v6.pine` / `_v5.pine` — Pine v6 and v5 identical

| case | setup | observed (v6 = v5 unless noted) |
|---|---|---|
| 4 | `[1,2,3]`, `array.push(a, 4)` in the 1st iteration | completed; 4 iterations; sequence `1 2 3 4`; array after `[1 2 3 4]` (v5) |
| 5 | `[1,2,3,4]`, `array.pop(a)` in the 1st iteration | completed; 3 iterations; sequence `1 2 3`; array after `[1 2 3]` (v5) |
| 7 | `for [i, x] in [1,2,3,4,5]`, `array.remove(a, 3)` when `i == 1` | completed; 4 iterations; sequence `0:1 1:2 2:3 3:5`; array after `[1 2 3 5]` (v5) |
| 10 | `array<int> a = na; for x in a` | v6 only, **inconclusive** (the table disappeared, no error was visible on that chart); superseded by `q6n` (section 3) |

Established (v6 and v5):

6. The iteration count follows the array's **current** size: the header re-reads the size before every
   iteration. Growing adds iterations (Case 4); shrinking ends the loop early **without an error** (Cases 5, 7).
7. The `[i, x]` form uses the same rule; `i` keeps counting 0, 1, 2 … and `x` is read live at index `i`
   (Case 7: after removing index 3, index 3 holds 5).
8. This matches the official Pine documentation (Loops page, `for…in`): "When a `for…in` loop changes the size of
   a collection during an iteration, the loop's header uses the _updated size_ to control subsequent iterations."

Derived, not run (fully determined by 2 + 6 above, so no extra TradingView run was requested):

* **Q6 shift** `[1,2,3,4]`, shift in the 1st iteration: x = 1, then index 1 → 3, index 2 → 4, size 3 stops the loop:
  3 iterations, `1 3 4`, array `[2 3 4]`.
* **Q8 clear** `[1,2,3,4]`, clear in the 1st iteration: 1 iteration, `1`, array `[]`.

## 3. Companions `q6n`, `q6e`, `q6c_x`, `q6c_i`, `q6d` — Pine v6

| oracle | setup | observed (v6) |
|---|---|---|
| `q6n_for_in_na_v6` | `array<int> a = na`, `for x in a` on one historical bar | **runtime error RE10052**: "Error on bar 5544: Cannot call array methods when id of array is na. at #main():26" (line 26 = the `for x in a` line) |
| `q6e_for_in_reassign_v6` | `a = [1,2,3]`; `a := [7,8,9,10]` in the 1st iteration | completed; 3 iterations; sequence `1 2 3`; `a` after `[7 8 9 10]` |
| `q6c_i_for_in_assign_i_v6` | `for [i, x] in [10,20,30]`: `i := i + 10` | **compile error CE10174**: Variable "i" cannot be mutable |
| `q6c_x_for_in_assign_x_v6` | `for [i, x] in [10,20,30]`: `x := x * 2` | **compile error CE10174**: Variable "x" cannot be mutable |
| `q6d_for_in_shadow_v6` | `for x in [1,2]` / nested `for x in [10,20]` | compiled, no visible warning; `outer 1: 10 20 \| after inner 1; outer 2: 10 20 \| after inner 2` |

Established (v6):

9. An `na` array stops the script with RE10052 at the `for … in` line; it is **not** zero iterations.
10. The iterated array object is bound when the loop is entered; reassigning the variable inside the loop does not
    redirect the running loop (the variable itself does change).
11. Both loop variables are read-only (CE10174), in the `[i, x]` form; the single-name form is the same variable kind.
12. Nested loops may reuse a loop-variable name: the inner one shadows the outer one, which is visible again after
    the inner loop.

## 4. Pine v5 — runs waived

The v5 runs of `q6n`, `q6e`, `q6c_x`, `q6c_i` and `q6d` were not made:

* Every `for … in` runtime case run in both versions (main q6, q6r Cases 4, 5, 7) matched exactly.
* The official v6 migration guide lists **no** change to `for…in`, loop variables, scoping, shadowing or `:=` rules.
  Its only loop change concerns the `for` loop's `to_num` (fixed in v5, re-evaluated in v6), which P1 already
  implements as `Runtime.dynamic_for_end`. It does not apply to `for…in`: the q6r v5 runs show the size is
  re-read in v5 as well.
* The v6 observations are therefore applied to v5. A v5-specific difference, if ever observed, becomes a
  version-gated rule like `lazy_bool` and `dynamic_for_end`.

## 5. Frozen `for … in` model (implemented by P2.2-A2)

1. `for x in a` / `for [i, x] in a`: the array expression is evaluated **once**, when the loop is entered, and the
   loop keeps that object (10).
2. `na` array → runtime error RE10052 at the loop line; a non-array type is a compile error.
3. Before every iteration the loop compares its index (0, 1, 2 …) with the array's **current** size; it stops when
   the index reaches the size. Growing adds iterations, shrinking ends the loop early without an error (6, 7).
4. Each iteration binds `x` to the element read live at that index (the value at that moment, 1, 2) and `i` to the
   index.
5. `i` and `x` are read-only (CE10174-style compile error, including compound `+=` etc.) (11).
6. Loop variables live in the loop's own scope: they shadow outer names and disappear after the loop (12).
7. `break` / `continue` as in other loops; an empty array runs zero times (3).
8. Arrays keep every P2.2-A1 rule (P22_ARRAY_ARCHITECTURE.md): mutations inside the loop are ordinary mutations of
   a shared execution-local object; iterating `a[n]` iterates a read-only historical copy (mutating it is RE10051).
9. The loop limit (100,000 iterations per loop) and the array element limit also stop endless growth.

Derived, not run: Q6 shift and Q8 clear (section 2). Engine-only wording: the non-array compile error and the loop
limit text. Not covered: maps and matrices (not implemented; loops over them are capability gaps).

## 6. Oracle scripts (SHA-256)

| script | sha256 |
|---|---|
| `quick/q6_for_in_v5.pine` | `731e24000075d0b498b941f97634814223288295c0c5f0a8238e7205ed8e313c` |
| `quick/q6_for_in_v6.pine` | `9bd7b620ef599bbd6c10dbe21c2ceacce6ad1ff5cd11964789dda07ff63023bf` |
| `quick/q6r_for_in_runtime_v5.pine` | `708880226b160a1f1da959c1010a5bb213954d2014009d21d2ce5e935f9b609b` |
| `quick/q6r_for_in_runtime_v6.pine` | `f907af961fc436a11cca995c8753cfeeb134fb090a2f06f6d3386cf1ba7874ee` |
| `quick/q6c_x_for_in_assign_x_v5.pine` | `0c3095c4059907b0491e43835b04e971ce93f48f333ab91bad583331060648c1` |
| `quick/q6c_x_for_in_assign_x_v6.pine` | `2e1415121010b705ccc23dc149ee29c26cb16a7b827a94305dd92ef22fa40b9f` |
| `quick/q6c_i_for_in_assign_i_v5.pine` | `c9fcfa8123968a99ece340f63f10f88d9d370b1aa84c595eed50b2064a4194b2` |
| `quick/q6c_i_for_in_assign_i_v6.pine` | `d438c681f11dd3e5c456eaa982650f41eeff67ead19c38a5d7645446943ada01` |
| `quick/q6d_for_in_shadow_v5.pine` | `2a18c694eb9bc6062ab23f9ff653935787b1fadfb22d2ba8cb68031f73f14274` |
| `quick/q6d_for_in_shadow_v6.pine` | `fbca715b96049a33295cde59b33c71858f2f67944bda1da096d2c040098b307d` |
| `quick/q6e_for_in_reassign_v5.pine` | `89fd8c1d5ac846b82875751bd7b77f5b7724fcaa472402f2b17d5ae9d2f55498` |
| `quick/q6e_for_in_reassign_v6.pine` | `8923ce9cf01a21ff351058da521b32374997241b91d52f72d71e83432573507c` |
| `quick/q6n_for_in_na_v5.pine` | `d1504d630cd781a60e4b75b2879521a6765d785af99acadb7e52a9d26a71dd5a` |
| `quick/q6n_for_in_na_v6.pine` | `97078766330d3f952fc4474e4d36248ba33ecd96249040709fcedfe4c10fc96d` |

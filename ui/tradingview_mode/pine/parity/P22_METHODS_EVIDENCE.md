# P2.2-A3 built-in array method syntax — evidence

Recorded 2026-09-28. **No real TradingView run was needed**: the official Pine documentation settles the semantics,
and every behaviour the method form can have is already recorded, on real TradingView, for the equivalent
namespace call (P22_ARRAY_EVIDENCE.md, P22_FORIN_EVIDENCE.md).

## 1. Official documentation

| source | statement |
|---|---|
| Pine v6 manual, *Methods* (tradingview.com/pine-script-docs/language/methods/) | built-in methods exist for most special types, including `array`; "the expressions `<namespace>.<functionName>([paramName =] <objectName>, …)` and `<objectName>.<functionName>(…)` are equivalent" (example: `array.get(id, index)` ≡ `id.get(index)`) |
| Pine v5 manual, *Methods* (tradingview.com/pine-script-docs/v5/language/methods/) | built-in methods exist for all special types, including `array`; same equivalence; chaining example `srcArray.copy().fill(1.0, 0.0, min, val).avg()` |
| Pine v6 manual, *Arrays* | examples in method form (`a.size()`, `a.push(value)`); calling functions on an `na` array ID is a runtime error |

## 2. What follows for the engine

1. The method form is **syntactic sugar**, in v5 and v6: `a.f(args)` is `array.f(a, args)`. The receiver is the
   first (`id`) argument, and there are no other semantic differences.
2. Every implemented `array.*` builtin with an `id` first parameter therefore has a method: `size`, `get`, `set`,
   `push`, `pop`, `shift`, `unshift`, `first`, `last`, `copy`, `clear`, `remove`. (`new_*` / `from` have no receiver.)
3. Any receiver expression works: variables (`var`, `varip`, local, parameters, `for … in` variables), call results
   (`a.copy().size()`, chaining), and history references (`a[1].size()`). Because the form is equivalent, mutating
   `a[1]` through a method is RE10051 (q5c), calling a method on an `na` array fails as the namespace call does, and
   `a[1].copy()` is a mutable copy (RE10051's own advice).
4. Namespace and method forms can be mixed freely; they are the same call.
5. Type checking is the namespace builtin's: the receiver's type is checked as the `id` argument.

## 3. Engine-only decisions (not TradingView observations)

* A method on a primitive value (`close.size()`) is a compile error ("Could not find method `size()` for a
  `float` value."), and an unknown method on an array is a compile error. The wording is this engine's own.
* Chaining a method onto a call that returns nothing (`a.push(1).size()`) is a compile error.
* An `array.*` function that is not implemented yet is the same capability gap in either form (`a.sort()`).
* Receivers whose type the analyzer cannot know (a user function's result, an untyped parameter) are dispatched to
  `array.*`, because arrays are the only values with built-in methods in this engine today; a non-array value then
  fails at run time with the builtin's "`id` argument is not an array" error. This must be revisited when maps,
  matrices or drawing objects are implemented.
* User-defined `method` declarations remain a gap (P2.5).

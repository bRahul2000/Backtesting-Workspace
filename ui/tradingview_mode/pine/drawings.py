"""Drawing objects (P2.3a): the per-runtime object store (see parity/P23_DRAWING_RESEARCH.md §15).

* Objects live here; variables, history and aliases hold ``DrawingRef``s. The store keeps LIVE objects only: delete,
  garbage collection, linefill replacement and the linefill cascade remove the object (its ref then reads as na,
  getters na, setters/delete no-ops — TradingView q8 / q8g).
* Garbage collection (inferred from q8g r3 / q8 Case 0): creating an object beyond its kind's limit removes the
  oldest-created object that is not a ROOT (the current value of a scalar ``var`` drawing variable, global or
  function-local); rooted objects are kept even above the limit, and the object being created is never evicted by its
  own creation. IDs held elsewhere (arrays, history, plain variables) do not protect.
* Realtime rollback (m07): while the forming bar executes, every change is journaled (creation, property change with
  its old value, removal with the full object) together with the ID counter; rolling the bar back undoes the journal,
  so a re-executed tick recreates the same IDs. The journal is dropped when the next bar starts (commit), so removed
  objects never accumulate.
* Linefills (P2.3b, q9 C1-C3 + q9v): one CURRENT linefill per unordered line pair. A new ``linefill.new`` on the
  pair makes the previous one SUPERSEDED: still a valid ID (getters work) but neither listed in ``linefill.all`` nor
  rendered, and never reactivated. Deleting the current fill also removes the pair's superseded fills. Explicitly
  deleting either of its lines kills a linefill (q8 Case 4); garbage collection of a line does NOT (q11 row G): the
  fill stays alive and listed, its getters return the dead line's ID, and it is not rendered.
* Tables (P2.3b oracle-support tables-core): stored like drawings (rollback included), never garbage-collected.
* Chart points are not stored here (they are plain objects held by reference), but their field writes on the forming
  bar are journaled here too, so that rollback undoes them except for points reachable from ``varip`` roots.
"""
from __future__ import annotations

from bisect import insort
from dataclasses import dataclass
from typing import Callable

from .errors import PineRuntimeError
from .values import NA, DrawingRef

DEFAULT_LIMIT = 50                  # TradingView: "~50" when max_*_count is not declared
MAX_LIMIT = 500
LINEFILL_ENGINE_LIMIT = 500         # ENGINE LIMIT (TradingView has no max_linefills_count)
TABLE_ENGINE_LIMIT = 100            # ENGINE LIMIT (table limits were not researched; P2.4)
LIMITED_KINDS = ("line", "label", "box")


@dataclass
class Drawing:
    kind: str
    oid: int
    props: dict
    created_bar: int
    superseded: bool = False        # a linefill replaced by a newer one on the same pair (P2.3b)


class DrawingStore:
    def __init__(self, limits: dict[str, int] | None = None, roots: Callable[[], set] | None = None):
        self.limits = {kind: DEFAULT_LIMIT for kind in LIMITED_KINDS}
        self.limits.update(limits or {})
        self.roots = roots or (lambda: set())
        self.live: dict[int, Drawing] = {}
        self.order: dict[str, list[int]] = {kind: [] for kind in ("line", "label", "box", "linefill", "table")}
        self.pairs: dict[tuple[int, int], int] = {}          # line pair -> its current linefill
        self.fills_of: dict[int, set[int]] = {}              # line -> linefills using it
        self.next_oid = 1
        self._journal: list | None = None
        self._journal_bar: int | None = None
        self._start_oid = 1
        self.next_pid = 1                                    # chart.point identities (repr / diagnostics only)
        self._start_pid = 1

    # -- lifecycle: journal, rollback, commit -------------------------------------------------------------------------
    def begin(self, bar: int, record: bool) -> None:
        """Start executing ``bar``. A journal of an earlier bar is dropped (that bar is committed); ``record`` journals
        this execution so that it can be rolled back (the forming / last bar)."""
        if self._journal_bar is not None and self._journal_bar != bar:
            self._journal, self._journal_bar = None, None
        if record and self._journal is None:
            self._journal, self._journal_bar = [], bar
            self._start_oid, self._start_pid = self.next_oid, self.next_pid

    def rollback(self, bar: int, keep_points=frozenset()) -> None:
        """Undo every change journaled on ``bar`` or later: the store returns to its committed state. Field writes to
        the chart points whose ``id()`` is in ``keep_points`` (reachable from ``varip`` roots) persist (manual)."""
        if self._journal is None or self._journal_bar is None or self._journal_bar < bar:
            return
        for entry in reversed(self._journal):
            op = entry[0]
            if op == "create":
                self._remove(self.live[entry[1]])
            elif op == "set":
                self.live[entry[1]].props[entry[2]] = entry[3]
            elif op == "supersede":
                drawing = self.live[entry[1]]
                drawing.superseded = False
                self.pairs[_pair(drawing)] = drawing.oid
            elif op == "point":
                if id(entry[1]) not in keep_points:
                    setattr(entry[1], entry[2], entry[3])
            else:                                           # "kill": restore the removed object
                self._insert(entry[1])
        self.next_oid, self.next_pid = self._start_oid, self._start_pid
        self._journal, self._journal_bar = None, None

    def _log(self, entry: tuple) -> None:
        if self._journal is not None:
            self._journal.append(entry)

    # -- access -------------------------------------------------------------------------------------------------------
    def get(self, ref) -> Drawing | None:
        if not isinstance(ref, DrawingRef):
            return None
        drawing = self.live.get(ref.oid)
        return drawing if drawing is not None and drawing.kind == ref.kind else None

    def alive(self, ref) -> bool:
        return self.get(ref) is not None

    def listing(self, kind: str) -> list[DrawingRef]:
        """``line.all`` / ``label.all`` / ``box.all`` / ``linefill.all``: the live (for linefills: current) objects of
        ``kind``, oldest-created first (TradingView q8g r3, q9 A / C1)."""
        return [DrawingRef(kind, oid) for oid in self.order[kind] if not self.live[oid].superseded]

    # -- changes ------------------------------------------------------------------------------------------------------
    def create(self, kind: str, props: dict, bar: int) -> DrawingRef:
        if kind == "linefill" and len(self.order["linefill"]) >= LINEFILL_ENGINE_LIMIT:
            raise PineRuntimeError(f"Current Pine engine limit: at most {LINEFILL_ENGINE_LIMIT} linefills can exist at "
                                   "the same time.", 0)
        if kind == "table" and len(self.order["table"]) >= TABLE_ENGINE_LIMIT:
            raise PineRuntimeError(f"Current Pine engine limit: at most {TABLE_ENGINE_LIMIT} tables can exist at the "
                                   "same time.", 0)
        oid = self.next_oid
        self.next_oid += 1
        drawing = Drawing(kind, oid, props, bar)
        self._insert(drawing)
        self._log(("create", oid))
        if kind in self.limits:
            self._collect(kind, exclude=oid)
        return DrawingRef(kind, oid)

    def set(self, ref, key: str, value) -> None:
        drawing = self.get(ref)
        if drawing is None:
            return                                          # na / deleted / collected: a no-op (q8 Case 3, q8g r4)
        self._log(("set", drawing.oid, key, drawing.props.get(key)))
        drawing.props[key] = value

    def delete(self, ref) -> None:
        drawing = self.get(ref)
        if drawing is not None:                             # na / already dead: a no-op (q8 Cases 0, 2)
            self._kill(drawing, cascade=True)

    def copy(self, ref, bar: int):
        drawing = self.get(ref)
        if drawing is None:
            return NA                                       # ENGINE POLICY (not observed on TradingView)
        return self.create(drawing.kind, dict(drawing.props), bar)

    def linefill(self, line1, line2, props: dict, bar: int):
        if not (self.alive(line1) and self.alive(line2)):
            return NA                                       # ENGINE POLICY: no fill without two live lines
        previous = self.pairs.get((min(line1.oid, line2.oid), max(line1.oid, line2.oid)))
        if previous is not None and previous in self.live:
            drawing = self.live[previous]                   # q9 C1/C2 + q9v: the unordered pair's current fill is
            drawing.superseded = True                       # superseded (valid ID, not listed, not rendered)
            self._log(("supersede", previous))
        return self.create("linefill", {"line1": line1.oid, "line2": line2.oid, **props}, bar)

    def point_set(self, point, field: str, value) -> None:
        """A chart.point field write, journaled on the forming bar (see ``rollback``)."""
        self._log(("point", point, field, getattr(point, field)))
        setattr(point, field, value)

    def new_pid(self) -> int:
        pid = self.next_pid
        self.next_pid += 1
        return pid

    def _kill(self, drawing: Drawing, cascade: bool) -> None:
        """Remove ``drawing``. ``cascade``: an explicit deletion, which also removes the linefills of a deleted line
        (q8 Case 4); garbage collection passes False and leaves them alive (q11 row G)."""
        self._remove(drawing)
        self._log(("kill", drawing))
        if drawing.kind == "line" and cascade:
            for fill in sorted(self.fills_of.get(drawing.oid, ())):
                if fill in self.live:
                    self._kill(self.live[fill], cascade=True)
        elif drawing.kind == "linefill" and not drawing.superseded:
            l1, l2 = drawing.props["line1"], drawing.props["line2"]   # q9 C3: the pair's superseded fills go too
            for fill in sorted(self.fills_of.get(l1, set()) & self.fills_of.get(l2, set())):
                if fill in self.live and self.live[fill].superseded:
                    self._kill(self.live[fill], cascade=True)

    def _collect(self, kind: str, exclude: int) -> None:
        ids = self.order[kind]
        limit = self.limits[kind]
        if len(ids) <= limit:
            return
        roots = self.roots()
        for oid in list(ids):                               # oldest-created first
            if len(ids) <= limit:
                break
            if oid == exclude or oid in roots:
                continue
            self._kill(self.live[oid], cascade=False)       # q11 G: a collected line leaves its linefills alive

    # -- indexes ------------------------------------------------------------------------------------------------------
    def _insert(self, drawing: Drawing) -> None:
        self.live[drawing.oid] = drawing
        insort(self.order[drawing.kind], drawing.oid)
        if drawing.kind == "linefill":
            l1, l2 = drawing.props["line1"], drawing.props["line2"]
            if not drawing.superseded:
                self.pairs[_pair(drawing)] = drawing.oid
            self.fills_of.setdefault(l1, set()).add(drawing.oid)
            self.fills_of.setdefault(l2, set()).add(drawing.oid)

    def _remove(self, drawing: Drawing) -> None:
        del self.live[drawing.oid]
        self.order[drawing.kind].remove(drawing.oid)
        if drawing.kind == "linefill":
            l1, l2 = drawing.props["line1"], drawing.props["line2"]
            key = _pair(drawing)
            if self.pairs.get(key) == drawing.oid:
                del self.pairs[key]
            for line in (l1, l2):
                fills = self.fills_of.get(line)
                if fills is not None:
                    fills.discard(drawing.oid)
                    if not fills:
                        del self.fills_of[line]

    # -- output -------------------------------------------------------------------------------------------------------
    def objects(self) -> list[Drawing]:
        """Live objects in creation order."""
        return [self.live[oid] for oid in sorted(self.live)]


def _pair(linefill: Drawing) -> tuple[int, int]:
    """The unordered line pair of a linefill (q9 C2: `linefill.new(l2, l1)` is the same pair as `(l1, l2)`)."""
    l1, l2 = linefill.props["line1"], linefill.props["line2"]
    return min(l1, l2), max(l1, l2)

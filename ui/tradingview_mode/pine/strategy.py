"""TradingView-style broker emulator for Pine strategies (P3.1; see parity/P31_STRATEGY_RESEARCH.md).

SIMULATION ONLY. Nothing here talks to a broker: orders, fills, positions and P&L are hypothetical values computed
from the chart's OHLC data. There is no code path from this module to MT5, Exness, Binance order endpoints, webhooks
or alerts.

Model (DOC = TradingView manual, "Strategies" page; POLICY = this engine's choice where TradingView is not documented):

* Orders created by an execution at a bar's close can fill from the next tick: the open of the next bar (DOC).
  ``process_orders_on_close`` lets orders created at the close fill on that same closing tick (DOC).
* Historical intrabar path (DOC): open -> high -> low -> close if the open is closer to the high than to the low,
  otherwise open -> low -> high -> close (a tie is treated as "not closer to the high": POLICY). Price-based orders
  fill anywhere inside a bar's range; an order crossed by a gap between bars fills at the next bar's open (DOC).
* Market orders fill on the next tick at that tick's price (DOC); slippage moves market and stop fills against the
  order (DOC for the direction; which order classes get it: POLICY - market and stop, not limit).
* strategy.entry reverses an opposite position by adding its size (DOC); pyramiding caps open trades from
  strategy.entry, checked when the order is placed (DOC notice: price orders placed on one tick all fill).
* strategy.exit: per-trade brackets (limit / stop / trailing) that reserve quantity in call order and cancel each
  other (OCA) inside one call (DOC); without from_entry a call persists for every trade until the position closes;
  with from_entry it binds to entries of that ID created on or before the call's bar (DOC). Exits close trades FIFO
  (DOC). Relative vs absolute levels: v5 prefers the absolute one, v6 the one triggered first (DOC, v6 migration).
* Trailing stop (DOC): activation at trail_price or entry +/- trail_points ticks; once active the stop follows the
  best price reached by trail_offset ticks and triggers when the price comes back to it. The best price is tracked
  along the intrabar path above (POLICY where the manual only says "the bar's high or low").
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import copy
import math

from .errors import PineRuntimeError
from .values import NA, is_na

LONG, SHORT = 1, -1
FIXED, CASH, PERCENT_OF_EQUITY = "fixed", "cash", "percent_of_equity"
COMMISSION_PERCENT, COMMISSION_PER_CONTRACT, COMMISSION_PER_ORDER = "percent", "cash_per_contract", "cash_per_order"
OCA_NONE, OCA_CANCEL, OCA_REDUCE = "none", "cancel", "reduce"
EPS = 1e-9
QTY_STEP = 1e-6                      # default-size orders are truncated to this step: OBS q13 on BINANCE:BTCUSDT.P
                                     # only; ENGINE POLICY for every other instrument
MAX_EVENTS_PER_BAR = 10_000          # ENGINE LIMIT: a runaway intrabar event loop stops the script


@dataclass(frozen=True)
class StrategySettings:
    initial_capital: float = 1_000_000.0
    default_qty_type: str = FIXED
    default_qty_value: float = 1.0
    pyramiding: int = 1
    commission_type: str = COMMISSION_PERCENT
    commission_value: float = 0.0
    slippage: int = 0
    process_orders_on_close: bool = False
    backtest_fill_limits_assumption: int = 0
    margin_long: float = 0.0          # v5 default 0, v6 default 100 (v6 migration guide)
    margin_short: float = 0.0
    version: int = 5


@dataclass
class Order:
    seq: int
    id: str
    kind: str                          # entry | order | close | close_all
    direction: int
    qty: float | None                  # None: the strategy's default size, fixed when the order is placed
    limit: float | None = None
    stop: float | None = None
    oca_name: str | None = None
    oca_type: str = OCA_NONE
    comment: str | None = None
    created_bar: int = 0
    triggered: bool = False            # stop-limit: the stop was reached, the limit is now working
    from_entry: str | None = None      # close: the entry ID to close
    qty_percent: float | None = None   # close

    @property
    def is_market(self) -> bool:
        return self.limit is None and self.stop is None


@dataclass
class ExitCommand:
    seq: int
    id: str
    from_entry: str | None
    created_bar: int
    qty: float | None
    qty_percent: float | None
    profit: float | None
    limit: float | None
    loss: float | None
    stop: float | None
    trail_price: float | None
    trail_points: float | None
    trail_offset: float | None
    comment: str | None = None
    comment_profit: str | None = None
    comment_loss: str | None = None
    comment_trailing: str | None = None
    bound_orders: set = field(default_factory=set)     # from_entry: entry-order seqs created on/before the call bar


@dataclass
class Trade:
    uid: int
    entry_id: str
    direction: int
    qty: float
    entry_price: float
    entry_bar: int
    entry_time: int
    entry_order: int                   # seq of the entry order
    entry_comment: str | None
    commission: float                  # entry commission still attributed to the open quantity
    max_runup: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class ClosedTrade:
    number: int
    entry_id: str
    direction: int
    qty: float
    entry_price: float
    entry_bar: int
    entry_time: int
    entry_comment: str | None
    exit_id: str
    exit_price: float
    exit_bar: int
    exit_time: int
    exit_comment: str | None
    exit_kind: str                     # market | close | reversal | limit | stop | trail | margin_call
    commission: float
    profit: float                      # net: price move minus entry and exit commission
    max_runup: float
    max_drawdown: float


@dataclass
class Fill:
    bar: int
    time: int
    order_id: str
    kind: str                          # entry | exit | reversal | order | close | margin_call
    exit_kind: str | None
    direction: int                     # +1 buy / -1 sell
    qty: float
    price: float
    position_after: float
    comment: str | None


@dataclass
class _State:
    """Everything that realtime rollback restores (copied as a whole at the start of the forming bar)."""
    seq: int = 0
    trade_uid: int = 0
    orders: list = field(default_factory=list)
    exits: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    closed: list = field(default_factory=list)
    fills: list = field(default_factory=list)
    consumed: set = field(default_factory=set)          # (exit id, trade uid) brackets that already filled
    trails: dict = field(default_factory=dict)          # (exit id, trade uid) -> best price after activation
    netprofit: float = 0.0
    grossprofit: float = 0.0
    grossloss: float = 0.0
    commission_paid: float = 0.0
    wins: int = 0
    losses: int = 0
    evens: int = 0
    peak_equity: float = 0.0
    max_drawdown: float = 0.0
    trough_equity: float = 0.0
    max_runup: float = 0.0
    max_held_long: float = 0.0
    max_held_short: float = 0.0
    equity_curve: list = field(default_factory=list)    # (bar, equity at close)
    history: dict = field(default_factory=dict)         # bar -> state visible to the script on that bar
    margin_calls: int = 0
    closed_peak: float = 0.0                            # highest closed-trade equity (OBS: strategy max drawdown)
    closed_trough: float = 0.0


class Broker:
    def __init__(self, settings: StrategySettings, data):
        self.settings = settings
        self.data = data
        self.state = _State(peak_equity=settings.initial_capital, trough_equity=settings.initial_capital,
                            closed_peak=settings.initial_capital, closed_trough=settings.initial_capital)
        self._saved: tuple[int, _State] | None = None
        self.bar = -1

    # -- lifecycle: realtime rollback ---------------------------------------------------------------------------------
    def begin(self, bar: int, record: bool) -> None:
        if self._saved is not None and self._saved[0] != bar:
            self._saved = None
        if record and self._saved is None:
            self._saved = (bar, copy.deepcopy(self.state))

    def rollback(self, bar: int) -> None:
        if self._saved is not None and self._saved[0] >= bar:
            self.state = copy.deepcopy(self._saved[1])

    # -- helpers ------------------------------------------------------------------------------------------------------
    @property
    def mintick(self) -> float:
        return self.data.mintick or 0.01

    def tick(self, price: float, mode: str = "nearest") -> float:
        """A price on the symbol's tick grid (OBS Donchian 2019-2020 bars, which Binance quotes with 2 decimals while
        the tick is 0.1): market fills and excursions use the nearest tick; stop levels round away from the market
        ("up" for buy stops, "down" for sell stops)."""
        step = self.mintick
        units = price / step
        n = math.floor(units + 1e-7) if mode == "down" else math.ceil(units - 1e-7) if mode == "up" \
            else math.floor(units + 0.5)
        return round(n * step, 10)

    def _next_seq(self) -> int:
        self.state.seq += 1
        return self.state.seq

    def _time(self, bar: int) -> int:
        return int(self.data.time[bar])

    def position(self) -> float:
        return sum(t.qty * t.direction for t in self.state.trades)

    def _direction(self) -> int:
        p = self.position()
        return 0 if abs(p) < EPS else (LONG if p > 0 else SHORT)

    def avg_price(self):
        trades = self.state.trades
        qty = sum(t.qty for t in trades)
        return NA if qty < EPS else sum(t.entry_price * t.qty for t in trades) / qty

    def open_profit(self, price: float) -> float:
        return sum((price - t.entry_price) * t.direction * t.qty for t in self.state.trades)

    def equity(self, price: float) -> float:
        return self.settings.initial_capital + self.state.netprofit + self.open_profit(price)

    def _commission(self, qty: float, price: float, order_fill: bool = True) -> float:
        s = self.settings
        if s.commission_value <= 0:
            return 0.0
        if s.commission_type == COMMISSION_PERCENT:
            return qty * price * s.commission_value / 100.0
        if s.commission_type == COMMISSION_PER_CONTRACT:
            return qty * s.commission_value
        return s.commission_value if order_fill else 0.0

    def default_qty(self, price: float) -> float:
        """Default order size at ``price``. OBS q13 (BINANCE:BTCUSDT.P): cash sizing divides by the FILL price
        (slippage included) and truncates the quantity to 6 decimals. ENGINE POLICY: the same step for other
        instruments, and the same rule for percent_of_equity."""
        s = self.settings
        if s.default_qty_type == FIXED:
            return s.default_qty_value
        if price is None or is_na(price) or price <= 0:
            return 0.0
        if s.default_qty_type == CASH:
            raw = s.default_qty_value / price
        else:
            raw = self.equity(price) * s.default_qty_value / 100.0 / price
        return math.floor(raw / QTY_STEP + 1e-6) * QTY_STEP

    # -- commands (called by the strategy.* built-ins during an execution) ------------------------------------------
    def _replace_or_add(self, order: Order) -> None:
        orders = self.state.orders
        for index, existing in enumerate(orders):
            if existing.id == order.id and existing.kind == order.kind:
                orders[index] = replace(order, seq=existing.seq)       # same ID: the pending order is modified
                return
        orders.append(order)

    def entry(self, bar: int, close: float, id: str, direction: int, qty, limit, stop, oca_name, oca_type,
              comment) -> None:
        if qty is not None and (is_na(qty) or qty <= 0):
            raise PineRuntimeError(f"strategy.entry(): the quantity must be greater than 0 (got {qty}).", 0)
        same_direction = [t for t in self.state.trades if t.direction == direction]
        if same_direction and len(same_direction) >= self.settings.pyramiding:
            # DOC: after the pyramiding limit, new strategy.entry orders are not executed. An existing pending order
            # with this ID is left as it was.
            return
        # a default size (qty None) is computed when the order fills, from the fill price (OBS q13)
        self._replace_or_add(Order(self._next_seq(), id, "entry", direction, qty, limit, stop, oca_name, oca_type,
                                   comment, bar))

    def order(self, bar: int, close: float, id: str, direction: int, qty, limit, stop, oca_name, oca_type, comment) -> None:
        if qty is not None and (is_na(qty) or qty <= 0):
            raise PineRuntimeError(f"strategy.order(): the quantity must be greater than 0 (got {qty}).", 0)
        self._replace_or_add(Order(self._next_seq(), id, "order", direction, qty, limit, stop, oca_name, oca_type,
                                   comment, bar))

    def close(self, bar: int, id: str | None, qty, qty_percent, comment, immediately: bool) -> None:
        trades = self.state.trades if id is None else [t for t in self.state.trades if t.entry_id == id]
        if not trades:
            return                                                     # DOC: no open position -> no order
        kind = "close_all" if id is None else "close"
        name = "Close position order" if id is None else f"Close entry(s) order {id}"      # OBS q12 S1 / S13
        order = Order(self._next_seq(), name, kind, 0, None if is_na_or_none(qty) else qty,
                      comment=comment, created_bar=bar, from_entry=id,
                      qty_percent=None if is_na_or_none(qty_percent) else qty_percent)
        if immediately:
            self.state.orders.append(order)
            self._fill_market(order, bar, self.data.close[bar], immediate=True)
            return
        self._replace_or_add(order)

    def exit(self, bar: int, command: ExitCommand) -> None:
        for index, existing in enumerate(self.state.exits):
            if existing.id == command.id and existing.from_entry == command.from_entry:
                # same exit ID: the command is updated in place (keeps its reservation order and bindings)
                command.seq, command.bound_orders = existing.seq, existing.bound_orders
                if command.from_entry is not None:
                    command.bound_orders |= self._entry_orders(command.from_entry)
                self.state.exits[index] = command
                return
        command.seq = self._next_seq()
        if command.from_entry is not None:
            command.bound_orders = self._entry_orders(command.from_entry)
            if not command.bound_orders:
                return                                                 # DOC: an unknown from_entry creates nothing
        self.state.exits.append(command)                               # without from_entry: also the next position

    def _entry_orders(self, entry_id: str) -> set:
        bound = {t.entry_order for t in self.state.trades if t.entry_id == entry_id}
        bound |= {o.seq for o in self.state.orders if o.kind in ("entry", "order") and o.id == entry_id}
        return bound

    def cancel(self, id: str | None) -> None:
        if id is None:
            self.state.orders = []
            self.state.exits = []
            return
        self.state.orders = [o for o in self.state.orders if o.id != id]
        self.state.exits = [e for e in self.state.exits if e.id != id]

    # -- broker processing of one bar ---------------------------------------------------------------------------------
    def path(self, o: float, h: float, l: float, c: float) -> list[float]:
        return [o, h, l, c] if abs(h - o) < abs(o - l) else [o, l, h, c]

    def process_bar(self, bar: int, final: bool = True) -> None:
        """Fill the orders working during ``bar`` along its intrabar path (before the script executes on it)."""
        self.bar = bar
        d = self.data
        o, h, l, c = float(d.open[bar]), float(d.high[bar]), float(d.low[bar]), float(d.close[bar])
        if any(math.isnan(v) for v in (o, h, l, c)):
            self._record(bar, c)
            return
        points = self.path(o, h, l, c)
        # first tick: market orders placed at the previous close, then price orders crossed by the gap to the open
        for order in [x for x in self.state.orders if x.is_market]:
            if order in self.state.orders:
                self._fill_market(order, bar, o)
        self._events(bar, o, o)
        for a, b in zip(points, points[1:]):
            self._events(bar, a, b)
        self._record(bar, c)

    def after_execution(self, bar: int) -> None:
        """process_orders_on_close (DOC): orders placed at this close fill on the same closing tick."""
        c = float(self.data.close[bar])
        if self.settings.process_orders_on_close and not math.isnan(c):
            for order in [x for x in self.state.orders if x.is_market]:
                if order in self.state.orders:
                    self._fill_market(order, bar, c)
            self._events(bar, c, c)
        self._mark(bar, c)

    # -- intrabar events ----------------------------------------------------------------------------------------------
    def _events(self, bar: int, a: float, b: float) -> None:
        """Walk the price from ``a`` to ``b`` (a == b: a single tick) filling every order the move reaches, nearest
        first; the state is re-read after each fill (new exits, cancelled or reduced orders)."""
        price, count = a, 0
        up = b >= a
        while True:
            count += 1
            if count > MAX_EVENTS_PER_BAR:
                raise PineRuntimeError("Current Pine engine limit: too many order events on one bar.", 0)
            self._advance_trails(price)
            self._excursions(price)
            event = self._next_event(price, b, up)
            if event is None:
                self._advance_trails(b)
                self._excursions(b)
                return
            level, action = event
            price = level
            self._advance_trails(price)
            self._excursions(price)
            action(price)

    def _excursions(self, price: float) -> None:
        """Per-trade run-up / drawdown along the intrabar path while the trade is open (OBS q12 S2: an exit on the
        way up stops the run-up at the exit price)."""
        price = self.tick(price)
        for trade in self.state.trades:
            move = (price - trade.entry_price) * trade.direction
            trade.max_runup = max(trade.max_runup, move)
            trade.max_drawdown = max(trade.max_drawdown, -move)
        self._equity_extremes()

    def _equity_extremes(self) -> None:
        """OBS q12/q13/q14: strategy max drawdown = the peak of closed-trade equity minus (closed equity + the open
        trades' drawdowns so far, net of their entry commission); max run-up symmetrically from the trough."""
        s = self.state
        closed = self.settings.initial_capital + s.netprofit
        low = closed - sum(t.max_drawdown * t.qty + t.commission for t in s.trades)
        high = closed + sum(t.max_runup * t.qty - t.commission for t in s.trades)
        s.max_drawdown = max(s.max_drawdown, s.closed_peak - low)
        s.max_runup = max(s.max_runup, high - s.closed_trough)

    def _advance_trails(self, price: float) -> None:
        for (exit_id, uid), best in list(self.state.trails.items()):
            trade = self._trade(uid)
            if trade is None or best is None:
                continue
            self.state.trails[(exit_id, uid)] = max(best, price) if trade.direction == LONG else min(best, price)

    def _trade(self, uid: int):
        return next((t for t in self.state.trades if t.uid == uid), None)

    def _next_event(self, price: float, target: float, up: bool):
        """The nearest order level reached when the price moves from ``price`` to ``target``."""
        best = None

        def consider(level: float, action) -> None:
            nonlocal best
            if level is None:
                return
            distance = (level - price) if up else (price - level)
            if distance < -EPS:
                return
            if (target - level if up else level - target) < -EPS:
                return
            if best is None or distance < best[0] - EPS:
                best = (distance, level, action)

        for order in list(self.state.orders):
            if order.is_market:
                continue
            trigger = self._order_trigger(order, price, up)
            if trigger is not None:
                consider(trigger, lambda p, order=order: self._touch_order(order, p))
        for leg in self._exit_legs():
            for level, kind in self._leg_levels(leg, price, up):
                consider(level, lambda p, leg=leg, kind=kind: self._fill_exit(leg, kind, p))
        return None if best is None else (best[1], best[2])

    def _order_trigger(self, order: Order, price: float, up: bool):
        """Level at which a pending entry/order reacts on a move in direction ``up`` starting at ``price``."""
        buy = order.direction == LONG
        if order.stop is not None and not order.triggered:
            if buy and (up or order.stop <= price + EPS):
                return max(order.stop, price) if order.stop <= price + EPS else order.stop
            if not buy and (not up or order.stop >= price - EPS):
                return min(order.stop, price) if order.stop >= price - EPS else order.stop
            return None
        limit = order.limit
        if limit is None:
            return None
        extra = self.settings.backtest_fill_limits_assumption * self.mintick
        if buy:
            level = limit - extra
            if level >= price - EPS:
                return price                                          # already at or below the limit: fills now
            return level if not up else None
        level = limit + extra
        if level <= price + EPS:
            return price
        return level if up else None

    def _touch_order(self, order: Order, price: float) -> None:
        if order not in self.state.orders:
            return
        if order.stop is not None and not order.triggered:
            if order.limit is None:
                slip = self.settings.slippage * self.mintick * order.direction
                at_level = abs(price - order.stop) < EPS
                base = self.tick(price, "up" if order.direction == LONG else "down") if at_level else self.tick(price)
                self._execute(order, base + slip, price)
                return
            order.triggered = True                                    # stop-limit: the limit order is now working
            return
        limit = order.limit
        fill = min(price, limit) if order.direction == LONG else max(price, limit)
        if self.settings.backtest_fill_limits_assumption:
            fill = limit                                              # DOC: verified limits fill at their price
        self._execute(order, self.tick(fill), price)

    # -- exits ----------------------------------------------------------------------------------------------------
    def _exit_legs(self) -> list:
        """(command, trade, qty) for every working exit bracket, reserving quantity in command order (DOC)."""
        legs = []
        reserved: dict[int, float] = {}
        for command in sorted(self.state.exits, key=lambda e: e.seq):
            for trade in self.state.trades:
                if command.from_entry is not None and trade.entry_order not in command.bound_orders:
                    continue
                if (command.id, trade.uid) in self.state.consumed:
                    continue
                want = command.qty if command.qty is not None else trade.qty * (
                    command.qty_percent if command.qty_percent is not None else 100.0) / 100.0
                free = trade.qty - reserved.get(trade.uid, 0.0)
                qty = min(want, free)
                if qty <= EPS:
                    continue
                reserved[trade.uid] = reserved.get(trade.uid, 0.0) + qty
                legs.append((command, trade, qty))
        return legs

    def _levels(self, command: ExitCommand, trade: Trade) -> dict:
        tick, e, d = self.mintick, trade.entry_price, trade.direction
        v6 = self.settings.version >= 6

        def pick(absolute, relative, favourable_first: bool):
            rel = None if relative is None else e + d * relative * tick * (1 if favourable_first else -1)
            if absolute is None:
                return rel
            if rel is None or not v6:
                return absolute                                       # v5: the absolute level wins (DOC)
            # v6: the level reached first (DOC): nearer to the entry in the move's direction
            if favourable_first:
                return min(absolute, rel) if d == LONG else max(absolute, rel)
            return max(absolute, rel) if d == LONG else min(absolute, rel)

        levels = {"limit": pick(command.limit, command.profit, True),
                  "stop": pick(command.stop, command.loss, False)}
        if command.trail_offset is not None and (command.trail_price is not None or command.trail_points is not None):
            levels["activation"] = pick(command.trail_price, command.trail_points, True)
            levels["offset"] = command.trail_offset * tick
        return levels

    def _leg_levels(self, leg, price: float, up: bool) -> list:
        command, trade, _qty = leg
        lv = self._levels(command, trade)
        long = trade.direction == LONG
        out = []
        limit, stop = lv.get("limit"), lv.get("stop")
        if limit is not None:                                          # take profit: sell limit (long) / buy limit
            if (long and limit <= price + EPS) or (not long and limit >= price - EPS):
                out.append((price, "limit"))
            elif (long and up) or (not long and not up):
                out.append((limit, "limit"))
        if stop is not None:                                           # stop loss: sell stop (long) / buy stop
            if (long and stop >= price - EPS) or (not long and stop <= price + EPS):
                out.append((price, "stop"))
            elif (long and not up) or (not long and up):
                out.append((stop, "stop"))
        if "activation" in lv:
            key = (command.id, trade.uid)
            best = self.state.trails.get(key)
            if best is None:
                act = lv["activation"]
                if (long and act <= price + EPS) or (not long and act >= price - EPS):
                    out.append((price, "activate"))
                elif (long and up) or (not long and not up):
                    out.append((act, "activate"))
            else:
                trail = best - lv["offset"] if long else best + lv["offset"]
                if (long and trail >= price - EPS) or (not long and trail <= price + EPS):
                    out.append((price, "trail"))
                elif (long and not up) or (not long and up):
                    out.append((trail, "trail"))
        return out

    def _fill_exit(self, leg, kind: str, price: float) -> None:
        command, trade, qty = leg
        if trade not in self.state.trades:
            return
        key = (command.id, trade.uid)
        if kind == "activate":
            self.state.trails[key] = price
            return
        slip = 0.0 if kind == "limit" else self.settings.slippage * self.mintick * -trade.direction
        comment = {"limit": command.comment_profit, "stop": command.comment_loss,
                   "trail": command.comment_trailing}.get(kind) or command.comment
        level = self._exit_level(command, trade, kind)
        if kind == "limit" or level is None or abs(price - level) > EPS:
            base = self.tick(price)                                    # a gap / already crossed: the current price
        else:                                                          # a stop level: away from the market
            base = self.tick(price, "down" if trade.direction == LONG else "up")
        self.state.consumed.add(key)                                   # one order of the bracket filled: OCA
        self.state.trails.pop(key, None)
        self._close_fifo(qty, base + slip, command.id, comment, kind, "exit",
                         entry_id=None)

    def _exit_level(self, command: ExitCommand, trade: Trade, kind: str):
        lv = self._levels(command, trade)
        if kind == "trail":
            best = self.state.trails.get((command.id, trade.uid))
            if best is None:
                return None
            return best - lv["offset"] if trade.direction == LONG else best + lv["offset"]
        return lv.get(kind)

    # -- fills ----------------------------------------------------------------------------------------------------
    def _fill_market(self, order: Order, bar: int, price: float, immediate: bool = False) -> None:
        direction = order.direction
        if order.kind in ("close", "close_all"):
            trades = self.state.trades if order.kind == "close_all" else [
                t for t in self.state.trades if t.entry_id == order.from_entry]
            total = sum(t.qty for t in trades)
            qty = order.qty if order.qty is not None else total * (
                order.qty_percent if order.qty_percent is not None else 100.0) / 100.0
            qty = min(qty, total)
            self.state.orders.remove(order)
            if qty <= EPS or not trades:
                return
            side = -trades[0].direction
            slip = self.settings.slippage * self.mintick * side
            self._close_fifo(qty, self.tick(price) + slip, order.id, order.comment, "close", "close",
                             entry_id=None if order.kind == "close_all" else order.from_entry)
            return
        if order.kind == "entry" and self._direction() == direction and len(
                [t for t in self.state.trades if t.direction == direction]) >= self.settings.pyramiding:
            self.state.orders.remove(order)                            # OBS q12 S8: beyond pyramiding, not filled
            return
        slip = self.settings.slippage * self.mintick * direction
        self._execute(order, self.tick(price) + slip, price)

    def _execute(self, order: Order, fill: float, raw: float) -> None:
        """Fill an entry / order at ``fill`` (slippage included)."""
        if order not in self.state.orders:
            return
        self.state.orders.remove(order)
        bar = self.bar
        position = self._direction()
        qty = order.qty if order.qty is not None else self.default_qty(fill)
        if qty <= EPS:
            return
        transaction, closing = qty, 0.0
        if order.kind == "entry" and position == -order.direction:
            closing = sum(t.qty for t in self.state.trades)          # DOC: the reversal adds the open position's size
            transaction = closing + qty
            self._close_fifo(closing, fill, order.id, order.comment, "reversal", "reversal", entry_id=None,
                             order_qty=transaction)
        elif order.kind == "order" and position == -order.direction:
            closing = min(qty, sum(t.qty for t in self.state.trades))
            self._close_fifo(closing, fill, order.id, order.comment, "order", "order", entry_id=None,
                             order_qty=qty)
            qty -= closing
            if qty <= EPS:
                self._oca(order, transaction)
                return
        if not self._margin_ok(order.direction, qty, fill):
            return
        commission = self._commission(qty, fill)
        if self.settings.commission_type == COMMISSION_PER_ORDER and closing > 0:
            commission *= qty / transaction                            # POLICY: one order fee split by quantity
        self.state.trade_uid += 1
        trade = Trade(self.state.trade_uid, order.id, order.direction, qty, fill, bar, self._time(bar), order.seq,
                      order.comment, commission)
        self.state.trades.append(trade)
        self.state.commission_paid += commission
        if closing > 0:
            self.state.fills[-1].position_after = self.position()      # one transaction: close and open
        else:
            self.state.fills.append(Fill(bar, self._time(bar), order.id, "entry", None, order.direction, qty, fill,
                                         self.position(), order.comment))
        self._held()
        self._oca(order, transaction)

    def _oca(self, filled: Order, qty: float) -> None:
        if not filled.oca_name or filled.oca_type == OCA_NONE:
            return
        for other in list(self.state.orders):
            if other.oca_name == filled.oca_name and other.oca_type == filled.oca_type:
                if filled.oca_type == OCA_CANCEL:
                    self.state.orders.remove(other)
                elif other.qty is not None:
                    other.qty -= qty
                    if other.qty <= EPS:
                        self.state.orders.remove(other)

    def _margin_ok(self, direction: int, qty: float, price: float) -> bool:
        margin = self.settings.margin_long if direction == LONG else self.settings.margin_short
        if margin <= 0:
            return True                                                # v5 default: funds are not checked (DOC)
        required = qty * price * margin / 100.0
        used = sum(t.qty * t.entry_price for t in self.state.trades) * margin / 100.0
        # POLICY (to verify on TradingView): an entry that needs more margin than the available funds is not filled
        return required <= self.equity(price) - used + EPS

    def _close_fifo(self, qty: float, price: float, exit_id: str, comment, exit_kind: str, fill_kind: str,
                    entry_id: str | None, order_qty: float | None = None) -> None:
        """Close ``qty`` of the position, oldest trade first (DOC: FIFO) - ``entry_id`` only picks the quantity."""
        bar, remaining = self.bar, qty
        side = -self.state.trades[0].direction if self.state.trades else 0
        exit_commission_total = self._commission(qty, price, order_fill=True)
        if self.settings.commission_type == COMMISSION_PER_ORDER and order_qty:
            exit_commission_total *= qty / order_qty                   # POLICY: one order fee split by quantity
        while remaining > EPS and self.state.trades:
            trade = self.state.trades[0]
            move = (price - trade.entry_price) * trade.direction           # the exit fill (slippage included)
            trade.max_runup = max(trade.max_runup, move)
            trade.max_drawdown = max(trade.max_drawdown, -move)
            take = min(trade.qty, remaining)
            share = take / trade.qty
            entry_commission = trade.commission * share
            exit_commission = exit_commission_total * take / qty
            gross = (price - trade.entry_price) * trade.direction * take
            net = gross - entry_commission - exit_commission
            s = self.state
            s.closed.append(ClosedTrade(len(s.closed) + 1, trade.entry_id, trade.direction, take, trade.entry_price,
                                        trade.entry_bar, trade.entry_time, trade.entry_comment, exit_id, price, bar,
                                        self._time(bar), comment, exit_kind, entry_commission + exit_commission, net,
                                        # OBS q13: excursions are net of the trade's entry commission
                                        trade.max_runup * take - entry_commission,
                                        trade.max_drawdown * take + entry_commission))
            s.netprofit += net
            s.commission_paid += exit_commission
            if net > EPS:
                s.grossprofit += net
                s.wins += 1
            elif net < -EPS:
                s.grossloss += -net
                s.losses += 1
            else:
                s.evens += 1
            trade.qty -= take
            trade.commission -= entry_commission
            remaining -= take
            self._equity_extremes()
            s.closed_peak = max(s.closed_peak, self.settings.initial_capital + s.netprofit)
            s.closed_trough = min(s.closed_trough, self.settings.initial_capital + s.netprofit)
            if trade.qty <= EPS:
                s.trades.pop(0)
                s.consumed = {k for k in s.consumed if k[1] != trade.uid}
                s.trails = {k: v for k, v in s.trails.items() if k[1] != trade.uid}
        self.state.fills.append(Fill(bar, self._time(bar), exit_id, fill_kind, exit_kind, side,
                                     qty if order_qty is None else order_qty, price, self.position(), comment))
        if not self.state.trades:
            # DOC: exit commands without from_entry stop at the position's close; bound commands have nothing left
            self.state.exits = [e for e in self.state.exits if e.from_entry is not None and any(
                o.seq in e.bound_orders for o in self.state.orders)]
            self.state.consumed, self.state.trails = set(), {}

    # -- bookkeeping ---------------------------------------------------------------------------------------------
    def _held(self) -> None:
        position = self.position()
        if position > 0:
            self.state.max_held_long = max(self.state.max_held_long, position)
        elif position < 0:
            self.state.max_held_short = max(self.state.max_held_short, -position)

    def _record(self, bar: int, close: float) -> None:
        """The strategy state the script sees when it executes on ``bar`` (for strategy.*[n] history)."""
        self.state.history[bar] = self.snapshot(close)

    def _mark(self, bar: int, close: float) -> None:
        if not math.isnan(close):
            equity = self.equity(close)
            curve = self.state.equity_curve
            if curve and curve[-1][0] == bar:
                curve[-1] = (bar, equity)
            else:
                curve.append((bar, equity))

    def snapshot(self, close: float) -> dict:
        s = self.state
        price = close if not math.isnan(close) else NA
        open_profit = 0.0 if is_na(price) else self.open_profit(price)
        closed = len(s.closed)
        return {
            "position_size": self.position(), "position_avg_price": self.avg_price(),
            "position_entry_name": s.trades[0].entry_id if s.trades else "",
            "opentrades": len(s.trades), "closedtrades": closed, "wintrades": s.wins, "losstrades": s.losses,
            "eventrades": s.evens, "netprofit": s.netprofit, "grossprofit": s.grossprofit, "grossloss": s.grossloss,
            "openprofit": open_profit, "equity": self.settings.initial_capital + s.netprofit + open_profit,
            "max_drawdown": s.max_drawdown, "max_runup": s.max_runup,
            "max_contracts_held_long": s.max_held_long, "max_contracts_held_short": s.max_held_short,
            "max_contracts_held_all": max(s.max_held_long, s.max_held_short),
            "avg_trade": s.netprofit / closed if closed else NA,
            "avg_winning_trade": s.grossprofit / s.wins if s.wins else NA,
            "avg_losing_trade": s.grossloss / s.losses if s.losses else NA,
        }

    def value(self, name: str, bar: int):
        """A strategy.* variable as the script sees it on ``bar``: the live state on the current bar, the recorded
        state on earlier bars (history operator)."""
        if bar == self.bar:
            return self.snapshot(float(self.data.close[bar])).get(name, NA)
        recorded = self.state.history.get(bar)
        return NA if recorded is None else recorded.get(name, NA)


def is_na_or_none(value) -> bool:
    return value is None or is_na(value)

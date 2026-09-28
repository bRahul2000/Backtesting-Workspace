"""Reference list of Pine Script v5/v6 built-in identifiers (names only).

Used to tell "valid Pine that this engine does not implement yet" (a capability
gap, reported by name) from "not Pine at all" (Pine's own "Undeclared
identifier" error). Implementations live in the built-in registries; this list
never needs to change when a built-in is implemented.
"""
from __future__ import annotations

_FUNCTIONS = {
    "": """indicator strategy library plot plotshape plotchar plotarrow plotbar plotcandle hline fill bgcolor barcolor
        alert alertcondition nz na fixnan int float bool string color label line box table linefill polyline
        input max_bars_back time time_close timestamp year month weekofyear dayofmonth dayofweek hour minute second""",
    "ta": """alma atr barssince bb bbw cci change cmo cog correlation cross crossover crossunder cum dev dmi ema falling
        highest highestbars hma kc kcw linreg lowest lowestbars macd max median mfi min mode mom percentile_linear_interpolation
        percentile_nearest_rank percentrank pivot_point_levels pivothigh pivotlow range rci rising rma roc rsi sar sma
        stdev stoch supertrend swma tr tsi valuewhen variance vwap vwma wma wpr""",
    "math": """abs acos asin atan avg ceil cos exp floor log log10 max min pow random round round_to_mintick sign sin
        sqrt sum tan todegrees toradians""",
    "str": """contains endswith format format_time length lower match pos repeat replace replace_all split startswith
        substring tonumber tostring trim upper""",
    "color": "b from_gradient g new r rgb t",
    "input": "bool color enum float int price session source string symbol text_area time timeframe",
    "request": """currency_rate dividends earnings economic financial quandl security security_lower_tf seed splits
        footprint""",
    "array": """abs avg binary_search binary_search_leftmost binary_search_rightmost clear concat copy covariance every
        fill first from get includes indexof insert join last lastindexof max median min mode new new_bool new_box
        new_color new_float new_int new_label new_line new_linefill new_string new_table percentile_linear_interpolation
        percentile_nearest_rank percentrank pop push range remove reverse set shift size slice some sort sort_indices
        standardize stdev sum unshift variance""",
    "matrix": """add_col add_row avg col columns concat copy det diff eigenvalues eigenvectors elements_count fill get
        inv is_antidiagonal is_antisymmetric is_binary is_diagonal is_identity is_square is_stochastic is_symmetric
        is_triangular is_zero kron max median min mode mult new pinv pow rank remove_col remove_row reshape reverse
        row rows set sort submatrix sum swap_columns swap_rows trace transpose""",
    "map": "clear contains copy get keys new put put_all remove size values",
    "line": """copy delete get_price get_x1 get_x2 get_y1 get_y2 new set_color set_extend set_first_point
        set_second_point set_style set_width set_x1 set_x2 set_xloc set_xy1 set_xy2 set_y1 set_y2""",
    "label": """copy delete get_text get_x get_y new set_color set_point set_size set_style set_text set_text_font_family
        set_text_formatting set_textalign set_textcolor set_tooltip set_x set_xloc set_xy set_y set_yloc""",
    "box": """copy delete get_bottom get_left get_right get_top new set_bgcolor set_border_color set_border_style
        set_border_width set_bottom set_bottom_right_point set_extend set_left set_lefttop set_right set_rightbottom
        set_text set_text_color set_text_font_family set_text_formatting set_text_halign set_text_size set_text_valign
        set_text_wrap set_top set_top_left_point set_xloc""",
    "table": """cell cell_set_bgcolor cell_set_height cell_set_text cell_set_text_color cell_set_text_font_family
        cell_set_text_formatting cell_set_text_halign cell_set_text_size cell_set_text_valign cell_set_tooltip
        cell_set_width clear delete merge_cells new set_bgcolor set_border_color set_border_width set_frame_color
        set_frame_width set_position""",
    "polyline": "delete new",
    "linefill": "delete get_line1 get_line2 new set_color",
    "chart.point": "copy from_index from_time new now",
    "strategy": """cancel cancel_all close close_all closedtrades.commission closedtrades.entry_bar_index
        closedtrades.entry_comment closedtrades.entry_id closedtrades.entry_price closedtrades.entry_time
        closedtrades.exit_bar_index closedtrades.exit_comment closedtrades.exit_id closedtrades.exit_price
        closedtrades.exit_time closedtrades.max_drawdown closedtrades.max_runup closedtrades.profit closedtrades.size
        convert_to_account convert_to_symbol default_entry_qty entry exit order risk.allow_entry_in
        risk.max_cons_loss_days risk.max_drawdown risk.max_intraday_filled_orders risk.max_intraday_loss
        risk.max_position_size opentrades.commission opentrades.entry_bar_index opentrades.entry_comment
        opentrades.entry_id opentrades.entry_price opentrades.entry_time opentrades.max_drawdown opentrades.max_runup
        opentrades.profit opentrades.size""",
    "timeframe": "change from_seconds in_seconds",
    "ticker": "heikinashi inherit kagi linebreak modify new pointfigure renko standard",
    "runtime": "error",
    "log": "error info warning",
    "session": "",
    "syminfo": "",
}

_VARIABLES = {
    "": """open high low close volume hl2 hlc3 ohlc4 hlcc4 bar_index last_bar_index last_bar_time time time_close
        time_tradingday timenow na year month weekofyear dayofmonth dayofweek hour minute second""",
    "ta": "accdist iii nvi obv pvi pvt tr vwap wad wvad",
    "barstate": "isconfirmed isfirst ishistory islast islastconfirmedhistory isnew isrealtime",
    "timeframe": "isdaily isdwm isintraday isminutes ismonthly isseconds isticks isweekly main_period multiplier period",
    "syminfo": """basecurrency country currency description employees expiration_date industry main_tickerid
        mincontract minmove mintick pointvalue prefix pricescale recommendations_buy recommendations_buy_strong
        recommendations_date recommendations_hold recommendations_sell recommendations_sell_strong recommendations_total
        root sector session shareholders shares_outstanding_float shares_outstanding_total target_price_average
        target_price_date target_price_estimates target_price_high target_price_low target_price_median ticker
        tickerid timezone type volumetype""",
    "session": "isfirstbar isfirstbar_regular islastbar islastbar_regular ismarket ispostmarket ispremarket",
    "line": "all", "label": "all", "box": "all", "linefill": "all", "polyline": "all", "table": "all",
    "chart": "bg_color fg_color is_heikinashi is_kagi is_linebreak is_pnf is_range is_renko is_standard left_visible_bar_time right_visible_bar_time",
    "strategy": """account_currency avg_losing_trade avg_losing_trade_percent avg_trade avg_trade_percent avg_winning_trade
        avg_winning_trade_percent closedtrades equity eventrades grossloss grossloss_percent grossprofit
        grossprofit_percent initial_capital losstrades margin_liquidation_price max_contracts_held_all
        max_contracts_held_long max_contracts_held_short max_drawdown max_drawdown_percent max_runup max_runup_percent
        netprofit netprofit_percent openprofit openprofit_percent opentrades position_avg_price position_entry_name
        position_size wintrades""",
}

#: Constant namespaces (every member of these is a known Pine constant).
CONSTANT_NAMESPACES = {
    "color", "plot", "shape", "location", "size", "hline", "display", "format", "scale", "position", "extend", "xloc",
    "yloc", "text", "font", "dayofweek", "currency", "adjustment", "barmerge", "earnings", "dividends", "splits",
    "order", "alert", "label", "line", "session", "math", "strategy", "backadjustment", "settlement_as_close",
}

KNOWN_FUNCTIONS: set[str] = set()
KNOWN_VARIABLES: set[str] = set()
for namespace, names in _FUNCTIONS.items():
    for name in names.split():
        KNOWN_FUNCTIONS.add(f"{namespace}.{name}" if namespace else name)
for namespace, names in _VARIABLES.items():
    for name in names.split():
        KNOWN_VARIABLES.add(f"{namespace}.{name}" if namespace else name)

#: Human description of each namespace (used in capability-gap messages).
NAMESPACE_FEATURES = {
    "request": ("request", "multi-timeframe / external data requests"),
    "array": ("arrays", "arrays"),
    "matrix": ("matrices", "matrices"),
    "map": ("maps", "maps"),
    "line": ("drawings-core", "drawing objects (lines)"),
    "label": ("drawings-core", "drawing objects (labels)"),
    "box": ("drawings-core", "drawing objects (boxes)"),
    "table": ("drawing-objects", "drawing objects (tables)"),
    "polyline": ("drawing-objects", "drawing objects (polylines)"),
    "linefill": ("drawings-core", "drawing objects (linefills)"),
    "chart.point": ("drawing-objects", "chart points"),
    "strategy": ("strategy", "strategy scripts"),
    "ticker": ("request", "ticker construction"),
    "log": ("logging", "Pine logs"),
    "str": ("strings", "string functions"),
    "ta": ("ta", "technical-analysis built-ins"),
    "math": ("math", "math built-ins"),
    "input": ("inputs", "inputs"),
    "timeframe": ("timeframe", "timeframe built-ins"),
    "": ("core", "core built-ins"),
}


def namespace_of(name: str) -> str:
    if name.startswith("chart.point."):
        return "chart.point"
    return name.rsplit(".", 1)[0] if "." in name else ""


def is_known_function(name: str) -> bool:
    return name in KNOWN_FUNCTIONS


def is_known_variable(name: str) -> bool:
    if name in KNOWN_VARIABLES:
        return True
    namespace = namespace_of(name)
    return namespace in CONSTANT_NAMESPACES and "." in name

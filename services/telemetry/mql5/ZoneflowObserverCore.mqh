//+------------------------------------------------------------------+
//| ZoneflowObserverCore.mqh - the Telemetry V1 observer logic       |
//| (inputs, transaction capture, heartbeat, connection, export).    |
//| ZoneflowTelemetryObserver.mq5 wires it to the MT5 event handlers.|
//| No trade function exists in this file.                           |
//+------------------------------------------------------------------+
#property strict

#include "ZoneflowTelemetry.mqh"

#define ZF_OBSERVER_VERSION "observer-1.0"

input string InpStrategyId          = "";     // strategy_id (as in Zoneflow strategies.json)
input string InpStrategyVersion     = "";     // strategy version label (optional)
input string InpMagicNumbers        = "";     // magic number(s) to watch, comma separated
input string InpSymbols             = "";     // optional symbol filter, comma separated (empty = any)
input int    InpHeartbeatSeconds    = 60;     // heartbeat interval
input bool   InpExportBrokerHistory = true;   // daily MT5 history export for reconciliation
input int    InpExportCatchUpDays   = 14;     // export missed days on start (history permitting)

long   g_magics[];
string g_symbols[];
bool   g_connected       = false;
datetime g_last_beat     = 0;
datetime g_last_export_check = 0;
ulong  g_accepted_orders[];            // orders already reported as accepted (newest 2000)
ulong  g_pending_deals[];              // deals whose history was not readable yet
datetime g_pending_since[];

//+------------------------------------------------------------------+
bool Watched(const long magic, const string symbol)
  {
   bool magic_ok = false;
   for(int i = 0; i < ArraySize(g_magics); i++)
      if(g_magics[i] == magic)
         magic_ok = true;
   if(!magic_ok)
      return false;
   if(ArraySize(g_symbols) == 0)
      return true;
   for(int i = 0; i < ArraySize(g_symbols); i++)
      if(g_symbols[i] == symbol)
         return true;
   return false;
  }

string Runtime(const string status)
  {
   ZfObject o;
   o.Str("status", status);
   o.Str("program", "ZoneflowTelemetryObserver");
   o.Str("observer_version", ZF_OBSERVER_VERSION);
   o.Int("terminal_build", TerminalInfoInteger(TERMINAL_BUILD));
   o.Bool("terminal_connected", TerminalInfoInteger(TERMINAL_CONNECTED) != 0);
   o.Bool("trade_allowed", TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) != 0);
   o.Bool("account_trade_allowed", AccountInfoInteger(ACCOUNT_TRADE_ALLOWED) != 0);
   o.Bool("account_trade_expert", AccountInfoInteger(ACCOUNT_TRADE_EXPERT) != 0);
   o.Int("ping_ms", TerminalInfoInteger(TERMINAL_PING_LAST) / 1000);
   o.Int("server_utc_offset_s", ZfServerOffsetSeconds());
   o.Str("magic_numbers", InpMagicNumbers);
   o.Str("symbols", InpSymbols);
   o.Int("heartbeat_s", InpHeartbeatSeconds);
   o.Int("write_failures", ZfWriteFailures());
   o.Int("events_written", ZfEventsWritten());
   int positions = 0, orders = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && Watched(PositionGetInteger(POSITION_MAGIC), PositionGetString(POSITION_SYMBOL)))
         positions++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket > 0 && Watched(OrderGetInteger(ORDER_MAGIC), OrderGetString(ORDER_SYMBOL)))
         orders++;
     }
   o.Int("open_positions", positions);
   o.Int("open_orders", orders);
   return o.Json();
  }

void Beat(const string event_type, const string status)
  {
   ZfEvent e(event_type);
   e.Obj("runtime", Runtime(status));
   e.Write();
   g_last_beat = TimeGMT();
  }

//+------------------------------------------------------------------+
//| Deals -> position_opened / position_closed                       |
//+------------------------------------------------------------------+
string EntryName(const long entry)
  {
   switch((int)entry)
     {
      case DEAL_ENTRY_IN:     return "in";
      case DEAL_ENTRY_OUT:    return "out";
      case DEAL_ENTRY_INOUT:  return "inout";
      case DEAL_ENTRY_OUT_BY: return "out_by";
     }
   return "";
  }

string ReasonName(const long reason)
  {
   switch((int)reason)
     {
      case DEAL_REASON_SL:       return "sl";
      case DEAL_REASON_TP:       return "tp";
      case DEAL_REASON_SO:       return "stop_out";
      case DEAL_REASON_CLIENT:   return "client";
      case DEAL_REASON_MOBILE:   return "mobile";
      case DEAL_REASON_WEB:      return "web";
      case DEAL_REASON_EXPERT:   return "expert";
      case DEAL_REASON_ROLLOVER: return "rollover";
      case DEAL_REASON_VMARGIN:  return "vmargin";
      case DEAL_REASON_SPLIT:    return "split";
     }
   return "other";
  }

string DealSide(const long deal_type)
  {
   if(deal_type == DEAL_TYPE_BUY)
      return "buy";
   if(deal_type == DEAL_TYPE_SELL)
      return "sell";
   return "";
  }

bool AlreadyAccepted(const ulong order)
  {
   for(int i = ArraySize(g_accepted_orders) - 1; i >= 0; i--)
      if(g_accepted_orders[i] == order)
         return true;
   return false;
  }

void RememberAccepted(const ulong order)
  {
   int n = ArraySize(g_accepted_orders);
   if(n >= 2000)
     {
      ArrayRemove(g_accepted_orders, 0, 1000);
      n = ArraySize(g_accepted_orders);
     }
   ArrayResize(g_accepted_orders, n + 1);
   g_accepted_orders[n] = order;
  }

void EmitOrder(const string event_type, const ulong order, const bool in_history);

// A market order can be filled before MT5 reports it as added, so acceptance is also recorded the first time the
// order is seen in history (its fill, or its move to history) - once per order either way.
void EnsureOrderAccepted(const ulong order)
  {
   if(order == 0 || AlreadyAccepted(order) || !HistoryOrderSelect(order))
      return;
   EmitOrder("order_accepted", order, true);
  }

// true = handled (emitted or not ours); false = history not readable yet
bool EmitDeal(const ulong deal)
  {
   if(!HistoryDealSelect(deal))
      return false;
   long type = HistoryDealGetInteger(deal, DEAL_TYPE);
   if(type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL)
      return true;                                   // balance, credit, commission ... not a fill
   string symbol = HistoryDealGetString(deal, DEAL_SYMBOL);
   long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
   if(!Watched(magic, symbol))
      return true;
   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   ulong order = (ulong)HistoryDealGetInteger(deal, DEAL_ORDER);
   EnsureOrderAccepted(order);
   ZfEvent e(entry == DEAL_ENTRY_IN ? "position_opened" : "position_closed");
   e.Str("symbol", symbol);
   e.Int("magic_number", magic);
   e.Int("deal_id", (long)deal);
   e.Int("ticket_id", (long)deal);
   e.IntIfSet("order_id", (long)order);
   e.IntIfSet("position_id", HistoryDealGetInteger(deal, DEAL_POSITION_ID));
   e.Str("direction", DealSide(type));
   e.Str("deal_entry", EntryName(entry));
   e.BrokerTime(HistoryDealGetInteger(deal, DEAL_TIME_MSC), true);
   e.Num("fill_price", HistoryDealGetDouble(deal, DEAL_PRICE), digits);
   e.Num("filled_volume", HistoryDealGetDouble(deal, DEAL_VOLUME), 8);
   e.NumIfSet("stop_loss", HistoryDealGetDouble(deal, DEAL_SL), digits);
   e.NumIfSet("take_profit", HistoryDealGetDouble(deal, DEAL_TP), digits);
   if(order > 0 && HistoryOrderSelect(order))
     {
      e.NumIfSet("requested_price", HistoryOrderGetDouble(order, ORDER_PRICE_OPEN), digits);
      e.NumIfSet("requested_volume", HistoryOrderGetDouble(order, ORDER_VOLUME_INITIAL), 8);
     }
   if(entry != DEAL_ENTRY_IN)
      e.Str("exit_reason", ReasonName(HistoryDealGetInteger(deal, DEAL_REASON)));
   e.Quote(symbol);                                  // the quote seen at capture time, not at the fill
   e.Write();
   return true;
  }

void RetryPendingDeals()
  {
   for(int i = ArraySize(g_pending_deals) - 1; i >= 0; i--)
     {
      HistorySelect(TimeTradeServer() - 7 * 86400, TimeTradeServer() + 86400);
      bool done = EmitDeal(g_pending_deals[i]);
      if(!done && TimeGMT() - g_pending_since[i] > 120)
        {
         ZfEvent e("error");
         e.Int("deal_id", (long)g_pending_deals[i]);
         e.Str("message", "deal history not readable within 120 s - fill not captured here (reconciliation will list it)");
         e.Write();
         done = true;
        }
      if(done)
        {
         ArrayRemove(g_pending_deals, i, 1);
         ArrayRemove(g_pending_since, i, 1);
        }
     }
  }

//+------------------------------------------------------------------+
//| Orders                                                           |
//+------------------------------------------------------------------+
void EmitOrder(const string event_type, const ulong order, const bool in_history)
  {
   string symbol = in_history ? HistoryOrderGetString(order, ORDER_SYMBOL) : OrderGetString(ORDER_SYMBOL);
   long magic = in_history ? HistoryOrderGetInteger(order, ORDER_MAGIC) : OrderGetInteger(ORDER_MAGIC);
   if(!Watched(magic, symbol))
      return;
   if(event_type == "order_accepted")
     {
      if(AlreadyAccepted(order))
         return;
      RememberAccepted(order);
     }
   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   long type = in_history ? HistoryOrderGetInteger(order, ORDER_TYPE) : OrderGetInteger(ORDER_TYPE);
   long setup_ms = in_history ? HistoryOrderGetInteger(order, ORDER_TIME_SETUP_MSC) : OrderGetInteger(ORDER_TIME_SETUP_MSC);
   ZfEvent e(event_type);
   e.Str("symbol", symbol);
   e.Int("magic_number", magic);
   e.Int("order_id", (long)order);
   e.Int("ticket_id", (long)order);
   e.Str("direction", ZfDirection(type));
   e.IntIfSet("position_id", in_history ? HistoryOrderGetInteger(order, ORDER_POSITION_ID) : OrderGetInteger(ORDER_POSITION_ID));
   e.BrokerTime(event_type == "order_accepted" ? setup_ms
                : (in_history ? HistoryOrderGetInteger(order, ORDER_TIME_DONE_MSC) : setup_ms), false);
   e.NumIfSet("requested_price", in_history ? HistoryOrderGetDouble(order, ORDER_PRICE_OPEN) : OrderGetDouble(ORDER_PRICE_OPEN), digits);
   e.NumIfSet("requested_volume", in_history ? HistoryOrderGetDouble(order, ORDER_VOLUME_INITIAL) : OrderGetDouble(ORDER_VOLUME_INITIAL), 8);
   e.NumIfSet("stop_loss", in_history ? HistoryOrderGetDouble(order, ORDER_SL) : OrderGetDouble(ORDER_SL), digits);
   e.NumIfSet("take_profit", in_history ? HistoryOrderGetDouble(order, ORDER_TP) : OrderGetDouble(ORDER_TP), digits);
   e.Quote(symbol);
   e.Write();
  }

void ObsTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   switch(trans.type)
     {
      case TRADE_TRANSACTION_DEAL_ADD:
        {
         HistorySelect(TimeTradeServer() - 7 * 86400, TimeTradeServer() + 86400);
         if(!EmitDeal(trans.deal))
           {
            int n = ArraySize(g_pending_deals);
            ArrayResize(g_pending_deals, n + 1);
            ArrayResize(g_pending_since, n + 1);
            g_pending_deals[n] = trans.deal;
            g_pending_since[n] = TimeGMT();
           }
         break;
        }
      case TRADE_TRANSACTION_ORDER_ADD:
        {
         if(OrderSelect(trans.order))
            EmitOrder("order_accepted", trans.order, false);
         else
           {
            HistorySelect(TimeTradeServer() - 7 * 86400, TimeTradeServer() + 86400);
            if(HistoryOrderSelect(trans.order))
               EmitOrder("order_accepted", trans.order, true);
           }
         break;
        }
      case TRADE_TRANSACTION_HISTORY_ADD:
        {
         HistorySelect(TimeTradeServer() - 7 * 86400, TimeTradeServer() + 86400);
         if(!HistoryOrderSelect(trans.order))
            break;
         long state = HistoryOrderGetInteger(trans.order, ORDER_STATE);
         if(state != ORDER_STATE_REJECTED)
            EnsureOrderAccepted(trans.order);
         if(state == ORDER_STATE_CANCELED)
            EmitOrder("order_cancelled", trans.order, true);
         else if(state == ORDER_STATE_EXPIRED)
            EmitOrder("order_expired", trans.order, true);
         else if(state == ORDER_STATE_REJECTED)
            EmitOrder("order_rejected", trans.order, true);
         break;
        }
      case TRADE_TRANSACTION_POSITION:
        {
         if(!PositionSelectByTicket(trans.position))
            break;
         string symbol = PositionGetString(POSITION_SYMBOL);
         long magic = PositionGetInteger(POSITION_MAGIC);
         if(!Watched(magic, symbol))
            break;
         int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
         ZfEvent e("position_modified");
         e.Str("symbol", symbol);
         e.Int("magic_number", magic);
         e.Int("position_id", (long)trans.position);
         e.Int("ticket_id", (long)trans.position);
         e.Str("direction", PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "buy" : "sell");
         e.BrokerTime(PositionGetInteger(POSITION_TIME_UPDATE_MSC), false);
         e.NumIfSet("stop_loss", trans.price_sl, digits);
         e.NumIfSet("take_profit", trans.price_tp, digits);
         e.Quote(symbol);
         e.Write();
         break;
        }
      case TRADE_TRANSACTION_REQUEST:
        {
         // Delivered by MT5 to the program that sent the request, so normally not seen here; recorded if it is.
         bool ok = result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED
                   || result.retcode == TRADE_RETCODE_DONE_PARTIAL;
         if(!ok && Watched((long)request.magic, request.symbol))
           {
            ZfEvent e("order_rejected");
            e.Str("symbol", request.symbol);
            e.Int("magic_number", (long)request.magic);
            e.Str("direction", ZfDirection(request.type));
            e.NumIfSet("requested_price", request.price, (int)SymbolInfoInteger(request.symbol, SYMBOL_DIGITS));
            e.NumIfSet("requested_volume", request.volume, 8);
            e.Int("broker_return_code", (long)result.retcode);
            e.Str("message", result.comment);
            e.Write();
           }
         break;
        }
      default:
         break;
     }
  }

//+------------------------------------------------------------------+
//| Daily MT5 history export (the authority for reconciliation)       |
//+------------------------------------------------------------------+
string J(const string s) { return "\"" + ZfEscape(s) + "\""; }

string OrderTypeName(const long t)
  {
   switch((int)t)
     {
      case ORDER_TYPE_BUY: return "buy";               case ORDER_TYPE_SELL: return "sell";
      case ORDER_TYPE_BUY_LIMIT: return "buy_limit";   case ORDER_TYPE_SELL_LIMIT: return "sell_limit";
      case ORDER_TYPE_BUY_STOP: return "buy_stop";     case ORDER_TYPE_SELL_STOP: return "sell_stop";
      case ORDER_TYPE_BUY_STOP_LIMIT: return "buy_stop_limit";
      case ORDER_TYPE_SELL_STOP_LIMIT: return "sell_stop_limit";
      case ORDER_TYPE_CLOSE_BY: return "close_by";
     }
   return "other";
  }

string OrderStateName(const long s)
  {
   switch((int)s)
     {
      case ORDER_STATE_STARTED: return "started";   case ORDER_STATE_PLACED: return "placed";
      case ORDER_STATE_CANCELED: return "cancelled"; case ORDER_STATE_PARTIAL: return "partial";
      case ORDER_STATE_FILLED: return "filled";      case ORDER_STATE_REJECTED: return "rejected";
      case ORDER_STATE_EXPIRED: return "expired";
     }
   return "other";
  }

string OrderJson(const ulong t, const bool hist, const int offset)
  {
   string sym = hist ? HistoryOrderGetString(t, ORDER_SYMBOL) : OrderGetString(ORDER_SYMBOL);
   int d = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   long setup = hist ? HistoryOrderGetInteger(t, ORDER_TIME_SETUP_MSC) : OrderGetInteger(ORDER_TIME_SETUP_MSC);
   long done = hist ? HistoryOrderGetInteger(t, ORDER_TIME_DONE_MSC) : 0;
   string s = "{\"order_id\":" + IntegerToString((long)t)
              + ",\"position_id\":" + IntegerToString(hist ? HistoryOrderGetInteger(t, ORDER_POSITION_ID) : OrderGetInteger(ORDER_POSITION_ID))
              + ",\"symbol\":" + J(sym)
              + ",\"magic_number\":" + IntegerToString(hist ? HistoryOrderGetInteger(t, ORDER_MAGIC) : OrderGetInteger(ORDER_MAGIC))
              + ",\"type\":" + J(OrderTypeName(hist ? HistoryOrderGetInteger(t, ORDER_TYPE) : OrderGetInteger(ORDER_TYPE)))
              + ",\"state\":" + J(OrderStateName(hist ? HistoryOrderGetInteger(t, ORDER_STATE) : OrderGetInteger(ORDER_STATE)))
              + ",\"active\":" + (hist ? "false" : "true")
              + ",\"volume_initial\":" + DoubleToString(hist ? HistoryOrderGetDouble(t, ORDER_VOLUME_INITIAL) : OrderGetDouble(ORDER_VOLUME_INITIAL), 8)
              + ",\"price_open\":" + DoubleToString(hist ? HistoryOrderGetDouble(t, ORDER_PRICE_OPEN) : OrderGetDouble(ORDER_PRICE_OPEN), d)
              + ",\"stop_loss\":" + DoubleToString(hist ? HistoryOrderGetDouble(t, ORDER_SL) : OrderGetDouble(ORDER_SL), d)
              + ",\"take_profit\":" + DoubleToString(hist ? HistoryOrderGetDouble(t, ORDER_TP) : OrderGetDouble(ORDER_TP), d)
              + ",\"setup_time_server\":" + J(ZfServerMs(setup))
              + ",\"setup_utc\":" + J(ZfIsoMs(setup - (long)offset * 1000))
              + ",\"done_utc\":" + (done > 0 ? J(ZfIsoMs(done - (long)offset * 1000)) : "null")
              + ",\"digits\":" + IntegerToString(d) + "}";
   return s;
  }

bool ExportDay(const datetime day_utc)
  {
   MqlDateTime d;
   TimeToStruct(day_utc, d);
   string day = StringFormat("%04d-%02d-%02d", d.year, d.mon, d.day);
   string folder = ZF_ROOT + "\\broker\\" + g_zf_account_ref;
   string path = folder + "\\" + day + ".json";
   if(FileIsExist(path, FILE_COMMON))
      return true;                                    // exports are written once, never replaced
   int offset = ZfServerOffsetSeconds();
   datetime from_server = day_utc + offset, to_server = day_utc + 86400 + offset;
   if(!HistorySelect(from_server - 86400, TimeTradeServer() + 60))
      return false;
   string deals = "", orders = "";
   int deal_count = 0, order_count = 0;
   for(int i = 0; i < HistoryDealsTotal(); i++)
     {
      ulong t = HistoryDealGetTicket(i);
      long type = HistoryDealGetInteger(t, DEAL_TYPE);
      long ms = HistoryDealGetInteger(t, DEAL_TIME_MSC);
      if((type != DEAL_TYPE_BUY && type != DEAL_TYPE_SELL) || ms < (long)from_server * 1000 || ms >= (long)to_server * 1000)
         continue;
      string sym = HistoryDealGetString(t, DEAL_SYMBOL);
      int dg = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      long entry = HistoryDealGetInteger(t, DEAL_ENTRY);
      deals += (deal_count++ > 0 ? "," : "") + "{\"deal_id\":" + IntegerToString((long)t)
               + ",\"order_id\":" + IntegerToString(HistoryDealGetInteger(t, DEAL_ORDER))
               + ",\"position_id\":" + IntegerToString(HistoryDealGetInteger(t, DEAL_POSITION_ID))
               + ",\"symbol\":" + J(sym)
               + ",\"magic_number\":" + IntegerToString(HistoryDealGetInteger(t, DEAL_MAGIC))
               + ",\"type\":" + J(DealSide(type))
               + ",\"entry\":" + J(EntryName(entry))
               + ",\"reason\":" + J(ReasonName(HistoryDealGetInteger(t, DEAL_REASON)))
               + ",\"volume\":" + DoubleToString(HistoryDealGetDouble(t, DEAL_VOLUME), 8)
               + ",\"price\":" + DoubleToString(HistoryDealGetDouble(t, DEAL_PRICE), dg)
               + ",\"commission\":" + DoubleToString(HistoryDealGetDouble(t, DEAL_COMMISSION), 2)
               + ",\"swap\":" + DoubleToString(HistoryDealGetDouble(t, DEAL_SWAP), 2)
               + ",\"profit\":" + DoubleToString(HistoryDealGetDouble(t, DEAL_PROFIT), 2)
               + ",\"time_server\":" + J(ZfServerMs(ms))
               + ",\"broker_utc\":" + J(ZfIsoMs(ms - (long)offset * 1000))
               + ",\"digits\":" + IntegerToString(dg) + "}";
     }
   for(int i = 0; i < HistoryOrdersTotal(); i++)
     {
      ulong t = HistoryOrderGetTicket(i);
      long setup = HistoryOrderGetInteger(t, ORDER_TIME_SETUP_MSC);
      if(setup < (long)from_server * 1000 || setup >= (long)to_server * 1000)
         continue;
      orders += (order_count++ > 0 ? "," : "") + OrderJson(t, true, offset);
     }
   for(int i = 0; i < OrdersTotal(); i++)             // still-pending orders placed that day
     {
      ulong t = OrderGetTicket(i);
      long setup = OrderGetInteger(ORDER_TIME_SETUP_MSC);
      if(t == 0 || setup < (long)from_server * 1000 || setup >= (long)to_server * 1000)
         continue;
      orders += (order_count++ > 0 ? "," : "") + OrderJson(t, false, offset);
     }
   string text = "{\"export_version\":1,\"day\":" + J(day)
                 + ",\"account_ref\":" + J(g_zf_account_ref) + ",\"account_server\":" + J(g_zf_server)
                 + ",\"account_environment\":" + J(g_zf_environment) + ",\"broker\":" + J(g_zf_broker)
                 + ",\"server_utc_offset_s\":" + IntegerToString(offset)
                 + ",\"exported_utc\":" + J(ZfIsoSeconds(TimeGMT()))
                 + ",\"exported_by\":" + J(g_zf_writer_id + ":" + ZfRunId())
                 + ",\"deal_count\":" + IntegerToString(deal_count) + ",\"order_count\":" + IntegerToString(order_count)
                 + ",\"deals\":[" + deals + "],\"orders\":[" + orders + "],\"complete\":true}\n";
   uchar bytes[];
   int n = StringToCharArray(text, bytes, 0, WHOLE_ARRAY, CP_UTF8) - 1;
   ArrayResize(bytes, n);
   ZfEnsureFolder(folder);
   string temporary = path + "." + ZfRunId() + ".tmp";
   int h = FileOpen(temporary, FILE_WRITE | FILE_BIN | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return false;
   uint written = FileWriteArray(h, bytes, 0, n);
   FileFlush(h);
   FileClose(h);
   if(written != (uint)n || !FileMove(temporary, FILE_COMMON, path, FILE_COMMON))
     {
      FileDelete(temporary, FILE_COMMON);
      return false;
     }
   return true;
  }

void ExportDueDays()
  {
   datetime now = TimeGMT();
   datetime today = now - (now % 86400);
   if(now - today < 600)                                 // wait 10 minutes after UTC midnight
      today -= 86400;
   for(int back = InpExportCatchUpDays; back >= 1; back--)
     {
      if(!ExportDay(today - back * 86400))
        {
         ZfEvent e("error");
         e.Int("raw_error_code", GetLastError());
         e.Str("message", "broker history export failed for " + TimeToString(today - back * 86400, TIME_DATE));
         e.Write();
         break;                                          // try again on the next check
        }
     }
  }

//+------------------------------------------------------------------+
int ObsInit()
  {
   string parts[];
   int n = StringSplit(InpMagicNumbers, ',', parts);
   ArrayResize(g_magics, 0);
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringTrimLeft(p);
      StringTrimRight(p);
      if(StringLen(p) == 0)
         continue;
      long m = StringToInteger(p);
      if(m <= 0 || IntegerToString(m) != p)
        {
         Print("Zoneflow observer: invalid magic number '", p, "'");
         return INIT_PARAMETERS_INCORRECT;
        }
      int k = ArraySize(g_magics);
      ArrayResize(g_magics, k + 1);
      g_magics[k] = m;
     }
   ArrayResize(g_symbols, 0);
   n = StringSplit(InpSymbols, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringTrimLeft(p);
      StringTrimRight(p);
      if(StringLen(p) == 0)
         continue;
      int k = ArraySize(g_symbols);
      ArrayResize(g_symbols, k + 1);
      g_symbols[k] = p;
     }
   if(StringLen(InpStrategyId) == 0 || ArraySize(g_magics) == 0 || InpHeartbeatSeconds < 5)
     {
      Print("Zoneflow observer: set InpStrategyId and at least one magic number (heartbeat >= 5 s)");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(!ZfInit("observer." + InpStrategyId, InpStrategyId, InpStrategyVersion, "", "realtime"))
      Print("Zoneflow observer: telemetry spool not available - events will be counted as write failures");
   g_connected = TerminalInfoInteger(TERMINAL_CONNECTED) != 0;
   Beat("ea_started", "started");
   EventSetTimer(1);
   Print("Zoneflow telemetry observer ", ZF_OBSERVER_VERSION, " watching ", InpStrategyId, " magic ", InpMagicNumbers,
         " run ", ZfRunId(), " - observe only, no trading functions");
   return INIT_SUCCEEDED;
  }

void ObsDeinit(const int reason)
  {
   EventKillTimer();
   ZfEvent e("ea_stopped");
   ZfObject o;
   o.Str("status", "stopped");
   o.Int("deinit_reason", reason);
   o.Int("write_failures", ZfWriteFailures());
   o.Int("events_written", ZfEventsWritten());
   e.Obj("runtime", o.Json());
   e.Write();
  }

void ObsTimer()
  {
   bool connected = TerminalInfoInteger(TERMINAL_CONNECTED) != 0;
   if(connected != g_connected)
     {
      g_connected = connected;
      Beat(connected ? "broker_reconnect" : "broker_disconnect", connected ? "connected" : "disconnected");
     }
   if(TimeGMT() - g_last_beat >= InpHeartbeatSeconds)
      Beat("heartbeat", connected ? "running" : "running_disconnected");
   if(ArraySize(g_pending_deals) > 0)
      RetryPendingDeals();
   if(InpExportBrokerHistory && connected && TimeGMT() - g_last_export_check >= 60)
     {
      g_last_export_check = TimeGMT();
      ExportDueDays();
     }
  }

//+------------------------------------------------------------------+

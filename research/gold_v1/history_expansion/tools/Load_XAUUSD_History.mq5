//+------------------------------------------------------------------+
//| Load_XAUUSD_History.mq5                                          |
//| HISTORY-ONLY helper for Gold V1 history expansion.               |
//|                                                                  |
//| Asks the terminal to download/build older XAUUSDm M15 and H1     |
//| bars from the broker server, using the documented MQL5 pattern:  |
//| requesting bar positions older than the oldest local bar         |
//| (CopyTime from position = Bars()) makes the terminal fetch the   |
//| missing history, and SERIES_FIRSTDATE shows how far it got.      |
//|                                                                  |
//| No trading code: no Trade includes, no order/position/deal       |
//| functions, no web requests. It writes one status JSON into       |
//| MT5 Common Files. Exporting stays with the unchanged             |
//| mt5/Export_XAUUSD_History script.                                |
//+------------------------------------------------------------------+
#property script_show_inputs

input string   InpSymbol      = "XAUUSDm";
input datetime InpTargetDate  = D'2014.01.14 00:00';   // stop once history reaches this date (server first date)
input int      InpChunkBars   = 2000;                  // bars requested per round
input int      InpStallRounds = 40;                    // rounds without an older first bar before giving up
input int      InpSleepMs     = 500;                   // pause between rounds (server download is asynchronous)
input int      InpMaxMinutes  = 30;                    // hard time limit per run
input bool     InpWriteStatus = true;                  // write xauusd_history_loader_status.json to Common Files

struct LoadResult
  {
   string            tf;
   datetime          first;
   datetime          last;
   int               bars;
   bool              synced;
   bool              target_reached;
   string            stop_reason;
   int               rounds;
   int               last_error;
  };

string TfName(const ENUM_TIMEFRAMES tf)
  {
   if(tf == PERIOD_M15)
      return "M15";
   if(tf == PERIOD_H1)
      return "H1";
   return EnumToString(tf);
  }

datetime SeriesDate(const string symbol, const ENUM_TIMEFRAMES tf, const ENUM_SERIES_INFO_INTEGER prop)
  {
   long value = 0;
   if(!SeriesInfoInteger(symbol, tf, prop, value))
      return 0;
   return (datetime)value;
  }

string Ts(const datetime value)
  {
   if(value == 0)
      return "n/a";
   return TimeToString(value, TIME_DATE|TIME_MINUTES);
  }

// First date the broker server holds for the symbol (any timeframe). May need a few polls to arrive.
datetime ServerFirstDate(const string symbol)
  {
   for(int i = 0; i < 50 && !IsStopped(); i++)
     {
      datetime d = SeriesDate(symbol, PERIOD_M1, SERIES_SERVER_FIRSTDATE);
      if(d > 0)
         return d;
      Sleep(100);
     }
   return 0;
  }

void LoadSeries(const string symbol, const ENUM_TIMEFRAMES tf, const datetime target,
                const datetime server_first, const long max_bars, const uint deadline_ms, LoadResult &r)
  {
   r.tf = TfName(tf);
   r.stop_reason = "running";
   r.rounds = 0;
   r.last_error = 0;
   datetime effective = target;
   if(server_first > 0 && server_first > target)
      effective = server_first;              // the server holds nothing older than this

   datetime best_first = 0;
   int stall = 0;
   datetime times[];
   while(!IsStopped())
     {
      if(GetTickCount() > deadline_ms)
        {
         r.stop_reason = "TIMEOUT";
         break;
        }
      r.rounds++;
      int bars = Bars(symbol, tf);
      datetime first = SeriesDate(symbol, tf, SERIES_FIRSTDATE);
      if(first > 0 && first <= effective)
        {
         r.stop_reason = (effective == target) ? "TARGET_REACHED" : "SERVER_FIRST_DATE_REACHED";
         break;
        }
      if(max_bars > 0 && bars >= max_bars)
        {
         r.stop_reason = "MAX_BARS_LIMIT";   // raise Tools > Options > Charts > Max bars in chart
         break;
        }
      // Ask for bars older than the oldest one held locally; this triggers the server download.
      ResetLastError();
      int copied = CopyTime(symbol, tf, bars, InpChunkBars, times);
      if(copied <= 0)
         r.last_error = GetLastError();
      first = SeriesDate(symbol, tf, SERIES_FIRSTDATE);
      if(first > 0 && (best_first == 0 || first < best_first))
        {
         best_first = first;
         stall = 0;
        }
      else
         stall++;
      if(r.rounds % 10 == 0)
         PrintFormat("[%s] round %d: bars=%d first=%s copied=%d err=%d stall=%d",
                     r.tf, r.rounds, Bars(symbol, tf), Ts(first), copied, r.last_error, stall);
      if(stall >= InpStallRounds)
        {
         r.stop_reason = "NO_OLDER_DATA";
         break;
        }
      Sleep(InpSleepMs);
     }
   if(IsStopped() && r.stop_reason == "running")
      r.stop_reason = "STOPPED_BY_USER";

   r.bars = Bars(symbol, tf);
   r.first = SeriesDate(symbol, tf, SERIES_FIRSTDATE);
   datetime last_completed[];
   r.last = (CopyTime(symbol, tf, 1, 1, last_completed) == 1) ? last_completed[0] : 0;   // shift 1 = last completed bar
   r.synced = (SeriesInfoInteger(symbol, tf, SERIES_SYNCHRONIZED) != 0);
   r.target_reached = (r.first > 0 && r.first <= target);
  }

string ResultJson(const LoadResult &r)
  {
   return StringFormat("{\"timeframe\": \"%s\", \"first_bar\": \"%s\", \"last_completed_bar\": \"%s\", "
                       "\"bars\": %d, \"synchronized\": %s, \"target_reached\": %s, \"stop_reason\": \"%s\", "
                       "\"rounds\": %d, \"last_error\": %d}",
                       r.tf, Ts(r.first), Ts(r.last), r.bars, r.synced ? "true" : "false",
                       r.target_reached ? "true" : "false", r.stop_reason, r.rounds, r.last_error);
  }

void OnStart()
  {
   string symbol = InpSymbol;
   if(!SymbolSelect(symbol, true))
     {
      Print("Unable to select symbol ", symbol, ": ", GetLastError());
      return;
     }
   long max_bars = TerminalInfoInteger(TERMINAL_MAXBARS);
   datetime server_first = ServerFirstDate(symbol);
   datetime terminal_first = SeriesDate(symbol, PERIOD_M1, SERIES_TERMINAL_FIRSTDATE);
   // Rough need: ~92 M15 bars per trading day, ~5/7 of calendar days.
   double days = (double)(TimeCurrent() - InpTargetDate) / 86400.0;
   long need_m15 = (long)(days * 5.0 / 7.0 * 92.0);
   PrintFormat("History loader: symbol=%s server=%s target=%s", symbol, AccountInfoString(ACCOUNT_SERVER), Ts(InpTargetDate));
   PrintFormat("Server first date (any timeframe)=%s, terminal first date=%s, Max bars in chart=%I64d, "
               "estimated M15 bars needed=%I64d", Ts(server_first), Ts(terminal_first), max_bars, need_m15);
   if(max_bars > 0 && need_m15 > max_bars)
      PrintFormat("WARNING: Max bars in chart (%I64d) is below the ~%I64d M15 bars needed for %s. "
                  "M15 will stop at MAX_BARS_LIMIT; set Tools > Options > Charts > Max bars in chart to Unlimited "
                  "(or >= %I64d), restart MT5 and run again.", max_bars, need_m15, Ts(InpTargetDate), need_m15 + 25000);

   uint deadline = GetTickCount() + (uint)InpMaxMinutes * 60000;
   LoadResult m15, h1;
   LoadSeries(symbol, PERIOD_M15, InpTargetDate, server_first, max_bars, deadline, m15);
   LoadSeries(symbol, PERIOD_H1, InpTargetDate, server_first, max_bars, deadline, h1);

   PrintFormat("M15: first=%s last=%s bars=%d synced=%s target_reached=%s stop=%s rounds=%d last_error=%d",
               Ts(m15.first), Ts(m15.last), m15.bars, m15.synced ? "yes" : "no", m15.target_reached ? "yes" : "no",
               m15.stop_reason, m15.rounds, m15.last_error);
   PrintFormat("H1:  first=%s last=%s bars=%d synced=%s target_reached=%s stop=%s rounds=%d last_error=%d",
               Ts(h1.first), Ts(h1.last), h1.bars, h1.synced ? "yes" : "no", h1.target_reached ? "yes" : "no",
               h1.stop_reason, h1.rounds, h1.last_error);
   Print("Next: run Export_XAUUSD_History (unchanged) to export the loaded bars.");

   if(!InpWriteStatus)
      return;
   int handle = FileOpen("xauusd_history_loader_status.json", FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("Status file could not be written: ", GetLastError());
      return;
     }
   string json = "{\n";
   json += StringFormat("  \"symbol\": \"%s\",\n  \"server\": \"%s\",\n  \"target_date\": \"%s\",\n",
                        symbol, AccountInfoString(ACCOUNT_SERVER), Ts(InpTargetDate));
   json += StringFormat("  \"server_first_date\": \"%s\",\n  \"terminal_first_date_before_run\": \"%s\",\n",
                        Ts(server_first), Ts(terminal_first));
   json += StringFormat("  \"max_bars_in_chart\": %I64d,\n  \"estimated_m15_bars_needed\": %I64d,\n", max_bars, need_m15);
   json += StringFormat("  \"run_finished_server_time\": \"%s\",\n", Ts(TimeTradeServer()));
   json += "  \"M15\": " + ResultJson(m15) + ",\n";
   json += "  \"H1\": " + ResultJson(h1) + "\n}\n";
   FileWriteString(handle, json);
   FileClose(handle);
   Print("Wrote status to Common Files: xauusd_history_loader_status.json");
  }
//+------------------------------------------------------------------+

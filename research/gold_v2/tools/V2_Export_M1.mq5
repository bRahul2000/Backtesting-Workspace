//+------------------------------------------------------------------+
//| V2_Export_M1.mq5 — Gold V2 research-only M1 HISTORY LOADER+EXPORT |
//|                                                                  |
//| For each requested symbol the server offers: download M1 history |
//| back to max(server first date, InpFromYear-01-01) using the      |
//| documented CopyTime-from-position pattern, then export completed |
//| M1 bars per calendar year to Common Files:                       |
//|   v2_m1_<SYMBOL>_<YEAR>.csv   (timestamp,OHLC,tick_volume,spread,|
//|                                real_volume)                      |
//|   v2_m1_<SYMBOL>.metadata.json                                   |
//| Bars inside SEALED windows are never written (2021-09-01 ..      |
//| 2022-11-26, 2026-06-03 onward).                                  |
//| No trading code: no includes, no order/position/deal/history-     |
//| selection functions, no web/socket calls, no DLLs.                |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSymbols    = "XAUUSDm,XAGUSDm,EURUSDm";
input string InpOptional   = "DXYm,USDXm,DXY,USDX,USDJPYm";   // exported only if the server offers them
input int    InpFromYear   = 2014;
input int    InpChunkBars  = 20000;
input int    InpStallRounds = 40;
input int    InpSleepMs    = 500;
input int    InpMaxMinutes = 90;

string J(const string s) { return "\"" + s + "\""; }

// sealed windows are never written (Gold V1/V2 register): 2021-09-01..2022-11-26 and 2026-06-03 onward
bool Sealed(const datetime t)
  {
   return (t >= D'2021.09.01 00:00' && t < D'2022.11.27 00:00') || t >= D'2026.06.03 00:00';
  }
string Ts(const datetime t) { return t == 0 ? "n/a" : TimeToString(t, TIME_DATE|TIME_MINUTES|TIME_SECONDS); }

bool Exists(const string name)
  {
   int n = SymbolsTotal(false);
   for(int i = 0; i < n; i++)
      if(SymbolName(i, false) == name)
         return true;
   return false;
  }

datetime ServerFirst(const string sym)
  {
   for(int i = 0; i < 50 && !IsStopped(); i++)
     {
      long v = 0;
      if(SeriesInfoInteger(sym, PERIOD_M1, SERIES_SERVER_FIRSTDATE, v) && v > 0)
         return (datetime)v;
      Sleep(100);
     }
   return 0;
  }

string LoadM1(const string sym, const datetime target, const uint deadline)
  {
   long max_bars = TerminalInfoInteger(TERMINAL_MAXBARS);
   datetime best = 0;
   int stall = 0;
   datetime times[];
   while(!IsStopped())
     {
      if(GetTickCount() > deadline)
         return "TIMEOUT";
      long v = 0;
      datetime first = SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, v) ? (datetime)v : 0;
      if(first > 0 && first <= target)
         return "TARGET_REACHED";
      int bars = Bars(sym, PERIOD_M1);
      if(max_bars > 0 && bars >= max_bars)
         return "MAX_BARS_LIMIT";
      CopyTime(sym, PERIOD_M1, bars, InpChunkBars, times);
      first = SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, v) ? (datetime)v : 0;
      if(first > 0 && (best == 0 || first < best)) { best = first; stall = 0; }
      else stall++;
      if(stall >= InpStallRounds)
         return "NO_OLDER_DATA";
      Sleep(InpSleepMs);
     }
   return "STOPPED";
  }

void ExportSymbol(const string sym, const uint deadline)
  {
   if(!Exists(sym))
     {
      PrintFormat("%s: not offered by this server — skipped", sym);
      return;
     }
   SymbolSelect(sym, true);
   datetime sf = ServerFirst(sym);
   MqlDateTime s; s.year = InpFromYear; s.mon = 1; s.day = 1; s.hour = 0; s.min = 0; s.sec = 0;
   datetime target = MathMax(StructToTime(s), sf);
   string stop = LoadM1(sym, target, deadline);
   long v = 0;
   datetime first = SeriesInfoInteger(sym, PERIOD_M1, SERIES_FIRSTDATE, v) ? (datetime)v : 0;
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   MqlDateTime now; TimeToStruct(TimeTradeServer(), now);
   datetime last_completed[];
   CopyTime(sym, PERIOD_M1, 1, 1, last_completed);
   datetime cutoff = ArraySize(last_completed) == 1 ? last_completed[0] : 0;     // exclude the forming bar
   string per_year = "";
   long total = 0;
   for(int y = InpFromYear; y <= now.year && !IsStopped(); y++)
     {
      MqlDateTime a; a.year = y; a.mon = 1; a.day = 1; a.hour = 0; a.min = 0; a.sec = 0;
      MqlDateTime b; b.year = y + 1; b.mon = 1; b.day = 1; b.hour = 0; b.min = 0; b.sec = 0;
      datetime t0 = StructToTime(a), t1 = MathMin(StructToTime(b) - 1, cutoff);
      if(t1 < t0)
         continue;
      MqlRates r[];
      int got = CopyRates(sym, PERIOD_M1, t0, t1, r);
      if(got <= 0)
        {
         per_year += (per_year == "" ? "" : ", ") + "\"" + IntegerToString(y) + "\": 0";
         continue;
        }
      string fname = "v2_m1_" + sym + "_" + IntegerToString(y) + ".csv";
      int h = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
      if(h == INVALID_HANDLE)
        {
         PrintFormat("cannot write %s: %d", fname, GetLastError());
         continue;
        }
      FileWrite(h, "timestamp", "open", "high", "low", "close", "tick_volume", "spread", "real_volume");
      int written = 0;
      for(int k = 0; k < got; k++)
        {
         if(Sealed(r[k].time))
            continue;
         written++;
         FileWrite(h, TimeToString(r[k].time, TIME_DATE|TIME_MINUTES|TIME_SECONDS), DoubleToString(r[k].open, digits),
                   DoubleToString(r[k].high, digits), DoubleToString(r[k].low, digits), DoubleToString(r[k].close, digits),
                   (long)r[k].tick_volume, (int)r[k].spread, (long)r[k].real_volume);
        }
      FileClose(h);
      total += written;
      per_year += (per_year == "" ? "" : ", ") + "\"" + IntegerToString(y) + "\": " + IntegerToString(written);
     }
   string meta = "{\n \"source\": \"MT5 CopyRates M1 broker history\",\n \"symbol\": " + J(sym) + ",\n \"server\": " +
                 J(AccountInfoString(ACCOUNT_SERVER)) + ",\n \"server_utc_offset_seconds\": " +
                 IntegerToString((int)(TimeTradeServer() - TimeGMT())) + ",\n \"digits\": " + IntegerToString(digits) +
                 ",\n \"point\": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 8) +
                 ",\n \"server_first_date_m1\": " + J(Ts(sf)) + ",\n \"loaded_first_bar\": " + J(Ts(first)) +
                 ",\n \"load_stop_reason\": " + J(stop) + ",\n \"last_completed_bar\": " + J(Ts(cutoff)) +
                 ",\n \"bars_exported\": " + IntegerToString(total) + ",\n \"bars_by_year\": {" + per_year + "}" +
                 ",\n \"capture_server_time\": " + J(Ts(TimeTradeServer())) + "\n}\n";
   int hm = FileOpen("v2_m1_" + sym + ".metadata.json", FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(hm != INVALID_HANDLE)
     {
      FileWriteString(hm, meta);
      FileClose(hm);
     }
   PrintFormat("%s: first=%s stop=%s exported=%I64d bars", sym, Ts(first), stop, total);
  }

void OnStart()
  {
   uint deadline = GetTickCount() + (uint)InpMaxMinutes * 60000;
   string req[], opt[];
   int n1 = StringSplit(InpSymbols, ',', req);
   int n2 = StringSplit(InpOptional, ',', opt);
   for(int i = 0; i < n1 && !IsStopped(); i++) { StringTrimLeft(req[i]); StringTrimRight(req[i]); ExportSymbol(req[i], deadline); }
   for(int i = 0; i < n2 && !IsStopped(); i++) { StringTrimLeft(opt[i]); StringTrimRight(opt[i]); ExportSymbol(opt[i], deadline); }
   Print("V2 M1 export complete.");
  }
//+------------------------------------------------------------------+

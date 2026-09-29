//+------------------------------------------------------------------+
//| V2_DataProbe_Fast.mq5 — Gold V2 research-only FAST DATA PROBE    |
//|                                                                  |
//| 1. one-time server symbol LIST (metadata only, no history)       |
//|    -> v2_probe_symbols.csv                                        |
//| 2. PRIORITY symbols only (XAUUSDm, XAGUSDm, EURUSDm, DXYm,       |
//|    USDJPYm): earliest M1 server date + approximate earliest TICK |
//|    date by search (recent -> yearly back-steps -> bisection),    |
//|    bid/ask/flags/millisecond presence -> v2_probe_fast.json,      |
//|    small tick samples -> v2_probe_fast_ticks_<SYM>.csv            |
//| Strict limits: per request, per symbol, global. Partial results  |
//| are written if a limit is hit.                                    |
//| Sealed dates are never requested (2021-09-01..2022-11-26 and     |
//| 2026-06-03 onward). No trading code, no includes, no web/socket, |
//| no DLLs. SymbolSelect() adds the priority symbols to Market Watch.|
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpPriority      = "XAUUSDm,XAGUSDm,EURUSDm,DXYm,USDJPYm";
input int    InpRequestTries  = 8;        // attempts per tick request
input int    InpRequestSleep  = 250;      // ms between attempts (≈2 s max per request)
input int    InpSymbolSeconds = 120;      // per-symbol limit
input int    InpGlobalSeconds = 600;      // whole-probe limit
input int    InpOldestYear    = 2014;

uint g_deadline = 0;

string J(const string s) { string e = s; StringReplace(e, "\\", "\\\\"); StringReplace(e, "\"", "\\\""); return "\"" + e + "\""; }
string Ts(const datetime t) { return t == 0 ? "n/a" : TimeToString(t, TIME_DATE|TIME_MINUTES); }
string D(const datetime t) { return t == 0 ? "n/a" : TimeToString(t, TIME_DATE); }

bool Sealed(const datetime t) { return (t >= D'2021.09.01 00:00' && t < D'2022.11.27 00:00') || t >= D'2026.06.03 00:00'; }

bool Exists(const string name)
  {
   int n = SymbolsTotal(false);
   for(int i = 0; i < n; i++)
      if(SymbolName(i, false) == name)
         return true;
   return false;
  }

// Wednesday 14:00 UTC of the week containing t (server time = UTC+0)
datetime Wed14(const datetime t)
  {
   MqlDateTime s; TimeToStruct(t, s);
   datetime day0 = t - (s.hour * 3600 + s.min * 60 + s.sec);
   int shift = 3 - s.day_of_week;                 // Sunday=0 … Wednesday=3
   return day0 + shift * 86400 + 14 * 3600;
  }

// nearest usable probe time: a Wednesday 14:00 outside sealed windows, moved away from the seal if needed
datetime Usable(datetime t)
  {
   datetime w = Wed14(t);
   if(w >= D'2021.09.01 00:00' && w < D'2022.11.27 00:00')
      w = (w - D'2021.09.01 00:00' < D'2022.11.27 00:00' - w) ? Wed14(D'2021.08.25 00:00') : Wed14(D'2022.11.30 00:00');
   if(w >= D'2026.06.03 00:00')
      w = Wed14(D'2026.05.27 00:00');
   return w;
  }

struct Probe
  {
   datetime at;
   int      ticks;
   int      err;
  };

int g_requests = 0;

int Ticks(const string sym, const datetime from, MqlTick &t[], int &err)
  {
   int got = -1;
   err = 0;
   if(Sealed(from) || Sealed(from + 3600))
      return -2;                                   // never requested
   for(int a = 0; a < InpRequestTries && !IsStopped(); a++)
     {
      if(GetTickCount() > g_deadline)
         break;
      g_requests++;
      ResetLastError();
      got = CopyTicksRange(sym, t, COPY_TICKS_ALL, (ulong)from * 1000, (ulong)(from + 3600) * 1000);
      err = GetLastError();
      if(got > 0)
         return got;
      Sleep(InpRequestSleep);
     }
   return got;
  }

string ProbeSymbol(const string sym)
  {
   uint t0 = GetTickCount();
   uint sym_deadline = t0 + (uint)InpSymbolSeconds * 1000;
   uint keep = g_deadline;
   g_deadline = MathMin(g_deadline, sym_deadline);
   int req0 = g_requests;
   SymbolSelect(sym, true);
   datetime m1first = 0;
   for(int i = 0; i < 30 && !IsStopped(); i++)
     {
      long v = 0;
      if(SeriesInfoInteger(sym, PERIOD_M1, SERIES_SERVER_FIRSTDATE, v) && v > 0) { m1first = (datetime)v; break; }
      Sleep(100);
     }
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   string log = "";
   MqlTick t[];
   int err = 0;
   // recent (last unsealed month)
   datetime recent = Usable(D'2026.05.27 00:00');
   int nrec = Ticks(sym, recent, t, err);
   log += "{\"at\": " + J(Ts(recent)) + ", \"ticks\": " + IntegerToString(nrec) + "}";
   int nb = 0, na = 0, fb = 0, fa = 0, ms = 0;
   if(nrec > 0)
     {
      int hs = FileOpen("v2_probe_fast_ticks_" + sym + ".csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
      if(hs != INVALID_HANDLE)
         FileWrite(hs, "time_msc", "bid", "ask", "last", "volume", "flags");
      for(int k = 0; k < nrec; k++)
        {
         if(t[k].bid > 0) nb++;
         if(t[k].ask > 0) na++;
         if((t[k].flags & TICK_FLAG_BID) != 0) fb++;
         if((t[k].flags & TICK_FLAG_ASK) != 0) fa++;
         if(t[k].time_msc % 1000 != 0) ms++;
         if(hs != INVALID_HANDLE)
            FileWrite(hs, (long)t[k].time_msc, DoubleToString(t[k].bid, digits), DoubleToString(t[k].ask, digits),
                      DoubleToString(t[k].last, digits), (long)t[k].volume, (int)t[k].flags);
        }
      if(hs != INVALID_HANDLE)
         FileClose(hs);
     }
   // yearly back-steps from the recent point
   datetime good = nrec > 0 ? recent : 0, bad = 0;
   string status = nrec > 0 ? "searching" : "NO_RECENT_TICKS";
   if(nrec > 0)
     {
      MqlDateTime s; TimeToStruct(recent, s);
      for(int y = s.year - 1; y >= InpOldestYear && !IsStopped(); y--)
        {
         if(GetTickCount() > g_deadline) { status = "TIME_LIMIT"; break; }
         MqlDateTime q = s; q.year = y;
         datetime at = Usable(StructToTime(q));
         int n = Ticks(sym, at, t, err);
         log += ", {\"at\": " + J(Ts(at)) + ", \"ticks\": " + IntegerToString(n) + "}";
         if(n > 0) good = at;
         else { bad = at; break; }
        }
      if(status == "searching" && bad == 0)
         status = "TICKS_AT_OLDEST_YEAR_PROBED";
      // bisection between bad (no ticks) and good (ticks) to ~1 week
      while(status == "searching" && bad > 0 && good - bad > 7 * 86400 && !IsStopped())
        {
         if(GetTickCount() > g_deadline) { status = "TIME_LIMIT"; break; }
         datetime mid = Usable(bad + (good - bad) / 2);
         if(mid <= bad || mid >= good) break;
         int n = Ticks(sym, mid, t, err);
         log += ", {\"at\": " + J(Ts(mid)) + ", \"ticks\": " + IntegerToString(n) + "}";
         if(n > 0) good = mid; else bad = mid;
        }
      if(status == "searching")
         status = "BOUNDARY_FOUND";
     }
   uint elapsed = GetTickCount() - t0;
   g_deadline = keep;
   PrintFormat("%s: M1 first=%s earliest ticks found=%s status=%s requests=%d elapsed=%.1fs",
               sym, D(m1first), D(good), status, g_requests - req0, elapsed / 1000.0);
   return "{\"symbol\": " + J(sym) + ", \"digits\": " + IntegerToString(digits) +
          ", \"server_first_date_m1\": " + J(D(m1first)) + ", \"earliest_tick_date_found\": " + J(D(good)) +
          ", \"latest_no_tick_date_probed\": " + J(D(bad)) + ", \"status\": " + J(status) +
          ", \"recent_sample\": {\"at\": " + J(Ts(recent)) + ", \"ticks\": " + IntegerToString(nrec) +
          ", \"bid_present\": " + IntegerToString(nb) + ", \"ask_present\": " + IntegerToString(na) +
          ", \"flag_bid\": " + IntegerToString(fb) + ", \"flag_ask\": " + IntegerToString(fa) +
          ", \"nonzero_ms\": " + IntegerToString(ms) + "}" +
          ", \"requests\": " + IntegerToString(g_requests - req0) + ", \"elapsed_s\": " + DoubleToString(elapsed / 1000.0, 1) +
          ", \"probes\": [" + log + "]}";
  }

void OnStart()
  {
   uint start = GetTickCount();
   g_deadline = start + (uint)InpGlobalSeconds * 1000;
   // one-time symbol list (metadata only)
   int hs = FileOpen("v2_probe_symbols.csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   int n = SymbolsTotal(false);
   if(hs != INVALID_HANDLE)
     {
      FileWrite(hs, "name", "path", "description", "digits", "point", "currency_base", "currency_profit");
      for(int i = 0; i < n; i++)
        {
         string s = SymbolName(i, false);
         FileWrite(hs, s, SymbolInfoString(s, SYMBOL_PATH), SymbolInfoString(s, SYMBOL_DESCRIPTION),
                   (int)SymbolInfoInteger(s, SYMBOL_DIGITS), DoubleToString(SymbolInfoDouble(s, SYMBOL_POINT), 8),
                   SymbolInfoString(s, SYMBOL_CURRENCY_BASE), SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT));
        }
      FileClose(hs);
     }
   string pr[];
   int np = StringSplit(InpPriority, ',', pr);
   string body = "";
   for(int i = 0; i < np && !IsStopped(); i++)
     {
      string sym = pr[i];
      StringTrimLeft(sym); StringTrimRight(sym);
      string item;
      if(!Exists(sym))
         item = "{\"symbol\": " + J(sym) + ", \"status\": \"NOT_OFFERED\"}";
      else if(GetTickCount() > g_deadline)
         item = "{\"symbol\": " + J(sym) + ", \"status\": \"SKIPPED_GLOBAL_TIME_LIMIT\"}";
      else
         item = ProbeSymbol(sym);
      body += (body == "" ? "" : ",\n  ") + item;
      // write partial results after every symbol
      int hj = FileOpen("v2_probe_fast.json", FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
      if(hj != INVALID_HANDLE)
        {
         FileWriteString(hj, "{\n \"server\": " + J(AccountInfoString(ACCOUNT_SERVER)) + ",\n \"server_symbols_listed\": " +
                         IntegerToString(n) + ",\n \"elapsed_s\": " + DoubleToString((GetTickCount() - start) / 1000.0, 1) +
                         ",\n \"symbols\": [\n  " + body + "\n ]\n}\n");
         FileClose(hj);
        }
     }
   PrintFormat("V2 fast data probe complete in %.1fs (%d tick requests). Output: v2_probe_fast.json",
               (GetTickCount() - start) / 1000.0, g_requests);
  }
//+------------------------------------------------------------------+

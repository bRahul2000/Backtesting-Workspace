//+------------------------------------------------------------------+
//| V2_DataProbe.mq5 — Gold V2 research-only DATA PROBE              |
//|                                                                  |
//| Read-only investigation of what the broker server provides:      |
//|  1. every server symbol (name, path, description, digits, point, |
//|     currencies) -> v2_probe_symbols.csv                           |
//|  2. for candidate symbols: SERIES_SERVER_FIRSTDATE, spec, and a   |
//|     quarterly TICK-HISTORY SAMPLE (one hour on a Wednesday,       |
//|     14:00-15:00 UTC) since 2014: tick count, bid/ask presence,    |
//|     flag bits, millisecond timestamps, spread -> v2_probe.json    |
//|  3. the sampled ticks themselves -> v2_probe_ticks_<SYM>.csv      |
//| No trading code: no includes, no order/position/deal/history-     |
//| selection functions, no web/socket calls, no DLLs. It only reads  |
//| market data (which may download history) and writes to Common     |
//| Files. SymbolSelect() adds the candidates to Market Watch.        |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpCandidates = "XAUUSDm,XAGUSDm,EURUSDm,USDJPYm,GBPUSDm,USDCHFm,XPTUSDm,XPDUSDm,DXYm,USDXm,DXY,USDX,US10Ym,UST10Ym";
input int    InpFirstYear  = 2014;
input int    InpLastYear   = 2026;
input int    InpRetries    = 30;          // attempts per tick request (server download is asynchronous)
input int    InpSleepMs    = 300;

string J(const string s) { string e = s; StringReplace(e, "\\", "\\\\"); StringReplace(e, "\"", "\\\""); return "\"" + e + "\""; }
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

// sealed windows are never sampled (Gold V1/V2 register): 2021-09-01..2022-11-26 and 2026-06-03 onward
bool Sealed(const datetime t)
  {
   return (t >= D'2021.09.01 00:00' && t < D'2022.11.27 00:00') || t >= D'2026.06.03 00:00';
  }

// a Wednesday 14:00 UTC in the middle of month m of year y (server time is UTC+0 on this server)
datetime SampleStart(const int y, const int m)
  {
   MqlDateTime s;
   s.year = y; s.mon = m; s.day = 15; s.hour = 14; s.min = 0; s.sec = 0;
   datetime t = StructToTime(s);
   TimeToStruct(t, s);
   int shift = (3 - s.day_of_week + 7) % 7;       // move forward to Wednesday
   return t + shift * 86400;
  }

int FetchTicks(const string sym, const datetime from, const datetime to, MqlTick &ticks[], int &err)
  {
   int got = -1;
   for(int a = 0; a < InpRetries && !IsStopped(); a++)
     {
      ResetLastError();
      got = CopyTicksRange(sym, ticks, COPY_TICKS_ALL, (ulong)from * 1000, (ulong)to * 1000);
      err = GetLastError();
      if(got > 0)
         return got;
      Sleep(InpSleepMs);
     }
   return got;
  }

void OnStart()
  {
   // 1. all server symbols
   int hs = FileOpen("v2_probe_symbols.csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
   if(hs != INVALID_HANDLE)
     {
      FileWrite(hs, "name", "path", "description", "digits", "point", "currency_base", "currency_profit", "calc_mode");
      int n = SymbolsTotal(false);
      for(int i = 0; i < n; i++)
        {
         string s = SymbolName(i, false);
         FileWrite(hs, s, SymbolInfoString(s, SYMBOL_PATH), SymbolInfoString(s, SYMBOL_DESCRIPTION),
                   (int)SymbolInfoInteger(s, SYMBOL_DIGITS), DoubleToString(SymbolInfoDouble(s, SYMBOL_POINT), 8),
                   SymbolInfoString(s, SYMBOL_CURRENCY_BASE), SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT),
                   (int)SymbolInfoInteger(s, SYMBOL_TRADE_CALC_MODE));
        }
      FileClose(hs);
      PrintFormat("Wrote %d server symbols to v2_probe_symbols.csv", n);
     }
   // 2/3. candidate probe
   string cands[];
   int nc = StringSplit(InpCandidates, ',', cands);
   string json = "{\n  \"server\": " + J(AccountInfoString(ACCOUNT_SERVER)) + ",\n  \"probe_time_server\": " +
                 J(Ts(TimeTradeServer())) + ",\n  \"server_utc_offset_seconds\": " +
                 IntegerToString((int)(TimeTradeServer() - TimeGMT())) + ",\n  \"symbols\": [\n";
   bool firstSym = true;
   for(int c = 0; c < nc && !IsStopped(); c++)
     {
      string sym = cands[c];
      StringTrimLeft(sym); StringTrimRight(sym);
      if(!Exists(sym))
        {
         PrintFormat("%s: not offered by this server", sym);
         continue;
        }
      SymbolSelect(sym, true);
      datetime sf = ServerFirst(sym);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      string sj = (firstSym ? "" : ",\n") + "   {\"name\": " + J(sym) + ", \"path\": " + J(SymbolInfoString(sym, SYMBOL_PATH)) +
                  ", \"digits\": " + IntegerToString(digits) + ", \"point\": " + DoubleToString(SymbolInfoDouble(sym, SYMBOL_POINT), 8) +
                  ", \"server_first_date_m1\": " + J(Ts(sf)) + ", \"tick_samples\": [";
      firstSym = false;
      int ht = FileOpen("v2_probe_ticks_" + sym + ".csv", FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
      if(ht != INVALID_HANDLE)
         FileWrite(ht, "time_msc", "bid", "ask", "last", "volume", "flags", "volume_real");
      bool firstSample = true;
      for(int y = InpFirstYear; y <= InpLastYear && !IsStopped(); y++)
         for(int m = 1; m <= 10; m += 3)
           {
            datetime from = SampleStart(y, m);
            if(from > TimeTradeServer() - 86400 || Sealed(from) || Sealed(from + 3600))
               continue;
            MqlTick ticks[];
            int err = 0;
            int got = FetchTicks(sym, from, from + 3600, ticks, err);
            int nb = 0, na = 0, nbid = 0, nask = 0, nms = 0, nlast = 0, nbuy = 0, nsell = 0;
            double spsum = 0;
            for(int k = 0; k < got; k++)
              {
               if(ticks[k].bid > 0) nb++;
               if(ticks[k].ask > 0) na++;
               if((ticks[k].flags & TICK_FLAG_BID) != 0) nbid++;
               if((ticks[k].flags & TICK_FLAG_ASK) != 0) nask++;
               if((ticks[k].flags & TICK_FLAG_LAST) != 0) nlast++;
               if((ticks[k].flags & TICK_FLAG_BUY) != 0) nbuy++;
               if((ticks[k].flags & TICK_FLAG_SELL) != 0) nsell++;
               if(ticks[k].time_msc % 1000 != 0) nms++;
               if(ticks[k].bid > 0 && ticks[k].ask > 0) spsum += ticks[k].ask - ticks[k].bid;
               if(ht != INVALID_HANDLE)
                  FileWrite(ht, (long)ticks[k].time_msc, DoubleToString(ticks[k].bid, digits), DoubleToString(ticks[k].ask, digits),
                            DoubleToString(ticks[k].last, digits), (long)ticks[k].volume, (int)ticks[k].flags,
                            DoubleToString(ticks[k].volume_real, 2));
              }
            string first_msc = got > 0 ? IntegerToString((long)ticks[0].time_msc) : "null";
            sj += (firstSample ? "" : ", ") + "{\"from\": " + J(Ts(from)) + ", \"ticks\": " + IntegerToString(got) +
                  ", \"err\": " + IntegerToString(err) + ", \"first_msc\": " + first_msc +
                  ", \"bid_gt0\": " + IntegerToString(nb) + ", \"ask_gt0\": " + IntegerToString(na) +
                  ", \"flag_bid\": " + IntegerToString(nbid) + ", \"flag_ask\": " + IntegerToString(nask) +
                  ", \"flag_last\": " + IntegerToString(nlast) + ", \"flag_buy\": " + IntegerToString(nbuy) +
                  ", \"flag_sell\": " + IntegerToString(nsell) + ", \"nonzero_ms\": " + IntegerToString(nms) +
                  ", \"mean_spread\": " + (na > 0 ? DoubleToString(spsum / MathMax(1, MathMin(nb, na)), digits + 2) : "null") + "}";
            firstSample = false;
            PrintFormat("%s %s: ticks=%d err=%d", sym, Ts(from), got, err);
           }
      if(ht != INVALID_HANDLE)
         FileClose(ht);
      json += sj + "]}";
     }
   json += "\n  ]\n}\n";
   int hj = FileOpen("v2_probe.json", FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(hj != INVALID_HANDLE)
     {
      FileWriteString(hj, json);
      FileClose(hj);
     }
   Print("V2 data probe complete: v2_probe.json, v2_probe_symbols.csv, v2_probe_ticks_*.csv in Common Files");
  }
//+------------------------------------------------------------------+

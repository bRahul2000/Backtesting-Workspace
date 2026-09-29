//+------------------------------------------------------------------+
//| V2_Export_Ticks.mq5 — Gold V2 research-only TICK SAMPLE EXPORT    |
//|                                                                  |
//| Exports bid/ask ticks for each symbol in InpSymbols (COPY_TICKS_ |
//| ALL: time_msc, bid, ask, last,                                    |
//| volume, flags) for [InpFrom, InpTo) day by day to Common Files:   |
//|   v2_ticks_<SYMBOL>_<YYYYMMDD>.csv                                |
//| Days inside SEALED windows are refused (2021-09-01..2022-11-26,  |
//| 2026-06-03 onward). No trading code, no includes, no web/socket  |
//| calls, no DLLs.                                                  |
//+------------------------------------------------------------------+
#property script_show_inputs

input string   InpSymbols = "XAUUSDm,XAGUSDm,EURUSDm,DXYm";
input datetime InpFrom    = D'2026.02.18 00:00';     // inside broker tick history (starts 2026-01/02), unsealed
input datetime InpTo      = D'2026.02.20 00:00';
input int      InpRetries = 40;
input int      InpSleepMs = 300;

bool Sealed(const datetime day)
  {
   return (day >= D'2021.09.01 00:00' && day < D'2022.11.27 00:00') || day >= D'2026.06.03 00:00';
  }

void ExportOne(const string InpSymbol)
  {
   if(!SymbolSelect(InpSymbol, true))
     {
      Print("symbol not available: ", InpSymbol);
      return;
     }
   int digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   long total = 0;
   for(datetime day = InpFrom; day < InpTo && !IsStopped(); day += 86400)
     {
      if(Sealed(day))
        {
         Print("refused sealed day ", TimeToString(day, TIME_DATE));
         continue;
        }
      MqlTick t[];
      int got = -1, err = 0;
      for(int a = 0; a < InpRetries && !IsStopped(); a++)
        {
         ResetLastError();
         got = CopyTicksRange(InpSymbol, t, COPY_TICKS_ALL, (ulong)day * 1000, (ulong)(day + 86400) * 1000 - 1);
         err = GetLastError();
         if(got >= 0 && err == 0)
            break;
         Sleep(InpSleepMs);
        }
      if(got <= 0)
        {
         PrintFormat("%s: %d ticks (err %d)", TimeToString(day, TIME_DATE), got, err);
         continue;
        }
      MqlDateTime s; TimeToStruct(day, s);
      string fname = StringFormat("v2_ticks_%s_%04d%02d%02d.csv", InpSymbol, s.year, s.mon, s.day);
      int h = FileOpen(fname, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ',');
      if(h == INVALID_HANDLE)
         continue;
      FileWrite(h, "time_msc", "bid", "ask", "last", "volume", "flags");
      for(int k = 0; k < got; k++)
         FileWrite(h, (long)t[k].time_msc, DoubleToString(t[k].bid, digits), DoubleToString(t[k].ask, digits),
                   DoubleToString(t[k].last, digits), (long)t[k].volume, (int)t[k].flags);
      FileClose(h);
      total += got;
      PrintFormat("%s: %d ticks -> %s", TimeToString(day, TIME_DATE), got, fname);
     }
   PrintFormat("%s tick export: %I64d ticks", InpSymbol, total);
  }

void OnStart()
  {
   string syms[];
   int n = StringSplit(InpSymbols, ',', syms);
   for(int i = 0; i < n && !IsStopped(); i++)
     {
      StringTrimLeft(syms[i]); StringTrimRight(syms[i]);
      ExportOne(syms[i]);
     }
   Print("V2 tick export complete.");
  }
//+------------------------------------------------------------------+

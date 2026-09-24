//+------------------------------------------------------------------+
//| TradingViewLiveFeed.mq5                                           |
//| READ-ONLY market-data service for TradingView Mode (Live).        |
//|                                                                  |
//| Writes quotes and bars for the configured symbols into           |
//| Common\Files, where the Python terminal reads them. It uses only |
//| market-data functions (SymbolInfo*, CopyRates, TerminalInfo*,    |
//| Time*). It contains no trading call of any kind and must stay    |
//| that way (tests/tradingview_mode/test_live.py checks the source).|
//+------------------------------------------------------------------+
#property service
#property copyright "Backtesting project"
#property version   "1.00"
#property description "Read-only Exness quote/bar writer for TradingView Mode Live. No trading."

input string InpSymbols    = "BTCUSDm,XAUUSDm"; // symbols to publish
input int    InpIntervalMs = 500;               // quote refresh interval
input int    InpSeedBars   = 500;               // bars per timeframe in the seed files

ENUM_TIMEFRAMES Periods[3] = {PERIOD_M15, PERIOD_M30, PERIOD_H1};
string          PeriodNames[3] = {"M15", "M30", "H1"};
string          Symbols[];
datetime        LastSeedBar[][3];
long            Seq = 0;
string          WriterId;

//--- Write to a temporary file, then move over the target, so the reader
//--- never sees a half-written file.
bool WriteAtomically(const string name, const string text)
  {
   string tmp = name + ".tmp";
   int handle = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(handle == INVALID_HANDLE)
      return false;
   FileWriteString(handle, text);
   FileClose(handle);
   return FileMove(tmp, FILE_COMMON, name, FILE_COMMON | FILE_REWRITE);
  }

string Num(const double value, const int digits)
  {
   return DoubleToString(value, digits);
  }

string BarRow(const MqlRates &bar, const int digits)
  {
   return StringFormat("[%I64d,%s,%s,%s,%s,%I64d,%d]", (long)bar.time, Num(bar.open, digits), Num(bar.high, digits),
                       Num(bar.low, digits), Num(bar.close, digits), bar.tick_volume, bar.spread);
  }

string RecentBars(const string symbol, const ENUM_TIMEFRAMES period, const int digits)
  {
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, period, 0, 3, rates);
   string rows = "";
   for(int i = 0; i < copied; i++)
      rows += (i > 0 ? "," : "") + BarRow(rates[i], digits);
   return "[" + rows + "]";
  }

void WriteSeed(const string symbol, const int s, const int p, const int digits)
  {
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, Periods[p], 0, InpSeedBars, rates);
   if(copied <= 0)
      return;
   if(rates[copied - 1].time == LastSeedBar[s][p])
      return;  // rewritten only when a new bar opens
   string text = "time,open,high,low,close,tick_volume,spread\n";
   for(int i = 0; i < copied; i++)
      text += StringFormat("%I64d,%s,%s,%s,%s,%I64d,%d\n", (long)rates[i].time, Num(rates[i].open, digits),
                           Num(rates[i].high, digits), Num(rates[i].low, digits), Num(rates[i].close, digits),
                           rates[i].tick_volume, rates[i].spread);
   if(WriteAtomically("tv_live_" + symbol + "_" + PeriodNames[p] + "_seed.csv", text))
      LastSeedBar[s][p] = rates[copied - 1].time;
  }

void WriteQuote(const string symbol, const int s)
  {
   MqlTick tick;
   if(!SymbolInfoTick(symbol, tick))
      return;
   int    digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(symbol, SYMBOL_POINT);
   long   spread = SymbolInfoInteger(symbol, SYMBOL_SPREAD);
   bool   connected = (bool)TerminalInfoInteger(TERMINAL_CONNECTED);
   Seq++;
   string bars = "";
   for(int p = 0; p < 3; p++)
     {
      WriteSeed(symbol, s, p, digits);
      bars += (p > 0 ? "," : "") + "\"" + PeriodNames[p] + "\":" + RecentBars(symbol, Periods[p], digits);
     }
   string text = StringFormat(
      "{\"schema\":1,\"writer_id\":\"%s\",\"seq\":%I64d,\"symbol\":\"%s\",\"written_gmt\":%I64d,"
      "\"server_time\":%I64d,\"gmt_time\":%I64d,\"connected\":%s,\"digits\":%d,\"point\":%s,"
      "\"spread_points\":%I64d,\"tick\":{\"time_msc\":%I64d,\"bid\":%s,\"ask\":%s,\"volume\":%I64d},\"bars\":{%s}}",
      WriterId, Seq, symbol, (long)TimeGMT(), (long)TimeTradeServer(), (long)TimeGMT(), connected ? "true" : "false",
      digits, DoubleToString(point, 10), spread, tick.time_msc, Num(tick.bid, digits), Num(tick.ask, digits),
      (long)tick.volume, bars);
   WriteAtomically("tv_live_" + symbol + "_quote.json", text);
  }

void OnStart()
  {
   int count = StringSplit(InpSymbols, ',', Symbols);
   ArrayResize(LastSeedBar, count);
   for(int s = 0; s < count; s++)
     {
      StringTrimLeft(Symbols[s]);
      StringTrimRight(Symbols[s]);
      SymbolSelect(Symbols[s], true);  // Market Watch visibility only; required for quotes
      for(int p = 0; p < 3; p++)
         LastSeedBar[s][p] = 0;
     }
   WriterId = StringFormat("%I64d-%u", (long)TimeGMT(), GetTickCount());
   PrintFormat("TradingView Live Feed started (read-only) for %s every %d ms", InpSymbols, InpIntervalMs);
   while(!IsStopped())
     {
      for(int s = 0; s < count; s++)
         WriteQuote(Symbols[s], s);
      Sleep(InpIntervalMs);
     }
  }
//+------------------------------------------------------------------+

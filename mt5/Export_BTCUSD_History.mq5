//+------------------------------------------------------------------+
//| Export_BTCUSD_History.mq5                                        |
//|                                                                  |
//| Exports the maximum available Exness BTCUSDm M15 and H1 history   |
//| as CSV plus a metadata sidecar, for the Universal Backtester's    |
//| Phase R1 broker-native validation.                                |
//|                                                                  |
//| Same output contract as Export_XAUUSD_History.mq5 so the Gold     |
//| Phase 2A ingestion path can read it unchanged:                    |
//|   timestamp,open,high,low,close,tick_volume,spread,real_volume    |
//|                                                                  |
//| The currently forming bar is always excluded (export starts at    |
//| shift 1), so every exported bar is complete.                      |
//|                                                                  |
//| IMPORTANT: run this only after the terminal has actually          |
//| downloaded deep history for both timeframes. Open the BTCUSDm     |
//| M15 and H1 charts and press Home until the chart stops extending  |
//| backwards, otherwise MT5 returns only the recent window.          |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSymbol         = "BTCUSDm";
input string InpFilePrefix     = "btcusd";
input bool   InpUseCommonFiles = true;
//--- 0 = export every bar the terminal holds.
input int    InpMaxBars        = 0;

string EffectiveSymbol()
  {
   if(StringLen(InpSymbol) > 0)
      return InpSymbol;
   return _Symbol;
  }

string SafeFilePart(string value)
  {
   StringReplace(value, "/", "_");
   StringReplace(value, "\\", "_");
   StringReplace(value, " ", "_");
   return value;
  }

string IsoServerTime(const datetime value)
  {
   return TimeToString(value, TIME_DATE|TIME_MINUTES|TIME_SECONDS);
  }

string JsonString(const string value)
  {
   string escaped = value;
   StringReplace(escaped, "\\", "\\\\");
   StringReplace(escaped, "\"", "\\\"");
   return "\"" + escaped + "\"";
  }

string OutputPath(const string file_name)
  {
   if(InpUseCommonFiles)
      return TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + file_name;
   return TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\" + file_name;
  }

bool ExportTimeframe(const string symbol, const ENUM_TIMEFRAMES timeframe,
                     const string timeframe_name, const string csv_name)
  {
   int available = Bars(symbol, timeframe);
   if(available < 2)
     {
      Print("No completed history available for ", symbol, " ", timeframe_name,
            ". Bars returned: ", available,
            ". Open the chart and press Home repeatedly to download history first.");
      return false;
     }

   int wanted = available - 1;                       // exclude the forming bar
   if(InpMaxBars > 0 && InpMaxBars < wanted)
      wanted = InpMaxBars;

   MqlRates rates[];
   int copied = CopyRates(symbol, timeframe, 1, wanted, rates);
   if(copied <= 0)
     {
      Print("CopyRates failed for ", symbol, " ", timeframe_name, ": ", GetLastError());
      return false;
     }
   ArraySetAsSeries(rates, false);

   uint flags = FILE_WRITE|FILE_CSV|FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;
   int handle = FileOpen(csv_name, flags, ',');
   if(handle == INVALID_HANDLE)
     {
      Print("Unable to open ", OutputPath(csv_name), ": ", GetLastError());
      return false;
     }

   int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
   FileWrite(handle, "timestamp", "open", "high", "low", "close",
             "tick_volume", "spread", "real_volume");
   for(int index = 0; index < copied; index++)
     {
      MqlRates bar = rates[index];
      FileWrite(handle, TimeToString(bar.time, TIME_DATE|TIME_MINUTES|TIME_SECONDS),
                DoubleToString(bar.open, digits),
                DoubleToString(bar.high, digits),
                DoubleToString(bar.low, digits),
                DoubleToString(bar.close, digits),
                (long)bar.tick_volume, (int)bar.spread, (long)bar.real_volume);
     }
   FileClose(handle);

   datetime now_server = TimeTradeServer();
   datetime now_gmt = TimeGMT();
   int offset_seconds = (int)(now_server - now_gmt);
   string metadata_name = csv_name + ".metadata.json";
   int metadata = FileOpen(metadata_name, flags|FILE_TXT, ',');
   if(metadata == INVALID_HANDLE)
     {
      Print("CSV written, but metadata file could not be opened: ",
            OutputPath(metadata_name), ": ", GetLastError());
      Print("Wrote ", copied, " completed ", timeframe_name, " bars to ", OutputPath(csv_name));
      return true;
     }
   string json = "{\n";
   json += "  \"source\": \"MT5 CopyRates broker history\",\n";
   json += "  \"symbol\": " + JsonString(symbol) + ",\n";
   json += "  \"timeframe\": " + JsonString(timeframe_name) + ",\n";
   json += "  \"timestamp_field_timezone\": \"broker trade-server time; see server_utc_offset_seconds_at_capture\",\n";
   json += "  \"server_utc_offset_seconds_at_capture\": " + IntegerToString(offset_seconds) + ",\n";
   json += "  \"broker_company\": " + JsonString(AccountInfoString(ACCOUNT_COMPANY)) + ",\n";
   json += "  \"account_server\": " + JsonString(AccountInfoString(ACCOUNT_SERVER)) + ",\n";
   json += "  \"digits\": " + IntegerToString(digits) + ",\n";
   json += "  \"point\": " + DoubleToString(SymbolInfoDouble(symbol, SYMBOL_POINT), 10) + ",\n";
   json += "  \"bars_available_in_terminal\": " + IntegerToString(available) + ",\n";
   json += "  \"bars_exported\": " + IntegerToString(copied) + ",\n";
   json += "  \"first_bar_server_time\": " + JsonString(IsoServerTime(rates[0].time)) + ",\n";
   json += "  \"last_bar_server_time\": " + JsonString(IsoServerTime(rates[copied - 1].time)) + ",\n";
   json += "  \"current_incomplete_bar_excluded\": true,\n";
   json += "  \"spread_field_semantics\": \"MT5 bar spread is a bar-level spread descriptor in points, not the spread guaranteed at an execution tick\",\n";
   json += "  \"capture_server_time\": " + JsonString(IsoServerTime(now_server)) + ",\n";
   json += "  \"output_file\": " + JsonString(OutputPath(csv_name)) + "\n";
   json += "}\n";
   FileWriteString(metadata, json);
   FileClose(metadata);

   Print("Wrote ", copied, " completed ", timeframe_name, " bars to ", OutputPath(csv_name));
   Print("Wrote metadata to ", OutputPath(metadata_name));
   return true;
  }

void OnStart()
  {
   string symbol = EffectiveSymbol();
   ResetLastError();
   if(!SymbolSelect(symbol, true))
     {
      Print("Unable to select symbol ", symbol, ": ", GetLastError());
      return;
     }

   string prefix = SafeFilePart(InpFilePrefix) + "_" + SafeFilePart(symbol);
   bool m15_ok = ExportTimeframe(symbol, PERIOD_M15, "M15", prefix + "_M15.csv");
   bool h1_ok  = ExportTimeframe(symbol, PERIOD_H1,  "H1",  prefix + "_H1.csv");
   bool m30_ok = ExportTimeframe(symbol, PERIOD_M30, "M30", prefix + "_M30.csv");
   Print("BTC history export complete for ", symbol,
         ". M15=", m15_ok ? "OK" : "FAILED",
         ", M30=" + (m30_ok ? "OK" : "FAILED"),
         ", H1=",  h1_ok  ? "OK" : "FAILED");
  }

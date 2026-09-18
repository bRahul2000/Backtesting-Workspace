#property script_show_inputs

input string InpSymbol = "";
input string InpFilePrefix = "xauusd";
input bool   InpUseCommonFiles = true;

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
   string root;
   if(InpUseCommonFiles)
      root = TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\";
   else
      root = TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\";
   return root + file_name;
  }

bool ExportTimeframe(const string symbol, const ENUM_TIMEFRAMES timeframe,
                     const string timeframe_name, const string csv_name)
  {
   int available = Bars(symbol, timeframe);
   if(available < 2)
     {
      Print("No completed history available for ", symbol, " ", timeframe_name,
            ". Bars returned: ", available);
      return false;
     }

   MqlRates rates[];
   // Start at shift 1 so the currently forming bar is excluded.
   int copied = CopyRates(symbol, timeframe, 1, available - 1, rates);
   if(copied <= 0)
     {
      Print("CopyRates failed for ", symbol, " ", timeframe_name,
            ": ", GetLastError());
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

   FileWrite(handle, "timestamp", "open", "high", "low", "close",
             "tick_volume", "spread", "real_volume");
   for(int index = 0; index < copied; index++)
     {
      MqlRates bar = rates[index];
      FileWrite(handle, TimeToString(bar.time, TIME_DATE|TIME_MINUTES|TIME_SECONDS),
                DoubleToString(bar.open, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
                DoubleToString(bar.high, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
                DoubleToString(bar.low, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
                DoubleToString(bar.close, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS)),
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
      Print("Wrote ", copied, " completed ", timeframe_name, " bars to ",
            OutputPath(csv_name));
      return true;
     }
   string json = "{\n";
   json += "  \"source\": \"MT5 CopyRates broker history\",\n";
   json += "  \"symbol\": " + JsonString(symbol) + ",\n";
   json += "  \"timeframe\": " + JsonString(timeframe_name) + ",\n";
   json += "  \"timestamp_field_timezone\": \"broker trade-server time; see server_utc_offset_seconds\",\n";
   json += "  \"server_utc_offset_seconds_at_capture\": " + IntegerToString(offset_seconds) + ",\n";
   json += "  \"account_server\": " + JsonString(AccountInfoString(ACCOUNT_SERVER)) + ",\n";
   json += "  \"bars_exported\": " + IntegerToString(copied) + ",\n";
   json += "  \"current_incomplete_bar_excluded\": true,\n";
   json += "  \"capture_server_time\": " + JsonString(IsoServerTime(now_server)) + ",\n";
   json += "  \"output_file\": " + JsonString(OutputPath(csv_name)) + "\n";
   json += "}\n";
   FileWriteString(metadata, json);
   FileClose(metadata);

   Print("Wrote ", copied, " completed ", timeframe_name, " bars to ",
         OutputPath(csv_name));
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
   bool h1_ok = ExportTimeframe(symbol, PERIOD_H1, "H1", prefix + "_H1.csv");
   Print("Gold history export complete for ", symbol,
         ". M15=", m15_ok ? "OK" : "FAILED",
         ", H1=", h1_ok ? "OK" : "FAILED");
  }

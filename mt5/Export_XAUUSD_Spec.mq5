#property script_show_inputs

input string InpSymbol = "XAUUSDm";
input string InpProfileId = "EXNESS-XAUUSD-v1";
input string InpOutputFile = "xauusd_mt5_spec.json";

string JsonString(const string value) { return "\"" + value + "\""; }

string JsonDouble(const double value)
  {
   if(!MathIsValidNumber(value) || value == 0.0)
      return "null";
   return DoubleToString(value, 10);
  }

  string TradingSessions(const string symbol)
    {
    string output = "[";
    bool first = true;
    for(int day = DAY_SUNDAY; day <= DAY_SATURDAY; day++)
      {
      for(uint index = 0; index < 16; index++)
        {
        datetime from, to;
        if(!SymbolInfoSessionTrade(symbol, (ENUM_DAY_OF_WEEK)day, index, from, to))
          break;
        if(!first)
          output += ",";
        output += JsonString(IntegerToString(day) + " " + TimeToString(from, TIME_MINUTES) + "-" + TimeToString(to, TIME_MINUTES));
        first = false;
        }
      }
    return output + "]";
    }

void OnStart()
  {
   ResetLastError();
   if(!SymbolSelect(InpSymbol, true))
     {
      Print("Unable to select symbol ", InpSymbol, ": ", GetLastError());
      return;
     }
  int handle = FileOpen(InpOutputFile, FILE_WRITE|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle == INVALID_HANDLE)
     {
      Print("Unable to open output file ", TerminalInfoString(TERMINAL_COMMONDATA_PATH),
        "\\Files\\", InpOutputFile, ": ", GetLastError());
      return;
     }
   string server = AccountInfoString(ACCOUNT_SERVER);
   string json = "{\n";
   json += "  \"profile_id\": " + JsonString(InpProfileId) + ",\n";
   json += "  \"broker\": \"Exness\",\n";
   json += "  \"account_server\": " + JsonString(server) + ",\n";
   json += "  \"symbol\": " + JsonString(InpSymbol) + ",\n";
   json += "  \"description\": " + JsonString(SymbolInfoString(InpSymbol, SYMBOL_DESCRIPTION)) + ",\n";
   json += "  \"digits\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS)) + ",\n";
   json += "  \"point\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_POINT)) + ",\n";
   json += "  \"tick_size\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE)) + ",\n";
   json += "  \"tick_value\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE)) + ",\n";
   json += "  \"tick_value_profit\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE_PROFIT)) + ",\n";
   json += "  \"tick_value_loss\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE_LOSS)) + ",\n";
   json += "  \"contract_size\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_CONTRACT_SIZE)) + ",\n";
   json += "  \"volume_min\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN)) + ",\n";
   json += "  \"volume_max\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX)) + ",\n";
   json += "  \"volume_step\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP)) + ",\n";
   json += "  \"stops_level\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL)) + ",\n";
   json += "  \"freeze_level\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_FREEZE_LEVEL)) + ",\n";
   json += "  \"margin_calculation_mode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_CALC_MODE)) + ",\n";
   json += "  \"margin_initial\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_MARGIN_INITIAL)) + ",\n";
   json += "  \"margin_maintenance\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_MARGIN_MAINTENANCE)) + ",\n";
   json += "  \"swap_long\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_SWAP_LONG)) + ",\n";
   json += "  \"swap_short\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_SWAP_SHORT)) + ",\n";
   json += "  \"swap_mode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_SWAP_MODE)) + ",\n";
  json += "  \"trading_sessions\": " + TradingSessions(InpSymbol) + ",\n";
   json += "  \"bid\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_BID)) + ",\n";
   json += "  \"ask\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_ASK)) + ",\n";
   json += "  \"spread\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_ASK) - SymbolInfoDouble(InpSymbol, SYMBOL_BID)) + ",\n";
   json += "  \"capture_timestamp_utc\": " + JsonString(TimeToString(TimeGMT(), TIME_DATE|TIME_SECONDS)) + ",\n";
   json += "  \"source\": \"MT5 SymbolInfo capture; no credentials collected\"\n";
   json += "}\n";
   FileWriteString(handle, json);
   FileClose(handle);
     Print("Wrote ", TerminalInfoString(TERMINAL_COMMONDATA_PATH), "\\Files\\",
       InpOutputFile, " for ", InpSymbol);
  }
//+------------------------------------------------------------------+
//| Export_BTCUSD_Spec.mq5                                           |
//|                                                                  |
//| Captures the live Exness BTCUSDm symbol specification as JSON for |
//| the Universal Backtester's Phase R1 broker-native validation.     |
//|                                                                  |
//| Schema matches the Gold Phase 2A snapshot                         |
//| (data/exness/gold/phase2a/raw/xauusd_mt5_spec.json) so the same   |
//| loader and manifest machinery can read it.                        |
//|                                                                  |
//| Collects NO credentials. Leverage, commission and margin          |
//| assumptions are emitted as explicit UNVERIFIED markers: MT5 does  |
//| not expose a trustworthy per-symbol value for them, and a zero    |
//| capture must never be read as a true zero.                        |
//+------------------------------------------------------------------+
#property script_show_inputs

input string InpSymbol      = "BTCUSDm";
input string InpProfileId   = "EXNESS-BTCUSD-v1";
input string InpOutputFile  = "btcusd_mt5_spec.json";
input bool   InpUseCommonFiles = true;

string JsonString(const string value)
  {
   string escaped = value;
   StringReplace(escaped, "\\", "\\\\");
   StringReplace(escaped, "\"", "\\\"");
   return "\"" + escaped + "\"";
  }

string JsonDouble(const double value, const int digits = 10)
  {
   if(!MathIsValidNumber(value))
      return "null";
   return DoubleToString(value, digits);
  }

string OutputPath(const string file_name)
  {
   if(InpUseCommonFiles)
      return TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files\\" + file_name;
   return TerminalInfoString(TERMINAL_DATA_PATH) + "\\MQL5\\Files\\" + file_name;
  }

//--- SYMBOL_FILLING_MODE is a bitmask; report every supported mode.
string FillingModes(const string symbol)
  {
   int mask = (int)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   string output = "[";
   bool first = true;
   if((mask & SYMBOL_FILLING_FOK) != 0) { output += JsonString("FOK"); first = false; }
   if((mask & SYMBOL_FILLING_IOC) != 0) { if(!first) output += ","; output += JsonString("IOC"); first = false; }
   if((mask & SYMBOL_FILLING_BOC) != 0) { if(!first) output += ","; output += JsonString("BOC"); first = false; }
   return output + "]";
  }

string TradeModeName(const int mode)
  {
   switch(mode)
     {
      case SYMBOL_TRADE_MODE_DISABLED:   return "DISABLED";
      case SYMBOL_TRADE_MODE_LONGONLY:   return "LONGONLY";
      case SYMBOL_TRADE_MODE_SHORTONLY:  return "SHORTONLY";
      case SYMBOL_TRADE_MODE_CLOSEONLY:  return "CLOSEONLY";
      case SYMBOL_TRADE_MODE_FULL:       return "FULL";
     }
   return "UNKNOWN";
  }

string TradingSessions(const string symbol)
  {
   string names[7] = {"Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"};
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
         output += "{\"day_number\":" + IntegerToString(day) +
                   ",\"day\":" + JsonString(names[day]) +
                   ",\"session_index\":" + IntegerToString((int)index) +
                   ",\"from\":" + JsonString(TimeToString(from, TIME_MINUTES)) +
                   ",\"to\":" + JsonString(TimeToString(to, TIME_MINUTES)) + "}";
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

   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   int    digits = (int)SymbolInfoInteger(InpSymbol, SYMBOL_DIGITS);
   double point  = SymbolInfoDouble(InpSymbol, SYMBOL_POINT);

   uint flags = FILE_WRITE|FILE_TXT|FILE_ANSI;
   if(InpUseCommonFiles)
      flags |= FILE_COMMON;
   int handle = FileOpen(InpOutputFile, flags);
   if(handle == INVALID_HANDLE)
     {
      Print("Unable to open ", OutputPath(InpOutputFile), ": ", GetLastError());
      return;
     }

   string json = "{\n";
   json += "  \"schema_version\": \"1.0\",\n";
   json += "  \"profile_type\": \"MT5_SYMBOL_SPECIFICATION\",\n";
   json += "  \"profile_id\": " + JsonString(InpProfileId) + ",\n";
   json += "  \"capture\": {\n";
   json += "    \"timestamp_utc\": " + JsonString(TimeToString(TimeGMT(), TIME_DATE|TIME_SECONDS)) + ",\n";
   json += "    \"timestamp_server\": " + JsonString(TimeToString(TimeTradeServer(), TIME_DATE|TIME_SECONDS)) + ",\n";
   json += "    \"server_utc_offset_seconds\": " + IntegerToString((int)(TimeTradeServer() - TimeGMT())) + ",\n";
   json += "    \"terminal_common_data_path\": " + JsonString(TerminalInfoString(TERMINAL_COMMONDATA_PATH)) + "\n";
   json += "  },\n";
   json += "  \"broker\": {\n";
   json += "    \"company\": " + JsonString(AccountInfoString(ACCOUNT_COMPANY)) + ",\n";
   json += "    \"server\": " + JsonString(AccountInfoString(ACCOUNT_SERVER)) + "\n";
   json += "  },\n";
   json += "  \"symbol\": {\n";
   json += "    \"name\": " + JsonString(InpSymbol) + ",\n";
   json += "    \"description\": " + JsonString(SymbolInfoString(InpSymbol, SYMBOL_DESCRIPTION)) + ",\n";
   json += "    \"currency_base\": " + JsonString(SymbolInfoString(InpSymbol, SYMBOL_CURRENCY_BASE)) + ",\n";
   json += "    \"currency_profit\": " + JsonString(SymbolInfoString(InpSymbol, SYMBOL_CURRENCY_PROFIT)) + ",\n";
   json += "    \"currency_margin\": " + JsonString(SymbolInfoString(InpSymbol, SYMBOL_CURRENCY_MARGIN)) + ",\n";
   json += "    \"digits\": " + IntegerToString(digits) + ",\n";
   json += "    \"point\": " + JsonDouble(point) + "\n";
   json += "  },\n";
   json += "  \"contract\": {\n";
   json += "    \"tick_size\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_SIZE)) + ",\n";
   json += "    \"tick_value\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE)) + ",\n";
   json += "    \"tick_value_profit\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE_PROFIT)) + ",\n";
   json += "    \"tick_value_loss\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_TICK_VALUE_LOSS)) + ",\n";
   json += "    \"contract_size\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_TRADE_CONTRACT_SIZE)) + "\n";
   json += "  },\n";
   json += "  \"volume\": {\n";
   json += "    \"minimum\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN)) + ",\n";
   json += "    \"maximum\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX)) + ",\n";
   json += "    \"step\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP)) + "\n";
   json += "  },\n";
   json += "  \"trading\": {\n";
   json += "    \"trade_mode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_MODE)) + ",\n";
   json += "    \"trade_mode_name\": " + JsonString(TradeModeName((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_MODE))) + ",\n";
   json += "    \"trade_exemode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_EXEMODE)) + ",\n";
   json += "    \"trade_calc_mode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_CALC_MODE)) + ",\n";
   json += "    \"filling_modes\": " + FillingModes(InpSymbol) + ",\n";
   json += "    \"filling_mode_mask\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_FILLING_MODE)) + ",\n";
   json += "    \"order_mode_mask\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_ORDER_MODE)) + ",\n";
   json += "    \"expiration_mode_mask\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_EXPIRATION_MODE)) + ",\n";
   json += "    \"stops_level_points\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_STOPS_LEVEL)) + ",\n";
   json += "    \"freeze_level_points\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_TRADE_FREEZE_LEVEL)) + ",\n";
   json += "    \"spread_points_reported\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_SPREAD)) + ",\n";
   json += "    \"spread_float\": " + ((bool)SymbolInfoInteger(InpSymbol, SYMBOL_SPREAD_FLOAT) ? "true" : "false") + "\n";
   json += "  },\n";
   json += "  \"quote\": {\n";
   json += "    \"bid\": " + JsonDouble(bid, digits) + ",\n";
   json += "    \"ask\": " + JsonDouble(ask, digits) + ",\n";
   json += "    \"last\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_LAST), digits) + ",\n";
   json += "    \"spread_price\": " + JsonDouble(ask - bid, digits) + ",\n";
   json += "    \"spread_points\": " + JsonDouble((point > 0.0) ? (ask - bid) / point : 0.0, 4) + "\n";
   json += "  },\n";
   //--- Captured verbatim, but never to be trusted as an economic assumption.
   json += "  \"raw_margin_swap_capture\": {\n";
   json += "    \"margin_initial\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_MARGIN_INITIAL)) + ",\n";
   json += "    \"margin_maintenance\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_MARGIN_MAINTENANCE)) + ",\n";
   json += "    \"swap_mode\": " + IntegerToString((int)SymbolInfoInteger(InpSymbol, SYMBOL_SWAP_MODE)) + ",\n";
   json += "    \"swap_long\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_SWAP_LONG)) + ",\n";
   json += "    \"swap_short\": " + JsonDouble(SymbolInfoDouble(InpSymbol, SYMBOL_SWAP_SHORT)) + ",\n";
   json += "    \"account_leverage_reported\": " + IntegerToString((int)AccountInfoInteger(ACCOUNT_LEVERAGE)) + "\n";
   json += "  },\n";
   json += "  \"unverified\": {\n";
   json += "    \"leverage_status\": \"UNVERIFIED\",\n";
   json += "    \"commission_status\": \"UNVERIFIED\",\n";
   json += "    \"margin_status\": \"UNVERIFIED\",\n";
   json += "    \"note\": \"MT5 does not expose a trustworthy per-symbol commission, and a zero margin or swap capture does not imply a true zero. These must not be modelled as costs without an independent account-statement verification.\"\n";
   json += "  },\n";
   json += "  \"trading_sessions\": " + TradingSessions(InpSymbol) + ",\n";
   json += "  \"source\": \"MT5 SymbolInfo capture; no credentials collected\"\n";
   json += "}\n";

   FileWriteString(handle, json);
   FileClose(handle);
   Print("Wrote ", OutputPath(InpOutputFile), " for ", InpSymbol);
  }


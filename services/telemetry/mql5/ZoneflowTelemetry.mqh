//+------------------------------------------------------------------+
//| ZoneflowTelemetry.mqh - Telemetry V1 spool writer for MQL5       |
//|                                                                  |
//| Appends one self-checking JSON line per fact to                  |
//|   <Common Files>\Zoneflow\telemetry\spool\<writer>\<UTC day>.jsonl |
//| Line: {"schema_version":1,...,"crc32":"xxxxxxxx"}\n where the CRC |
//| covers the UTF-8 bytes before ,"crc32":" (services/telemetry/     |
//| schema.py checks it).                                            |
//|                                                                  |
//| SAFETY CONTRACT                                                  |
//|  - no trade function is called anywhere in this file             |
//|  - every function returns; none blocks, sleeps or stops the      |
//|    program; a failed write only increments ZfWriteFailures()     |
//|  - the account login is never written, only a SHA-256 reference  |
//|  - telemetry never feeds back into any caller's decisions        |
//+------------------------------------------------------------------+
#property strict

#define ZF_SCHEMA_VERSION 1
#define ZF_ROOT           "Zoneflow\\telemetry"

//--- writer identity, fixed at ZfInit
string g_zf_writer_id      = "";
string g_zf_run_id         = "";
string g_zf_strategy_id    = "";
string g_zf_strategy_ver   = "";
string g_zf_params_hash    = "";
string g_zf_capture_mode   = "realtime";
string g_zf_broker         = "";
string g_zf_server         = "";
string g_zf_environment    = "";
string g_zf_account_ref    = "";
long   g_zf_sequence       = 0;
long   g_zf_write_failures = 0;
long   g_zf_events_written = 0;
uint   g_zf_crc_table[256];
bool   g_zf_ready          = false;

long ZfWriteFailures() { return g_zf_write_failures; }
long ZfEventsWritten() { return g_zf_events_written; }
string ZfRunId()       { return g_zf_run_id; }

//+------------------------------------------------------------------+
//| CRC-32 (IEEE 802.3, same as zlib.crc32)                          |
//+------------------------------------------------------------------+
void ZfCrcInit()
  {
   for(uint n = 0; n < 256; n++)
     {
      uint c = n;
      for(int k = 0; k < 8; k++)
         c = ((c & 1) != 0) ? (0xEDB88320 ^ (c >> 1)) : (c >> 1);
      g_zf_crc_table[n] = c;
     }
  }

uint ZfCrc32(const uchar &data[], const int count)
  {
   uint c = 0xFFFFFFFF;
   for(int i = 0; i < count; i++)
      c = g_zf_crc_table[(c ^ data[i]) & 0xFF] ^ (c >> 8);
   return c ^ 0xFFFFFFFF;
  }

//+------------------------------------------------------------------+
//| Text helpers                                                     |
//+------------------------------------------------------------------+
string ZfEscape(const string text)
  {
   string out = "";
   int n = StringLen(text);
   for(int i = 0; i < n; i++)
     {
      ushort ch = StringGetCharacter(text, i);
      if(ch == '"')       out += "\\\"";
      else if(ch == '\\') out += "\\\\";
      else if(ch < 0x20)  out += StringFormat("\\u%04x", ch);
      else                out += ShortToString(ch);
     }
   return out;
  }

// UTC ISO-8601 from seconds, or from milliseconds since 1970
string ZfIsoSeconds(const datetime utc)
  {
   MqlDateTime t;
   TimeToStruct(utc, t);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ", t.year, t.mon, t.day, t.hour, t.min, t.sec);
  }

string ZfIsoMs(const long utc_ms)
  {
   MqlDateTime t;
   TimeToStruct((datetime)(utc_ms / 1000), t);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d.%03dZ", t.year, t.mon, t.day, t.hour, t.min, t.sec,
                       (int)(utc_ms % 1000));
  }

string ZfServerMs(const long server_ms)
  {
   return TimeToString((datetime)(server_ms / 1000), TIME_DATE | TIME_SECONDS) + StringFormat(".%03d", (int)(server_ms % 1000));
  }

// broker server clock minus UTC, rounded to 15 minutes (brokers use whole quarter-hour offsets)
int ZfServerOffsetSeconds()
  {
   long raw = (long)TimeTradeServer() - (long)TimeGMT();
   return (int)(MathRound(raw / 900.0) * 900);
  }

string ZfDirection(const long deal_or_order_type)
  {
   switch((int)deal_or_order_type)
     {
      case ORDER_TYPE_BUY: case ORDER_TYPE_BUY_LIMIT: case ORDER_TYPE_BUY_STOP: case ORDER_TYPE_BUY_STOP_LIMIT:
         return "buy";
      case ORDER_TYPE_SELL: case ORDER_TYPE_SELL_LIMIT: case ORDER_TYPE_SELL_STOP: case ORDER_TYPE_SELL_STOP_LIMIT:
         return "sell";
     }
   return "";
  }

//+------------------------------------------------------------------+
//| Event builder: fields are only added when known (absent = null)  |
//+------------------------------------------------------------------+
class ZfEvent
  {
private:
   string m_body;
public:
                     ZfEvent(const string event_type)
     {
      m_body = "";
      g_zf_sequence++;
      Str("telemetry_event_id", g_zf_writer_id + ":" + g_zf_run_id + ":" + IntegerToString(g_zf_sequence));
      Str("writer_id", g_zf_writer_id);
      Str("writer_run_id", g_zf_run_id);
      Int("sequence", g_zf_sequence);
      Str("event_type", event_type);
      Str("capture_mode", g_zf_capture_mode);
      Str("strategy_id", g_zf_strategy_id);
      Str("strategy_version", g_zf_strategy_ver);
      Str("strategy_parameters_hash", g_zf_params_hash);
      Str("broker", g_zf_broker);
      Str("account_server", g_zf_server);
      Str("account_environment", g_zf_environment);
      Str("account_ref", g_zf_account_ref);
     }
   void              Str(const string key, const string value)
     {
      if(StringLen(value) > 0)
         m_body += ",\"" + key + "\":\"" + ZfEscape(value) + "\"";
     }
   void              Int(const string key, const long value) { m_body += ",\"" + key + "\":" + IntegerToString(value); }
   void              IntIfSet(const string key, const long value) { if(value != 0) Int(key, value); }
   void              Num(const string key, const double value, const int digits)
     {
      if(MathIsValidNumber(value))
         m_body += ",\"" + key + "\":" + DoubleToString(value, digits);
     }
   void              NumIfSet(const string key, const double value, const int digits) { if(value != 0.0) Num(key, value, digits); }
   void              Bool(const string key, const bool value) { m_body += ",\"" + key + "\":" + (value ? "true" : "false"); }
   void              TsSeconds(const string key, const datetime utc) { if(utc > 0) Str(key, ZfIsoSeconds(utc)); }
   void              TsMs(const string key, const long utc_ms) { if(utc_ms > 0) Str(key, ZfIsoMs(utc_ms)); }
   // raw JSON object (runtime / strategy_state) - caller builds it with ZfObject
   void              Obj(const string key, const string json_object) { if(StringLen(json_object) > 1) m_body += ",\"" + key + "\":" + json_object; }
   // broker server-clock milliseconds -> broker_time_server (as reported) + broker_utc + offset used
   void              BrokerTime(const long server_ms, const bool is_fill)
     {
      if(server_ms <= 0)
         return;
      int offset = ZfServerOffsetSeconds();
      Str("broker_time_server", ZfServerMs(server_ms));
      Int("server_utc_offset_s", offset);
      TsMs("broker_utc", server_ms - (long)offset * 1000);
      if(is_fill)
         TsMs("fill_utc", server_ms - (long)offset * 1000);
     }
   void              Quote(const string symbol)
     {
      MqlTick tick;
      if(StringLen(symbol) == 0 || !SymbolInfoTick(symbol, tick))
         return;
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      Num("bid", tick.bid, digits);
      Num("ask", tick.ask, digits);
      Int("spread_points", SymbolInfoInteger(symbol, SYMBOL_SPREAD));
     }
   bool              Write()
     {
      if(!g_zf_ready)
        {
         g_zf_write_failures++;
         return false;
        }
      datetime now = TimeGMT();
      string text = "{\"schema_version\":" + IntegerToString(ZF_SCHEMA_VERSION) + m_body
                    + ",\"local_capture_utc\":\"" + ZfIsoSeconds(now) + "\"";
      uchar prefix[];
      int n = StringToCharArray(text, prefix, 0, WHOLE_ARRAY, CP_UTF8) - 1;   // drop the terminating zero
      if(n <= 0)
        {
         g_zf_write_failures++;
         return false;
        }
      ArrayResize(prefix, n);
      string tail = ",\"crc32\":\"" + StringFormat("%08x", ZfCrc32(prefix, n)) + "\"}\n";
      uchar tail_bytes[];
      int t = StringToCharArray(tail, tail_bytes, 0, WHOLE_ARRAY, CP_UTF8) - 1;
      ArrayResize(prefix, n + t);
      ArrayCopy(prefix, tail_bytes, n, 0, t);
      MqlDateTime d;
      TimeToStruct(now, d);
      string path = ZF_ROOT + "\\spool\\" + g_zf_writer_id + "\\" + StringFormat("%04d-%02d-%02d", d.year, d.mon, d.day) + ".jsonl";
      if(ZfAppend(path, prefix))
        {
         g_zf_events_written++;
         return true;
        }
      g_zf_write_failures++;
      return false;
     }
  };

//+------------------------------------------------------------------+
//| Append bytes to a Common Files file; seal a torn tail first.      |
//| Three quick attempts, no sleeping. Never throws, never stops.     |
//+------------------------------------------------------------------+
bool ZfAppend(const string path, const uchar &bytes[])
  {
   for(int attempt = 0; attempt < 3; attempt++)
     {
      ResetLastError();
      int h = FileOpen(path, FILE_READ | FILE_WRITE | FILE_BIN | FILE_COMMON | FILE_SHARE_READ);
      if(h == INVALID_HANDLE)
         continue;
      ulong size = FileSize(h);
      if(size > 0)
        {
         FileSeek(h, -1, SEEK_END);
         uchar last[];
         if(FileReadArray(h, last, 0, 1) == 1 && last[0] != 10)
           {
            uchar newline[1];
            newline[0] = 10;
            FileSeek(h, 0, SEEK_END);
            FileWriteArray(h, newline, 0, 1);
           }
        }
      FileSeek(h, 0, SEEK_END);
      uint written = FileWriteArray(h, bytes, 0, ArraySize(bytes));
      FileFlush(h);
      FileClose(h);
      if(written == (uint)ArraySize(bytes))
         return true;
     }
   return false;
  }

void ZfEnsureFolder(const string folder)
  {
   string parts[];
   int n = StringSplit(folder, '\\', parts);
   string path = "";
   for(int i = 0; i < n; i++)
     {
      path = (i == 0) ? parts[i] : path + "\\" + parts[i];
      FolderCreate(path, FILE_COMMON);
     }
  }

// SHA-256(login|server), first 8 bytes as hex: identifies the account in telemetry without the login itself
string ZfAccountRef()
  {
   string text = IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "|" + AccountInfoString(ACCOUNT_SERVER);
   uchar data[], key[], hash[];
   StringToCharArray(text, data, 0, StringLen(text), CP_UTF8);
   if(CryptEncode(CRYPT_HASH_SHA256, data, key, hash) < 8)
      return "";
   string hex = "";
   for(int i = 0; i < 8; i++)
      hex += StringFormat("%02x", hash[i]);
   return hex;
  }

string ZfEnvironment()
  {
   switch((int)AccountInfoInteger(ACCOUNT_TRADE_MODE))
     {
      case ACCOUNT_TRADE_MODE_DEMO:    return "demo";
      case ACCOUNT_TRADE_MODE_CONTEST: return "contest";
      case ACCOUNT_TRADE_MODE_REAL:    return "real";
     }
   return "";
  }

// writer ids become folder names: keep [A-Za-z0-9._-]
string ZfSafeId(const string text)
  {
   string out = "";
   for(int i = 0; i < StringLen(text) && StringLen(out) < 48; i++)
     {
      ushort ch = StringGetCharacter(text, i);
      bool ok = (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || ch == '.' || ch == '_' || ch == '-';
      out += ok ? ShortToString(ch) : "_";
     }
   return out;
  }

//+------------------------------------------------------------------+
//| Initialise once in OnInit. Returns false only if the spool folder |
//| cannot be prepared - callers must NOT treat that as a reason to   |
//| change trading; it only means telemetry is off (and counted).     |
//+------------------------------------------------------------------+
bool ZfInit(const string writer_id, const string strategy_id, const string strategy_version,
            const string parameters_hash, const string capture_mode)
  {
   ZfCrcInit();
   MathSrand((uint)(GetTickCount() ^ (uint)GetMicrosecondCount()));
   g_zf_writer_id    = ZfSafeId(writer_id);
   g_zf_strategy_id  = ZfSafeId(strategy_id);
   g_zf_strategy_ver = strategy_version;
   g_zf_params_hash  = parameters_hash;
   g_zf_capture_mode = capture_mode;
   g_zf_run_id       = StringFormat("r%I64x%04x%04x", (long)TimeGMT(), MathRand() & 0xFFFF,
                                    (uint)(GetMicrosecondCount() & 0xFFFF));
   g_zf_sequence     = 0;
   g_zf_broker       = AccountInfoString(ACCOUNT_COMPANY);
   g_zf_server       = AccountInfoString(ACCOUNT_SERVER);
   g_zf_environment  = ZfEnvironment();
   g_zf_account_ref  = ZfAccountRef();
   ZfEnsureFolder(ZF_ROOT + "\\spool\\" + g_zf_writer_id);
   g_zf_ready = StringLen(g_zf_writer_id) > 0 && StringLen(g_zf_strategy_id) > 0;
   return g_zf_ready;
  }

//+------------------------------------------------------------------+
//| Tiny JSON object builder for runtime / strategy_state            |
//+------------------------------------------------------------------+
class ZfObject
  {
private:
   string m_text;
public:
                     ZfObject() { m_text = ""; }
   void              Str(const string k, const string v) { Add(k, "\"" + ZfEscape(v) + "\""); }
   void              Int(const string k, const long v)   { Add(k, IntegerToString(v)); }
   void              Num(const string k, const double v, const int digits) { if(MathIsValidNumber(v)) Add(k, DoubleToString(v, digits)); }
   void              Bool(const string k, const bool v)  { Add(k, v ? "true" : "false"); }
   void              Add(const string k, const string raw) { m_text += (StringLen(m_text) > 0 ? "," : "") + "\"" + k + "\":" + raw; }
   string            Json() { return "{" + m_text + "}"; }
  };

//+------------------------------------------------------------------+
//| Strategy-side hooks (capture_mode = "strategy").                 |
//| Call them AFTER the strategy has made its own decision; ignore   |
//| their return values. They never alter a request or a result.     |
//+------------------------------------------------------------------+
void ZfStrategySignal(const string symbol, const long magic, const string direction, const double signal_price,
                      const datetime signal_time_server, const string strategy_state_json)
  {
   ZfEvent e("signal_generated");
   e.Str("symbol", symbol);
   e.Int("magic_number", magic);
   e.Str("direction", direction);
   e.Num("signal_price", signal_price, (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS));
   if(signal_time_server > 0)
      e.TsSeconds("signal_utc", signal_time_server - ZfServerOffsetSeconds());
   e.Quote(symbol);
   e.Obj("strategy_state", strategy_state_json);
   e.Write();
  }

void ZfStrategyOrderRequested(const MqlTradeRequest &request)
  {
   ZfEvent e(request.action == TRADE_ACTION_SLTP ? "position_modified" : "order_requested");
   int digits = (int)SymbolInfoInteger(request.symbol, SYMBOL_DIGITS);
   e.Str("symbol", request.symbol);
   e.Int("magic_number", (long)request.magic);
   e.Str("direction", ZfDirection(request.type));
   e.TsSeconds("request_utc", TimeGMT());
   e.NumIfSet("requested_price", request.price, digits);
   e.NumIfSet("requested_volume", request.volume, 8);
   e.NumIfSet("stop_loss", request.sl, digits);
   e.NumIfSet("take_profit", request.tp, digits);
   e.IntIfSet("position_id", (long)request.position);
   e.Quote(request.symbol);
   e.Write();
  }

void ZfStrategyOrderResult(const MqlTradeRequest &request, const MqlTradeResult &result, const int last_error)
  {
   bool ok = result.retcode == TRADE_RETCODE_DONE || result.retcode == TRADE_RETCODE_PLACED
             || result.retcode == TRADE_RETCODE_DONE_PARTIAL;
   ZfEvent e(ok ? "order_accepted" : "order_rejected");
   int digits = (int)SymbolInfoInteger(request.symbol, SYMBOL_DIGITS);
   e.Str("symbol", request.symbol);
   e.Int("magic_number", (long)request.magic);
   e.Str("direction", ZfDirection(request.type));
   e.IntIfSet("order_id", (long)result.order);
   e.IntIfSet("ticket_id", (long)result.order);
   e.IntIfSet("deal_id", (long)result.deal);
   e.NumIfSet("requested_price", request.price, digits);
   e.NumIfSet("requested_volume", request.volume, 8);
   e.NumIfSet("fill_price", result.price, digits);
   e.NumIfSet("filled_volume", result.volume, 8);
   e.NumIfSet("stop_loss", request.sl, digits);
   e.NumIfSet("take_profit", request.tp, digits);
   e.Int("broker_return_code", (long)result.retcode);
   e.Int("broker_error_code", last_error);
   e.Str("message", result.comment);
   e.Quote(request.symbol);
   e.Write();
  }

void ZfStrategyExitRequested(const string symbol, const long magic, const long position_id, const string why)
  {
   ZfEvent e("exit_requested");
   e.Str("symbol", symbol);
   e.Int("magic_number", magic);
   e.IntIfSet("position_id", position_id);
   e.TsSeconds("request_utc", TimeGMT());
   e.Str("message", why);
   e.Quote(symbol);
   e.Write();
  }

void ZfStrategyError(const string symbol, const long magic, const int error_code, const string what)
  {
   ZfEvent e("error");
   e.Str("symbol", symbol);
   e.Int("magic_number", magic);
   e.Int("raw_error_code", error_code);
   e.Str("message", what);
   e.Write();
  }
//+------------------------------------------------------------------+

//+------------------------------------------------------------------+
//|  BTC_V3_Stage4_Demo.mqh — R4 Stage 4 demo execution layer         |
//|                                                                   |
//|  TRANSMISSION IS NOT IMPLEMENTED IN THIS FILE.                     |
//|                                                                   |
//|  Every gate, validation, normalisation and reconciliation hook a   |
//|  demo order needs is here and is complete. The one thing missing   |
//|  is the call that would actually send it: Stage4Transmit() refuses  |
//|  unconditionally and returns false.                                 |
//|                                                                     |
//|  That is deliberate. A gated OrderSend is one edited condition away |
//|  from firing; an absent OrderSend is not. The static checker scans   |
//|  this file along with the EA and requires the forbidden-call list to |
//|  stay empty, so enabling Stage 4 cannot happen by accident — it      |
//|  takes a reviewed commit that adds the call at the marked site.      |
//+------------------------------------------------------------------+
#property strict

#define STAGE4_SCHEMA_VERSION 1
#define STAGE4_MAGIC 20260921

//--- Gate identifiers, reported verbatim so a refusal is never ambiguous.
#define G_MODE            "MODE_NOT_DEMO_EXECUTION"
#define G_ACCOUNT_DEMO    "ACCOUNT_NOT_DEMO"
#define G_SYMBOL          "SYMBOL_NOT_BTCUSDM"
#define G_BROKER          "BROKER_FINGERPRINT_MISMATCH"
#define G_STAGE3          "STAGE3_CERTIFICATE_ABSENT"
#define G_ACK             "OPERATOR_ACKNOWLEDGEMENT_ABSENT"
#define G_BUILD           "STALE_BUILD"
#define G_STAGE3_ISSUES   "STAGE3_ISSUES_UNRESOLVED"
#define G_TRANSMIT        "TRANSMISSION_NOT_IMPLEMENTED"

//--- Rejection classes for a broker reply. Retained so the handling policy is
//--- reviewable now rather than written in a hurry on the day it is needed.
#define R_OK              "ACCEPTED"
#define R_REQUOTE         "REQUOTE"
#define R_PRICE_OFF       "PRICE_OFF"
#define R_NO_MONEY        "INSUFFICIENT_MARGIN"
#define R_INVALID_VOLUME  "INVALID_VOLUME"
#define R_INVALID_STOPS   "INVALID_STOPS"
#define R_MARKET_CLOSED   "MARKET_CLOSED"
#define R_DISABLED        "TRADE_DISABLED"
#define R_TIMEOUT         "TIMEOUT"
#define R_OTHER           "OTHER"

struct Stage4Config
  {
   bool     enabled;              // InpMode == DEMO_EXECUTION
   string   expected_symbol;
   string   expected_broker;
   string   expected_server;
   string   stage3_certificate;   // file that must exist in Common\Files
   string   operator_ack;         // must equal ACK_PHRASE exactly
   string   twin_build;
   double   max_spread_points;
   double   risk_percent;
   double   max_leverage;
   int      deviation_points;
  };

#define STAGE4_ACK_PHRASE "I AUTHORISE EXNESS DEMO EXECUTION"

struct Stage4Gate
  {
   bool     passed;
   string   failed_code;
   string   detail;
  };

struct Stage4Order
  {
   bool     valid;
   int      direction;            // +1 long, -1 short
   double   volume;
   double   price;                // stop-entry trigger
   double   sl;
   double   tp;
   long     magic;
   string   client_tag;           // exactly-once key
   string   reject_code;
   string   reject_detail;
  };

//--- Forward declarations. These three are called above their definitions, and
//--- MQL5 resolves a call only against something already declared.
int    Stage4CertificateIssues(const string name);
bool   Stage4BuildMatchesCertificate(const string name,const string build);
string Stage4ClassifyRetcode(const int retcode);

//+------------------------------------------------------------------+
//| Gate evaluation                                                   |
//|                                                                   |
//| ALL of these must pass. They are evaluated in a fixed order and    |
//| the first failure is reported, so a refusal names one cause.       |
//+------------------------------------------------------------------+
Stage4Gate Stage4EvaluateGates(const Stage4Config &cfg)
  {
   Stage4Gate gate;
   gate.passed=false; gate.failed_code=""; gate.detail="";

   if(!cfg.enabled)
     { gate.failed_code=G_MODE; gate.detail="InpMode is not DEMO_EXECUTION"; return gate; }

   //--- A live or contest account must never reach transmission. ACCOUNT_DEMO
   //--- is the only accepted value; ACCOUNT_REAL is refused explicitly.
   long trade_mode = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(trade_mode!=ACCOUNT_TRADE_MODE_DEMO)
     {
      gate.failed_code=G_ACCOUNT_DEMO;
      gate.detail="ACCOUNT_TRADE_MODE is "+IntegerToString((int)trade_mode)
                  +" (demo is "+IntegerToString((int)ACCOUNT_TRADE_MODE_DEMO)+")";
      return gate;
     }
   if(_Symbol!=cfg.expected_symbol)
     { gate.failed_code=G_SYMBOL; gate.detail="symbol is "+_Symbol; return gate; }

   string company = AccountInfoString(ACCOUNT_COMPANY);
   string server  = AccountInfoString(ACCOUNT_SERVER);
   if(cfg.expected_broker!="" && company!=cfg.expected_broker)
     { gate.failed_code=G_BROKER; gate.detail="broker is "+company; return gate; }
   if(cfg.expected_server!="" && server!=cfg.expected_server)
     { gate.failed_code=G_BROKER; gate.detail="server is "+server; return gate; }

   //--- Stage 3 must have certified before Stage 4 may transmit. The operator
   //--- places the certificate file; its absence is a hard refusal.
   int common = FILE_COMMON;
   if(cfg.stage3_certificate=="" || !FileIsExist(cfg.stage3_certificate,common))
     {
      gate.failed_code=G_STAGE3;
      gate.detail="certificate "+cfg.stage3_certificate+" not found";
      return gate;
     }
   if(Stage4CertificateIssues(cfg.stage3_certificate)>0)
     {
      gate.failed_code=G_STAGE3_ISSUES;
      gate.detail="Stage 3 certificate reports unresolved issues";
      return gate;
     }
   if(cfg.operator_ack!=STAGE4_ACK_PHRASE)
     { gate.failed_code=G_ACK; gate.detail="acknowledgement phrase absent or wrong"; return gate; }
   if(!Stage4BuildMatchesCertificate(cfg.stage3_certificate,cfg.twin_build))
     { gate.failed_code=G_BUILD; gate.detail="running build differs from the certified one"; return gate; }

   gate.passed=true;
   return gate;
  }

//--- Reads "unresolved_issues" from the certificate. Absent or unparsable is
//--- treated as unresolved: an unreadable certificate certifies nothing.
int Stage4CertificateIssues(const string name)
  {
   int handle = FileOpen(name,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE) return 1;
   int issues = 1;
   bool seen = false;
   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      int comma = StringFind(line,",");
      if(comma<=0) continue;
      if(StringSubstr(line,0,comma)=="unresolved_issues")
        { issues=(int)StringToInteger(StringSubstr(line,comma+1)); seen=true; }
     }
   FileClose(handle);
   return seen ? issues : 1;
  }

bool Stage4BuildMatchesCertificate(const string name,const string build)
  {
   int handle = FileOpen(name,FILE_READ|FILE_TXT|FILE_ANSI|FILE_COMMON);
   if(handle==INVALID_HANDLE) return false;
   bool match = false;
   while(!FileIsEnding(handle))
     {
      string line = FileReadString(handle);
      int comma = StringFind(line,",");
      if(comma<=0) continue;
      if(StringSubstr(line,0,comma)=="twin_build")
         match = (StringSubstr(line,comma+1)==build);
     }
   FileClose(handle);
   return match;
  }

//+------------------------------------------------------------------+
//| Volume, price and stop normalisation                              |
//+------------------------------------------------------------------+
double Stage4NormalisePrice(const double price)
  {
   double tick = SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tick<=0.0) tick = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   if(tick<=0.0) return price;
   return NormalizeDouble(MathRound(price/tick)*tick,
                          (int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS));
  }

//--- Rounds DOWN to the volume step. Rounding up could exceed the risk budget,
//--- which is never an acceptable direction to err.
double Stage4NormaliseVolume(const double volume,string &reject)
  {
   reject="";
   double step = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(step<=0.0) { reject=R_INVALID_VOLUME; return 0.0; }
   double normalised = MathFloor(volume/step)*step;
   normalised = NormalizeDouble(normalised,2);
   if(normalised<vmin) { reject=R_INVALID_VOLUME; return 0.0; }
   if(normalised>vmax) normalised = vmax;
   return normalised;
  }

//--- Stops must clear the broker's minimum distance, or the order is rejected
//--- server-side. Checked before building the request, never after.
bool Stage4StopsAreValid(const int direction,const double price,const double sl,
                         const double tp,string &reject)
  {
   reject="";
   long level = SymbolInfoInteger(_Symbol,SYMBOL_TRADE_STOPS_LEVEL);
   double point = SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   double minimum = level*point;
   if(direction>0 && !(sl<price && tp>price)) { reject=R_INVALID_STOPS; return false; }
   if(direction<0 && !(sl>price && tp<price)) { reject=R_INVALID_STOPS; return false; }
   if(MathAbs(price-sl)<minimum || MathAbs(tp-price)<minimum)
     { reject=R_INVALID_STOPS; return false; }
   return true;
  }

//--- Refuses when the live spread is wider than the twin assumed. A demo fill
//--- taken at an abnormal spread is not evidence about the strategy.
bool Stage4SpreadAcceptable(const Stage4Config &cfg,string &reject)
  {
   reject="";
   double spread = (double)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD);
   if(cfg.max_spread_points>0.0 && spread>cfg.max_spread_points)
     { reject=R_PRICE_OFF; return false; }
   return true;
  }

//+------------------------------------------------------------------+
//| Request construction and pre-flight validation                    |
//|                                                                   |
//| OrderCheck() validates margin and request validity WITHOUT sending |
//| anything. It is the strongest pre-flight available that is not a   |
//| transmission.                                                      |
//+------------------------------------------------------------------+
Stage4Order Stage4BuildOrder(const Stage4Config &cfg,const int direction,
                             const double trigger,const double stop,
                             const double target,const double balance,
                             const string client_tag)
  {
   Stage4Order order;
   order.valid=false; order.direction=direction; order.magic=STAGE4_MAGIC;
   order.client_tag=client_tag; order.reject_code=""; order.reject_detail="";
   order.volume=0.0; order.price=0.0; order.sl=0.0; order.tp=0.0;

   if(!Stage4SpreadAcceptable(cfg,order.reject_code))
     { order.reject_detail="live spread exceeds the configured maximum"; return order; }

   order.price = Stage4NormalisePrice(trigger);
   order.sl    = Stage4NormalisePrice(stop);
   order.tp    = Stage4NormalisePrice(target);

   double distance = MathAbs(order.price-order.sl);
   if(distance<=0.0)
     { order.reject_code=R_INVALID_STOPS; order.reject_detail="zero stop distance"; return order; }

   double budget = balance*cfg.risk_percent/100.0;
   double raw = budget/distance;
   double cap = (balance*cfg.max_leverage)/order.price;
   if(raw>cap) raw = cap;
   order.volume = Stage4NormaliseVolume(raw,order.reject_code);
   if(order.reject_code!="")
     { order.reject_detail="volume "+DoubleToString(raw,4)+" fails broker limits"; return order; }

   if(!Stage4StopsAreValid(direction,order.price,order.sl,order.tp,order.reject_code))
     { order.reject_detail="stops inside the broker minimum distance"; return order; }

   //--- Margin pre-flight. OrderCheck does not transmit.
   MqlTradeRequest request;
   MqlTradeCheckResult check;
   ZeroMemory(request); ZeroMemory(check);
   request.action       = TRADE_ACTION_PENDING;
   request.symbol       = _Symbol;
   request.volume       = order.volume;
   request.price        = order.price;
   request.sl           = order.sl;
   request.tp           = order.tp;
   request.magic        = order.magic;
   request.deviation    = cfg.deviation_points;
   request.type         = (direction>0) ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
   request.type_filling = ORDER_FILLING_RETURN;
   request.type_time    = ORDER_TIME_GTC;
   request.comment      = order.client_tag;
   if(!OrderCheck(request,check))
     {
      order.reject_code = Stage4ClassifyRetcode((int)check.retcode);
      order.reject_detail = "OrderCheck retcode "+IntegerToString((int)check.retcode);
      return order;
     }
   order.valid = true;
   return order;
  }

//--- Broker reply classification. Written now so the policy is reviewable.
string Stage4ClassifyRetcode(const int retcode)
  {
   switch(retcode)
     {
      case TRADE_RETCODE_DONE:
      case TRADE_RETCODE_PLACED:           return R_OK;
      case TRADE_RETCODE_REQUOTE:
      case TRADE_RETCODE_PRICE_CHANGED:    return R_REQUOTE;
      case TRADE_RETCODE_PRICE_OFF:        return R_PRICE_OFF;
      case TRADE_RETCODE_NO_MONEY:         return R_NO_MONEY;
      case TRADE_RETCODE_INVALID_VOLUME:   return R_INVALID_VOLUME;
      case TRADE_RETCODE_INVALID_STOPS:    return R_INVALID_STOPS;
      case TRADE_RETCODE_MARKET_CLOSED:    return R_MARKET_CLOSED;
      case TRADE_RETCODE_TRADE_DISABLED:   return R_DISABLED;
      case TRADE_RETCODE_TIMEOUT:          return R_TIMEOUT;
      default:                             return R_OTHER;
     }
  }

//--- A requote or a price change may be retried; anything else may not. A
//--- rejection for volume, stops or margin means the request was wrong, and
//--- resending it unchanged would only repeat the error.
bool Stage4IsRetryable(const string reject_class)
  {
   return (reject_class==R_REQUOTE || reject_class==R_TIMEOUT);
  }

//+------------------------------------------------------------------+
//| Exactly-once ownership                                            |
//|                                                                   |
//| Every order carries STAGE4_MAGIC and a client tag derived from the |
//| signal bar, so the twin can recognise its own orders after a       |
//| restart and can never create a second order for the same signal.   |
//+------------------------------------------------------------------+
string Stage4ClientTag(const string setup_id,const datetime signal_time)
  {
   return "S4|"+setup_id+"|"+IntegerToString((long)signal_time);
  }

//--- True when the broker already holds an order or position with this tag.
//--- Checked before building a request, so a restart cannot duplicate.
bool Stage4AlreadySubmitted(const string client_tag)
  {
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)!=STAGE4_MAGIC) continue;
      if(OrderGetString(ORDER_COMMENT)==client_tag) return true;
     }
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=STAGE4_MAGIC) continue;
      if(PositionGetString(POSITION_COMMENT)==client_tag) return true;
     }
   return false;
  }

//--- Broker objects carrying our magic that the twin does not expect. Reported,
//--- never auto-closed: deciding what to do with one is an operator decision.
int Stage4OrphanCount(const string expected_tag)
  {
   int orphans = 0;
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket==0) continue;
      if(OrderGetInteger(ORDER_MAGIC)!=STAGE4_MAGIC) continue;
      if(OrderGetString(ORDER_COMMENT)!=expected_tag) orphans++;
     }
   for(int i=PositionsTotal()-1;i>=0;i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket==0) continue;
      if(PositionGetInteger(POSITION_MAGIC)!=STAGE4_MAGIC) continue;
      if(PositionGetString(POSITION_COMMENT)!=expected_tag) orphans++;
     }
   return orphans;
  }

//+------------------------------------------------------------------+
//| THE TRANSMISSION SITE                                              |
//|                                                                    |
//| This function is where a demo order would be sent, and it is the    |
//| only place that will ever be allowed to send one. It refuses         |
//| unconditionally and contains no transmission call.                   |
//|                                                                      |
//| Activating Stage 4 means adding, at the marked line, in a separate    |
//| reviewed commit carrying explicit authorisation:                      |
//|                                                                       |
//|     MqlTradeResult result;                                            |
//|     ZeroMemory(result);                                               |
//|     bool sent = <the MQL5 send call>(request,result);                 |
//|                                                                       |
//| and nothing else. Every gate, validation and ledger hook around it is  |
//| already written and tested.                                           |
//+------------------------------------------------------------------+
bool Stage4Transmit(const Stage4Config &cfg,const Stage4Order &order,
                    string &outcome,ulong &ticket)
  {
   ticket = 0;
   Stage4Gate gate = Stage4EvaluateGates(cfg);
   if(!gate.passed)
     {
      outcome = gate.failed_code;
      Print("STAGE 4 REFUSED (",gate.failed_code,"): ",gate.detail);
      return false;
     }
   if(!order.valid)
     {
      outcome = order.reject_code;
      Print("STAGE 4 REFUSED (",order.reject_code,"): ",order.reject_detail);
      return false;
     }
   if(Stage4AlreadySubmitted(order.client_tag))
     {
      outcome = "DUPLICATE_SUPPRESSED";
      Print("STAGE 4 REFUSED (DUPLICATE_SUPPRESSED): ",order.client_tag,
            " already exists at the broker");
      return false;
     }

   //=== AUTHORISED TRANSMISSION WOULD GO HERE — NOTHING IS SENT TODAY ======
   outcome = G_TRANSMIT;
   Print("STAGE 4 REFUSED (",G_TRANSMIT,"): every gate passed, but order "
         "transmission is not implemented. Enabling it is a separate "
         "authorised change.");
   return false;
   //=======================================================================
  }

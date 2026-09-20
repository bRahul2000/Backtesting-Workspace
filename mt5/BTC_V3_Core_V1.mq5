//+------------------------------------------------------------------+
//| BTC_V3_Core_V1.mq5                                               |
//|                                                                  |
//| AUDIT-ONLY digital twin of the frozen Python BTC_V3_CORE_V1.     |
//| Composition of:                                                  |
//|   A4 Pullback Long  (BTC_V3_A4_PULLBACK_LONG_FROZEN)             |
//|   T3 Breakout Short (BTC_V3_T3_BREAKOUT_SHORT_FROZEN)            |
//|                                                                  |
//| R4 Stage 1. This EA NEVER sends an order while AUDIT_ONLY is     |
//| selected, which is the default and is enforced by a hard guard   |
//| in SendOrderGuard(). DEMO_EXECUTION exists as a declared state   |
//| only; its transmission path is deliberately unimplemented and    |
//| hard-fails.                                                      |
//|                                                                  |
//| Ported from the authoritative Python sources:                    |
//|   strategies/btc_v3_l2_trend_pullback_long.py  (A4 base)         |
//|   strategies/btc_v3_a4_pullback_long.py        (A4 overlay)      |
//|   strategies/btc_v3_t3_breakout_short.py       (T3)              |
//|   strategies/btc_v3_core_v1.py                 (composition)     |
//|   strategies/pine_indicators.py                (EMA/RMA/ATR/...) |
//|   strategies/confirmed_h1_regime.py            (H1 context)      |
//|   engine/execution.py                          (order lifecycle) |
//|                                                                  |
//| CLOSED-CANDLE SEMANTICS                                          |
//|   Shift 0 is the forming M15 bar and is NEVER evaluated.         |
//|   Shift 1 is the just-closed M15 bar and is the only bar fed to  |
//|   the strategy. A new bar is detected when iTime(PERIOD_M15,0)   |
//|   changes; the bar then evaluated is shift 1.                    |
//|   The confirmed H1 bar is the previous complete four-bar hour.   |
//|   It becomes visible only once a bar belonging to the NEXT hour  |
//|   has closed, exactly as ConfirmedH1Regime does, and a bucket    |
//|   missing any of its :00/:15/:30/:45 bars is discarded, not      |
//|   partially aggregated.                                          |
//+------------------------------------------------------------------+
#property copyright "Universal Backtester V1 — research"
#property version   "1.00"
#property strict
#property description "BTC V3 Core V1 audit-only digital twin. Sends no orders."

enum ExecutionMode
  {
   AUDIT_ONLY      = 0,  // Audit only: evaluate and log, never trade
   DEMO_EXECUTION  = 1   // Declared only; transmission NOT implemented
  };

input ExecutionMode InpMode            = AUDIT_ONLY;
input string        InpSymbolExpected  = "BTCUSDm";
input string        InpLogFile         = "btc_core_v1_audit.csv";
input bool          InpUseCommonFiles  = true;
input double        InpStartBalance    = 10000.0;
input double        InpRiskPercent     = 0.25;
input double        InpRewardMultiple  = 3.0;
input double        InpMaxLeverage     = 1.0;
input bool          InpRequireUtcServer = true;

//--- Frozen fingerprints, stamped into every log row so a log can never be
//--- silently matched against a different Python build.
#define CORE_FINGERPRINT "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"
#define A4_SETUP_ID "BTC_V3_A4_PULLBACK_LONG_FROZEN"
#define T3_SETUP_ID "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
#define STEP_SECONDS 900

//--- A4 / V3-L2 frozen parameters -----------------------------------------
#define A4_H1_FAST 50
#define A4_H1_SLOW 200
#define A4_H1_ATR 14
#define A4_H1_SLOPE_LOOKBACK 4
#define A4_H1_MIN_SEPARATION_ATR 1.00
#define A4_EMA_FAST 20
#define A4_EMA_SLOW 50
#define A4_ATR_LENGTH 14
#define A4_RSI_LENGTH 14
#define A4_DI_LENGTH 14
#define A4_ADX_SMOOTHING 14
#define A4_MIN_ADX 18.0
#define A4_STRUCTURE_LOOKBACK 5
#define A4_MAX_PULLBACK_DEPTH_ATR 1.00
#define A4_CONFIRM_MIN_BODY 0.70
#define A4_CONFIRM_MAX_BODY 0.90
#define A4_CONFIRM_RSI_MIN 48.0
#define A4_CONFIRM_RSI_MAX 70.0
#define A4_MIN_NORM_H1_SLOPE 0.15
#define A4_MATERIAL_EMA50_ATR 0.20
#define A4_ENTRY_BUFFER_ATR 0.05
#define A4_STOP_BUFFER_ATR 0.20
#define A4_MIN_STOP_ATR 0.50
#define A4_MAX_STOP_ATR 3.00
#define A4_PENDING_BARS 2

//--- T3 frozen parameters --------------------------------------------------
#define T3_MIN_H1_SEPARATION_ATR 1.00
#define T3_MIN_ADX 18.0
#define T3_STRUCTURE_LOOKBACK 5
#define T3_MIN_BODY 0.70
#define T3_MIN_RANGE_ATR 0.60
#define T3_MAX_RANGE_ATR 2.00
#define T3_SHORT_RSI_MIN 24.0
#define T3_SHORT_RSI_MAX 50.0
#define T3_MAX_EXTENSION_ATR 2.50
#define T3_STOP_LOOKBACK 2
#define T3_RANGE_SWEEP_LOOKBACK 8
#define T3_ENTRY_BUFFER_ATR 0.05
#define T3_STOP_BUFFER_ATR 0.20
#define T3_MIN_STOP_ATR 0.50
#define T3_MAX_STOP_ATR 3.00
#define T3_PENDING_BARS 2

//--- Shared session / day limits (identical in both components)
#define SESSION_START_HOUR 0
#define SESSION_END_HOUR 22
#define MAX_TRADES_PER_DAY 3

//+------------------------------------------------------------------+
//| Pine-equivalent streaming indicators                             |
//|                                                                  |
//| These deliberately do NOT use iMA/iATR/iRSI/iADX. MT5's built-in |
//| handles seed differently (SMA seeding for EMA, Wilder seeding    |
//| for ATR) and would not reproduce strategies/pine_indicators.py.  |
//+------------------------------------------------------------------+
struct PineEma
  {
   int    length;
   double value;
   bool   ready;
  };

void EmaInit(PineEma &ema,const int length)
  { ema.length=length; ema.value=0.0; ema.ready=false; }

//--- Python: value = price if value is None else value + 2/(n+1)*(price-value)
double EmaUpdate(PineEma &ema,const double price)
  {
   if(!ema.ready) { ema.value=price; ema.ready=true; }
   else           ema.value += 2.0/(ema.length+1.0)*(price-ema.value);
   return ema.value;
  }

struct PineRma
  {
   int    length;
   double value;
   bool   ready;
   double seed_sum;
   int    seed_count;
  };

void RmaInit(PineRma &rma,const int length)
  { rma.length=length; rma.value=0.0; rma.ready=false; rma.seed_sum=0.0; rma.seed_count=0; }

//--- Python: seed with the simple mean of the first `length` observations,
//--- then value += (obs - value)/length.
bool RmaUpdate(PineRma &rma,const double observation,double &out)
  {
   if(!rma.ready)
     {
      rma.seed_sum += observation;
      rma.seed_count++;
      if(rma.seed_count==rma.length)
        { rma.value=rma.seed_sum/rma.length; rma.ready=true; }
     }
   else
      rma.value += (observation-rma.value)/rma.length;
   out=rma.value;
   return rma.ready;
  }

struct PineAtr
  {
   PineRma average;
   double  previous_close;
   bool    has_previous;
  };

void AtrInit(PineAtr &atr,const int length)
  { RmaInit(atr.average,length); atr.previous_close=0.0; atr.has_previous=false; }

bool AtrUpdate(PineAtr &atr,const double high,const double low,const double close,double &out)
  {
   double tr;
   if(!atr.has_previous)
      tr = high-low;
   else
      tr = MathMax(high-low,MathMax(MathAbs(high-atr.previous_close),
                                    MathAbs(low-atr.previous_close)));
   atr.previous_close=close;
   atr.has_previous=true;
   return RmaUpdate(atr.average,tr,out);
  }

struct PineRsi
  {
   PineRma gain;
   PineRma loss;
   double  previous_close;
   bool    has_previous;
  };

void RsiInit(PineRsi &rsi,const int length)
  { RmaInit(rsi.gain,length); RmaInit(rsi.loss,length); rsi.previous_close=0.0; rsi.has_previous=false; }

//--- Python returns None on the first close and while the RMAs are seeding.
bool RsiUpdate(PineRsi &rsi,const double close,double &out)
  {
   if(!rsi.has_previous)
     { rsi.previous_close=close; rsi.has_previous=true; return false; }
   double change = close-rsi.previous_close;
   rsi.previous_close = close;
   double gain_value=0.0, loss_value=0.0;
   bool gain_ready = RmaUpdate(rsi.gain,MathMax(change,0.0),gain_value);
   bool loss_ready = RmaUpdate(rsi.loss,MathMax(-change,0.0),loss_value);
   if(!gain_ready || !loss_ready)
      return false;
   if(loss_value==0.0)
     { out = (gain_value>0.0) ? 100.0 : 50.0; return true; }
   out = 100.0 - 100.0/(1.0 + gain_value/loss_value);
   return true;
  }

struct PineDmi
  {
   PineRma tr;
   PineRma plus;
   PineRma minus;
   PineRma adx;
   double  previous_high;
   double  previous_low;
   double  previous_close;
   bool    has_previous;
  };

void DmiInit(PineDmi &dmi,const int di_length,const int adx_smoothing)
  {
   RmaInit(dmi.tr,di_length); RmaInit(dmi.plus,di_length);
   RmaInit(dmi.minus,di_length); RmaInit(dmi.adx,adx_smoothing);
   dmi.previous_high=0.0; dmi.previous_low=0.0; dmi.previous_close=0.0;
   dmi.has_previous=false;
  }

bool DmiUpdate(PineDmi &dmi,const double high,const double low,const double close,
               double &plus_di,double &minus_di,double &adx_out)
  {
   if(!dmi.has_previous)
     {
      //--- Pine's ta.tr includes the first bar's high-low.
      double ignored;
      RmaUpdate(dmi.tr,high-low,ignored);
      dmi.previous_high=high; dmi.previous_low=low; dmi.previous_close=close;
      dmi.has_previous=true;
      return false;
     }
   double up   = high - dmi.previous_high;
   double down = dmi.previous_low - low;
   double plus  = (up>down   && up>0.0)   ? up   : 0.0;
   double minus = (down>up   && down>0.0) ? down : 0.0;
   double tr = MathMax(high-low,MathMax(MathAbs(high-dmi.previous_close),
                                        MathAbs(low-dmi.previous_close)));
   dmi.previous_high=high; dmi.previous_low=low; dmi.previous_close=close;

   double tr_avg=0.0, plus_avg=0.0, minus_avg=0.0;
   bool a = RmaUpdate(dmi.tr,tr,tr_avg);
   bool b = RmaUpdate(dmi.plus,plus,plus_avg);
   bool c = RmaUpdate(dmi.minus,minus,minus_avg);
   if(!a || !b || !c)
      return false;
   double divisor = (tr_avg!=0.0) ? tr_avg : 1.0;
   plus_di  = 100.0*plus_avg/divisor;
   minus_di = 100.0*minus_avg/divisor;
   double total = plus_di+minus_di;
   double dx = 100.0*MathAbs(plus_di-minus_di)/((total!=0.0)?total:1.0);
   return RmaUpdate(dmi.adx,dx,adx_out);
  }

//+------------------------------------------------------------------+
//| Confirmed H1 regime — port of strategies/confirmed_h1_regime.py  |
//+------------------------------------------------------------------+
struct H1Regime
  {
   PineEma  fast;
   PineEma  slow;
   PineAtr  atr;
   int      slope_lookback;
   double   slow_history[8];      // ring of the last slope_lookback+1 slow values
   int      slow_count;
   datetime bucket;
   bool     has_bucket;
   datetime bucket_times[4];
   double   bucket_open, bucket_high, bucket_low, bucket_close;
   int      bucket_bars;
   //--- confirmed values
   bool     confirmed;
   datetime confirmed_hour;
   double   confirmed_open, confirmed_high, confirmed_low, confirmed_close;
   double   confirmed_fast, confirmed_slow, confirmed_past, confirmed_atr;
   bool     has_past;
   bool     has_atr;
  };

void H1Init(H1Regime &h1)
  {
   EmaInit(h1.fast,A4_H1_FAST);
   EmaInit(h1.slow,A4_H1_SLOW);
   AtrInit(h1.atr,A4_H1_ATR);
   h1.slope_lookback=A4_H1_SLOPE_LOOKBACK;
   ArrayInitialize(h1.slow_history,0.0);
   h1.slow_count=0;
   h1.bucket=0; h1.has_bucket=false; h1.bucket_bars=0;
   h1.bucket_open=h1.bucket_high=h1.bucket_low=h1.bucket_close=0.0;
   h1.confirmed=false; h1.confirmed_hour=0;
   h1.confirmed_open=h1.confirmed_high=h1.confirmed_low=h1.confirmed_close=0.0;
   h1.confirmed_fast=h1.confirmed_slow=h1.confirmed_past=h1.confirmed_atr=0.0;
   h1.has_past=false; h1.has_atr=false;
  }

//--- A bucket completes only with exactly four bars at :00/:15/:30/:45.
void H1CompleteBucket(H1Regime &h1)
  {
   if(h1.bucket_bars!=4)
      return;
   for(int i=0;i<4;i++)
      if(h1.bucket_times[i]!=h1.bucket+i*STEP_SECONDS)
         return;
   double fast = EmaUpdate(h1.fast,h1.bucket_close);
   double slow = EmaUpdate(h1.slow,h1.bucket_close);
   double atr_value=0.0;
   bool atr_ready = AtrUpdate(h1.atr,h1.bucket_high,h1.bucket_low,h1.bucket_close,atr_value);

   //--- deque(maxlen=slope_lookback+1) of slow EMA values
   int capacity = h1.slope_lookback+1;
   if(h1.slow_count<capacity)
      h1.slow_history[h1.slow_count++]=slow;
   else
     {
      for(int i=0;i<capacity-1;i++)
         h1.slow_history[i]=h1.slow_history[i+1];
      h1.slow_history[capacity-1]=slow;
     }
   h1.has_past = (h1.slow_count==capacity);
   h1.confirmed_past = h1.has_past ? h1.slow_history[0] : 0.0;

   h1.confirmed=true;
   h1.confirmed_hour=h1.bucket;
   h1.confirmed_open=h1.bucket_open;
   h1.confirmed_high=h1.bucket_high;
   h1.confirmed_low=h1.bucket_low;
   h1.confirmed_close=h1.bucket_close;
   h1.confirmed_fast=fast;
   h1.confirmed_slow=slow;
   h1.confirmed_atr=atr_value;
   h1.has_atr=atr_ready;
  }

void H1Update(H1Regime &h1,const datetime bar_time,const double open,const double high,
              const double low,const double close)
  {
   datetime hour = bar_time - (bar_time % 3600);
   if(h1.has_bucket && hour!=h1.bucket)
     {
      H1CompleteBucket(h1);
      h1.bucket_bars=0;
     }
   h1.bucket=hour;
   h1.has_bucket=true;
   if(h1.bucket_bars==0)
     { h1.bucket_open=open; h1.bucket_high=high; h1.bucket_low=low; }
   else
     { h1.bucket_high=MathMax(h1.bucket_high,high); h1.bucket_low=MathMin(h1.bucket_low,low); }
   h1.bucket_close=close;
   if(h1.bucket_bars<4)
      h1.bucket_times[h1.bucket_bars]=bar_time;
   h1.bucket_bars++;
  }

bool H1Slope(const H1Regime &h1,double &slope)
  {
   if(!h1.confirmed || !h1.has_past)
      return false;
   slope = h1.confirmed_slow - h1.confirmed_past;
   return true;
  }

bool H1SeparationAtr(const H1Regime &h1,double &separation)
  {
   if(!h1.confirmed || !h1.has_atr || h1.confirmed_atr<=0.0)
      return false;
   separation = MathAbs(h1.confirmed_fast-h1.confirmed_slow)/h1.confirmed_atr;
   return true;
  }

//--- Port of h1_bullish() in btc_v3_l2_trend_pullback_long.py
bool H1Bullish(const H1Regime &h1)
  {
   double slope=0.0, separation=0.0;
   if(!h1.confirmed) return false;
   if(!H1Slope(h1,slope)) return false;
   if(!H1SeparationAtr(h1,separation)) return false;
   return (h1.confirmed_fast>h1.confirmed_slow
           && h1.confirmed_close>h1.confirmed_slow
           && slope>0.0
           && separation>=A4_H1_MIN_SEPARATION_ATR);
  }

//+------------------------------------------------------------------+
//| Rolling closed-bar buffer (mirrors the strategies' deques)        |
//+------------------------------------------------------------------+
#define HISTORY 16
struct BarBuffer
  {
   datetime time[HISTORY];
   double   open[HISTORY];
   double   high[HISTORY];
   double   low[HISTORY];
   double   close[HISTORY];
   int      count;
  };

void BufferReset(BarBuffer &buffer) { buffer.count=0; }

void BufferPush(BarBuffer &buffer,const datetime t,const double o,const double h,
                const double l,const double c)
  {
   if(buffer.count<HISTORY)
     {
      buffer.time[buffer.count]=t; buffer.open[buffer.count]=o;
      buffer.high[buffer.count]=h; buffer.low[buffer.count]=l;
      buffer.close[buffer.count]=c; buffer.count++;
      return;
     }
   for(int i=0;i<HISTORY-1;i++)
     {
      buffer.time[i]=buffer.time[i+1]; buffer.open[i]=buffer.open[i+1];
      buffer.high[i]=buffer.high[i+1]; buffer.low[i]=buffer.low[i+1];
      buffer.close[i]=buffer.close[i+1];
     }
   buffer.time[HISTORY-1]=t; buffer.open[HISTORY-1]=o; buffer.high[HISTORY-1]=h;
   buffer.low[HISTORY-1]=l; buffer.close[HISTORY-1]=c;
  }

//--- Highest high over the last `window` buffered bars; false if too few.
bool BufferHighest(const BarBuffer &buffer,const int window,double &out)
  {
   if(buffer.count<window) return false;
   double best=buffer.high[buffer.count-1];
   for(int i=buffer.count-window;i<buffer.count;i++)
      best=MathMax(best,buffer.high[i]);
   out=best; return true;
  }

bool BufferLowest(const BarBuffer &buffer,const int window,double &out)
  {
   if(buffer.count<window) return false;
   double best=buffer.low[buffer.count-1];
   for(int i=buffer.count-window;i<buffer.count;i++)
      best=MathMin(best,buffer.low[i]);
   out=best; return true;
  }

//+------------------------------------------------------------------+
//| Strategy and audit-order state                                    |
//+------------------------------------------------------------------+
struct A4State
  {
   bool     pullback_active;
   datetime pullback_start_time;
   double   pullback_low;
   bool     has_pullback_low;
   double   pullback_max_depth_atr;
   int      pullback_bars;
   string   pullback_touch;
   double   structure_level;
   bool     has_structure;
   int      trades_today;
  };

struct T3State { int trades_today; };

//--- Internal audit order model, mirroring engine/execution.py.
struct AuditOrder
  {
   bool     active;
   int      direction;          // +1 long, -1 short
   string   setup_id;
   datetime signal_time;
   datetime created_time;
   double   trigger;
   double   stop;
   datetime expiry_time;
   int      created_bar_index;
   int      expiry_bar_index;
   double   quantity;
   double   planned_risk;
  };

struct AuditPosition
  {
   bool     active;
   int      direction;
   string   setup_id;
   datetime signal_time;
   datetime entry_time;
   double   entry;
   double   stop;
   double   target;
   double   quantity;
   double   planned_risk;
   bool     gap_through_trigger;
   bool     entered_intrabar;
  };

//--- globals
H1Regime      g_h1;
PineEma       g_ema20, g_ema50;
PineAtr       g_atr;
PineRsi       g_rsi;
PineDmi       g_dmi;
BarBuffer     g_prior;
A4State       g_a4;
T3State       g_t3;
AuditOrder    g_order;
AuditPosition g_position;
double        g_balance;
int           g_bar_index;
datetime      g_last_bar_time;
datetime      g_last_processed;
int           g_day_key;
int           g_file;
bool          g_halted;
string        g_halt_reason;
int           g_digits;
double        g_point;

void ResetIndicators()
  {
   H1Init(g_h1);
   EmaInit(g_ema20,A4_EMA_FAST);
   EmaInit(g_ema50,A4_EMA_SLOW);
   AtrInit(g_atr,A4_ATR_LENGTH);
   RsiInit(g_rsi,A4_RSI_LENGTH);
   DmiInit(g_dmi,A4_DI_LENGTH,A4_ADX_SMOOTHING);
   BufferReset(g_prior);
  }

void ResetPullback(const bool clear_structure)
  {
   g_a4.pullback_active=false;
   g_a4.pullback_start_time=0;
   g_a4.pullback_low=0.0;
   g_a4.has_pullback_low=false;
   g_a4.pullback_max_depth_atr=0.0;
   g_a4.pullback_bars=0;
   g_a4.pullback_touch="";
   if(clear_structure)
     { g_a4.structure_level=0.0; g_a4.has_structure=false; }
  }

void ResetAll()
  {
   ResetIndicators();
   ResetPullback(true);
   g_a4.trades_today=0;
   g_t3.trades_today=0;
   g_order.active=false;
   g_position.active=false;
   g_balance=InpStartBalance;
   g_bar_index=0;
   g_day_key=-1;
  }

//+------------------------------------------------------------------+
//| HARD EXECUTION GUARD                                              |
//|                                                                   |
//| Every hypothetical order path must call this first. In AUDIT_ONLY |
//| it refuses unconditionally, so no code path can reach OrderSend   |
//| by accident. DEMO_EXECUTION is declared but deliberately          |
//| unimplemented and also refuses: enabling it is a separate         |
//| authorized stage.                                                 |
//+------------------------------------------------------------------+
bool SendOrderGuard(const string context)
  {
   if(InpMode==AUDIT_ONLY)
     {
      Print("BLOCKED (AUDIT_ONLY): order transmission refused for ",context);
      return false;
     }
   Print("BLOCKED: DEMO_EXECUTION transmission is not implemented in R4 Stage 1 (",context,").");
   return false;
  }

//+------------------------------------------------------------------+
//| Position sizing — port of engine/execution.py open_position       |
//| with commission_percent = 0 and slippage_percent = 0, so the      |
//| estimated stop loss per unit reduces to |entry - stop|.           |
//+------------------------------------------------------------------+
double AuditQuantity(const double entry,const double stop,double &planned_risk)
  {
   double distance = MathAbs(entry-stop);
   if(distance<=0.0) { planned_risk=0.0; return 0.0; }
   double budget = g_balance*InpRiskPercent/100.0;
   double quantity = budget/distance;
   double max_quantity = (g_balance*InpMaxLeverage)/entry;
   if(quantity>max_quantity)
      quantity = max_quantity;
   planned_risk = quantity*distance;
   return quantity;
  }

//+------------------------------------------------------------------+
//| Logging                                                           |
//+------------------------------------------------------------------+
string Csv(const string value) { return value; }

string Num(const double value,const bool present)
  { return present ? DoubleToString(value,10) : ""; }

string Flag(const bool value,const bool present)
  { return present ? (value ? "1" : "0") : ""; }

string IsoUtc(const datetime value,const bool present)
  {
   if(!present || value==0) return "";
   MqlDateTime parts;
   TimeToStruct(value,parts);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02dZ",parts.year,parts.mon,parts.day,
                       parts.hour,parts.min,parts.sec);
  }

bool OpenLog()
  {
   uint flags = FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI;
   if(InpUseCommonFiles) flags |= FILE_COMMON;
   g_file = FileOpen(InpLogFile,flags,',');
   if(g_file==INVALID_HANDLE)
     { Print("Cannot open audit log ",InpLogFile,": ",GetLastError()); return false; }
   if(FileSize(g_file)==0)
     {
      FileWrite(g_file,
        "bar_time_utc","symbol","open","high","low","close","tick_volume",
        "spread_points","spread_price",
        "h1_time_utc","h1_open","h1_high","h1_low","h1_close",
        "h1_ema50","h1_ema200","h1_ema200_past","h1_atr","h1_slope","h1_slope_atr",
        "h1_separation_atr",
        "ema20","ema50","atr","rsi","adx","plus_di","minus_di","body_percent",
        "a4_context_pass","a4_signal_pass","a4_reject_code","a4_in_session",
        "a4_trades_today","a4_material_below_ema50","a4_pullback_active",
        "a4_pullback_low","a4_pullback_depth_atr","a4_pullback_bars",
        "a4_pullback_touch","a4_structure_level","a4_prior_high","a4_trigger",
        "a4_stop","a4_stop_atr",
        "t3_regime","t3_context_pass","t3_signal_pass","t3_reject_code",
        "t3_prev_high","t3_prev_low","t3_stop_high","t3_stop_low","t3_range_atr",
        "t3_extension_atr","t3_trigger","t3_stop","t3_stop_atr",
        "signal_side","signal_setup_id","signal_time_utc",
        "pending_status","pending_trigger","pending_stop","pending_expiry_utc",
        "entry_time_utc","entry_price","entry_stop","entry_target",
        "exit_time_utc","exit_price","exit_reason","realized_r",
        "commission_status","swap_status","realized_cost_status");
     }
   FileSeek(g_file,0,SEEK_END);
   return true;
  }

double BodyPercent(const double open,const double high,const double low,const double close)
  {
   double width = high-low;
   return (width>0.0) ? MathAbs(close-open)/width : 0.0;
  }

//+------------------------------------------------------------------+
//| Per-bar evaluation result                                         |
//+------------------------------------------------------------------+
struct BarView
  {
   datetime time;
   double   open, high, low, close;
   long     tick_volume;
   int      spread_points;
   double   ema20, ema50, atr, rsi, adx, plus_di, minus_di;
   bool     has_atr, has_rsi, has_adx;
   bool     in_session;
  };

struct Decision
  {
   bool   context_pass;
   bool   signal_pass;
   string reject_code;
   int    direction;
   double trigger;
   double stop;
   double stop_atr;
   bool   has_levels;
  };

void DecisionInit(Decision &decision)
  {
   decision.context_pass=false; decision.signal_pass=false; decision.reject_code="";
   decision.direction=0; decision.trigger=0.0; decision.stop=0.0;
   decision.stop_atr=0.0; decision.has_levels=false;
  }

//+------------------------------------------------------------------+
//| A4 — port of BtcV3A4PullbackLongFrozen over V3-L2.                |
//| Called with the just-closed bar and the prior-bar buffer taken    |
//| BEFORE this bar was pushed, exactly as the Python deque is read.  |
//+------------------------------------------------------------------+
void EvaluateA4(const BarView &bar,const double prior_high,const bool has_prior_high,
                const double previous_high,const bool has_previous,
                const bool blocked,const string blocked_code,Decision &decision)
  {
   DecisionInit(decision);
   if(blocked) { decision.reject_code=blocked_code; return; }
   if(!bar.in_session) { decision.reject_code="A4_OUT_OF_SESSION"; return; }
   if(g_a4.trades_today>=MAX_TRADES_PER_DAY) { decision.reject_code="A4_MAX_TRADES_PER_DAY"; return; }
   if(!bar.has_atr || bar.atr<=0.0 || !bar.has_rsi || !bar.has_adx)
     { decision.reject_code="A4_WARMUP"; return; }

   bool bullish = H1Bullish(g_h1);
   if(!bullish)
     {
      if(g_a4.pullback_active) ResetPullback(true); else ResetPullback(true);
      decision.reject_code="A4_H1_NOT_BULLISH"; return;
     }
   if(!(bar.ema20>bar.ema50))
     { ResetPullback(false); decision.reject_code="A4_EMA_STACK_FAIL"; return; }
   if(bar.adx<A4_MIN_ADX)
     { ResetPullback(false); decision.reject_code="A4_ADX_FAIL"; return; }
   double slope=0.0;
   if(!H1Slope(g_h1,slope) || !g_h1.has_atr || g_h1.confirmed_atr<=0.0
      || slope/g_h1.confirmed_atr < A4_MIN_NORM_H1_SLOPE)
     { ResetPullback(false); decision.reject_code="A4_H1_SLOPE_NORM_FAIL"; return; }

   decision.context_pass=true;
   if(bar.close < bar.ema50 - A4_MATERIAL_EMA50_ATR*bar.atr)
     { ResetPullback(false); decision.reject_code="A4_MATERIAL_BELOW_EMA50"; return; }

   double depth = MathMax(0.0,(bar.ema20-bar.low)/bar.atr);
   if(g_a4.pullback_active && depth>A4_MAX_PULLBACK_DEPTH_ATR)
     {
      ResetPullback(false);
      if(has_prior_high && bar.close>prior_high)
        { g_a4.structure_level=prior_high; g_a4.has_structure=true; }
      decision.reject_code="A4_PULLBACK_TOO_DEEP"; return;
     }

   if(g_a4.pullback_active)
     {
      g_a4.pullback_low = g_a4.has_pullback_low ? MathMin(g_a4.pullback_low,bar.low) : bar.low;
      g_a4.has_pullback_low=true;
      g_a4.pullback_max_depth_atr = MathMax(g_a4.pullback_max_depth_atr,depth);
      g_a4.pullback_bars++;
      if(g_a4.pullback_start_time!=0 && bar.time>g_a4.pullback_start_time)
        {
         //--- confirmation_passes(), with the A4 body cap applied last.
         string code="A4_CONFIRM_OK";
         double body = BodyPercent(bar.open,bar.high,bar.low,bar.close);
         if(!has_previous)                          code="A4_WARMUP";
         else if(!(bar.close>bar.open))             code="A4_CONFIRM_NOT_BULLISH";
         else if(body<A4_CONFIRM_MIN_BODY)          code="A4_BODY_TOO_SMALL";
         else if(!(bar.close>bar.ema20))            code="A4_CLOSE_BELOW_EMA20";
         else if(!(bar.close>previous_high))        code="A4_NO_BREAK_PREV_HIGH";
         else if(bar.rsi<A4_CONFIRM_RSI_MIN || bar.rsi>A4_CONFIRM_RSI_MAX)
                                                    code="A4_RSI_OUT_OF_BAND";
         else if(body>A4_CONFIRM_MAX_BODY)          code="A4_BODY_TOO_LARGE";
         if(code=="A4_CONFIRM_OK")
           {
            double trigger = bar.high + A4_ENTRY_BUFFER_ATR*bar.atr;
            double stop    = g_a4.pullback_low - A4_STOP_BUFFER_ATR*bar.atr;
            double risk_atr = (trigger-stop)/bar.atr;
            decision.trigger=trigger; decision.stop=stop;
            decision.stop_atr=risk_atr; decision.has_levels=true;
            if(risk_atr<A4_MIN_STOP_ATR)      decision.reject_code="A4_STOP_TOO_TIGHT";
            else if(risk_atr>A4_MAX_STOP_ATR) decision.reject_code="A4_STOP_TOO_WIDE";
            else
              {
               decision.signal_pass=true; decision.direction=1;
               decision.reject_code="A4_SIGNAL_OK";
               ResetPullback(false);
               return;
              }
           }
         else
            decision.reject_code=code;
        }
      else
         decision.reject_code="A4_SAME_BAR_AS_PULLBACK_START";
     }

   //--- Structure break: an impulse bar, never the pullback itself.
   if(has_prior_high && bar.close>prior_high)
     {
      g_a4.structure_level=prior_high; g_a4.has_structure=true;
      if(decision.reject_code=="") decision.reject_code="A4_STRUCTURE_BREAK_BAR";
      return;
     }

   if(!g_a4.pullback_active)
     {
      string touches="";
      if(bar.low<=bar.ema20) touches="EMA20";
      if(bar.low<=bar.ema50) touches = (touches=="") ? "EMA50" : touches+"+EMA50";
      if(g_a4.has_structure && bar.low<=g_a4.structure_level)
         touches = (touches=="") ? "STRUCTURE" : touches+"+STRUCTURE";
      if(touches!="" && depth<=A4_MAX_PULLBACK_DEPTH_ATR)
        {
         g_a4.pullback_active=true;
         g_a4.pullback_start_time=bar.time;
         g_a4.pullback_low=bar.low;
         g_a4.has_pullback_low=true;
         g_a4.pullback_max_depth_atr=depth;
         g_a4.pullback_bars=1;
         g_a4.pullback_touch=touches;
        }
      if(decision.reject_code=="") decision.reject_code="A4_NO_PULLBACK";
     }
   if(decision.reject_code=="") decision.reject_code="A4_NO_PULLBACK";
  }

//+------------------------------------------------------------------+
//| T3 — port of BtcV3T3BreakoutShortFrozen.                          |
//| longs_enabled and range_enabled are False in the frozen           |
//| parameters, so only the trend-short branch can ever fire.         |
//+------------------------------------------------------------------+
void EvaluateT3(const BarView &bar,const double trend_low,const bool has_trend_low,
                const double stop_high,const bool blocked,const string blocked_code,
                string &regime_label,Decision &decision)
  {
   DecisionInit(decision);
   regime_label="";
   if(blocked) { decision.reject_code=blocked_code; return; }
   if(!bar.in_session) { decision.reject_code="T3_OUT_OF_SESSION"; return; }
   if(g_t3.trades_today>=MAX_TRADES_PER_DAY) { decision.reject_code="T3_MAX_TRADES_PER_DAY"; return; }

   double separation=0.0, slope=0.0;
   bool have_separation = H1SeparationAtr(g_h1,separation);
   bool have_slope = H1Slope(g_h1,slope);
   if(!have_separation || !have_slope || !bar.has_adx)
     { regime_label="CHOP"; decision.reject_code="T3_WARMUP"; return; }

   bool bullish = (g_h1.confirmed_fast>g_h1.confirmed_slow && slope>0.0 && bar.ema20>bar.ema50);
   bool bearish = (g_h1.confirmed_fast<g_h1.confirmed_slow && slope<0.0 && bar.ema20<bar.ema50);
   int direction=0;
   if(separation>=T3_MIN_H1_SEPARATION_ATR && bar.adx>=T3_MIN_ADX)
     {
      if(bullish)      { regime_label="TREND"; direction=1; }
      else if(bearish) { regime_label="TREND"; direction=-1; }
      else             regime_label="CHOP";
     }
   else
      regime_label="CHOP";

   if(!bar.has_atr || bar.atr<=0.0 || !bar.has_rsi)
     { decision.reject_code="T3_WARMUP"; return; }
   if(regime_label!="TREND")
     { decision.reject_code="T3_REGIME_NOT_TREND"; return; }
   if(direction==1)
     { decision.context_pass=true; decision.reject_code="T3_DIRECTION_LONG_DISABLED"; return; }

   decision.context_pass=true;
   if(!has_trend_low) { decision.reject_code="T3_WARMUP"; return; }
   if(!(bar.close<trend_low)) { decision.reject_code="T3_NO_BREAK_PREV_LOW"; return; }
   if(!(bar.close<bar.open)) { decision.reject_code="T3_NOT_BEARISH_CANDLE"; return; }
   if(BodyPercent(bar.open,bar.high,bar.low,bar.close)<T3_MIN_BODY)
     { decision.reject_code="T3_BODY_FAIL"; return; }
   double range_atr = (bar.high-bar.low)/bar.atr;
   if(range_atr<T3_MIN_RANGE_ATR) { decision.reject_code="T3_RANGE_TOO_SMALL"; return; }
   if(range_atr>T3_MAX_RANGE_ATR) { decision.reject_code="T3_RANGE_TOO_LARGE"; return; }
   if(bar.rsi<T3_SHORT_RSI_MIN || bar.rsi>T3_SHORT_RSI_MAX)
     { decision.reject_code="T3_RSI_OUT_OF_BAND"; return; }
   if(MathAbs(bar.close-bar.ema20)/bar.atr > T3_MAX_EXTENSION_ATR)
     { decision.reject_code="T3_EXTENSION_FAIL"; return; }

   double trigger = bar.low - T3_ENTRY_BUFFER_ATR*bar.atr;
   double stop    = stop_high + T3_STOP_BUFFER_ATR*bar.atr;
   double risk_atr = (stop-trigger)/bar.atr;
   decision.trigger=trigger; decision.stop=stop;
   decision.stop_atr=risk_atr; decision.has_levels=true;
   if(risk_atr<T3_MIN_STOP_ATR) { decision.reject_code="T3_STOP_TOO_TIGHT"; return; }
   if(risk_atr>T3_MAX_STOP_ATR) { decision.reject_code="T3_STOP_TOO_WIDE"; return; }
   decision.signal_pass=true; decision.direction=-1;
   decision.reject_code="T3_SIGNAL_OK";
  }

//+------------------------------------------------------------------+
//| Audit order lifecycle — mirrors engine/execution.py               |
//| Long fills on the synthetic Ask, exits on the Bid.                |
//| Short fills on the Bid, exits on the synthetic Ask.               |
//+------------------------------------------------------------------+
void SideCandle(const BarView &bar,const int direction,const bool entry,
                double &o,double &h,double &l,double &c)
  {
   double spread = bar.spread_points*g_point;
   bool use_ask = (direction>0) == entry;   // long entry / short exit use Ask
   double offset = use_ask ? spread : 0.0;
   o=bar.open+offset; h=bar.high+offset; l=bar.low+offset; c=bar.close+offset;
  }

//--- Returns true when a fill occurred.
bool TryFill(const BarView &bar,string &status)
  {
   if(!g_order.active) return false;
   if(g_bar_index>g_order.expiry_bar_index)
     { g_order.active=false; status="EXPIRED"; return false; }

   double o,h,l,c;
   SideCandle(bar,g_order.direction,true,o,h,l,c);
   bool triggered=false;
   double base_fill=0.0;
   bool gap=false;
   if(g_order.direction>0)
     {
      if(h>=g_order.trigger)
        { triggered=true; base_fill=MathMax(g_order.trigger,o); gap=(o>g_order.trigger); }
     }
   else
     {
      if(l<=g_order.trigger)
        { triggered=true; base_fill=MathMin(g_order.trigger,o); gap=(o<g_order.trigger); }
     }
   if(!triggered)
     {
      if(g_bar_index==g_order.expiry_bar_index)
        { g_order.active=false; status="EXPIRED"; }
      return false;
     }

   double distance = (g_order.direction>0) ? (base_fill-g_order.stop)
                                           : (g_order.stop-base_fill);
   if(distance<=0.0)
     { g_order.active=false; status="CANCELLED_INVALID_RISK"; return false; }

   g_position.active=true;
   g_position.direction=g_order.direction;
   g_position.setup_id=g_order.setup_id;
   g_position.signal_time=g_order.signal_time;
   g_position.entry_time=bar.time;
   g_position.entry=base_fill;
   g_position.stop=g_order.stop;
   g_position.target=base_fill + InpRewardMultiple*distance*((g_order.direction>0)?1.0:-1.0);
   g_position.quantity=g_order.quantity;
   g_position.planned_risk=g_order.planned_risk;
   g_position.gap_through_trigger=gap;
   g_position.entered_intrabar = (!gap && ((g_order.direction>0 && o<g_order.trigger)
                                        || (g_order.direction<0 && o>g_order.trigger)));
   g_order.active=false;
   status="FILLED";
   return true;
  }

//--- Returns true when the position closed on this bar.
bool TryExit(const BarView &bar,double &exit_price,string &reason,double &realized_r)
  {
   if(!g_position.active) return false;
   double o,h,l,c;
   SideCandle(bar,g_position.direction,false,o,h,l,c);
   bool entered_intrabar = (g_position.entry_time==bar.time) && g_position.entered_intrabar;

   bool stop_hit=false, target_hit=false;
   if(g_position.direction>0)
     {
      if(!entered_intrabar && o<=g_position.stop)
        { exit_price=o; reason="Stop loss (opening gap)"; }
      else if(!entered_intrabar && o>=g_position.target)
        { exit_price=g_position.target; reason="Take profit (opening gap)"; }
      else
        { stop_hit=(l<=g_position.stop); target_hit=(h>=g_position.target); reason=""; }
     }
   else
     {
      if(!entered_intrabar && o>=g_position.stop)
        { exit_price=o; reason="Stop loss (opening gap)"; }
      else if(!entered_intrabar && o<=g_position.target)
        { exit_price=g_position.target; reason="Take profit (opening gap)"; }
      else
        { stop_hit=(h>=g_position.stop); target_hit=(l<=g_position.target); reason=""; }
     }

   if(reason=="")
     {
      if(stop_hit && target_hit)
        { exit_price=g_position.stop; reason="Stop loss (ambiguous bar, SL First)"; }
      else if(stop_hit)
        { exit_price=g_position.stop; reason="Stop loss"; }
      else if(target_hit)
        { exit_price=g_position.target; reason="Take profit"; }
      else
         return false;
     }

   double sign = (g_position.direction>0) ? 1.0 : -1.0;
   double gross = sign*(exit_price-g_position.entry)*g_position.quantity;
   realized_r = (g_position.planned_risk>0.0) ? gross/g_position.planned_risk : 0.0;
   g_balance += gross;
   g_position.active=false;
   return true;
  }

void CreateAuditOrder(const Decision &decision,const BarView &bar,const string setup_id)
  {
   //--- No transmission in Stage 1: the guard refuses, and only the internal
   //--- model advances. This call documents the exact point a live build
   //--- would submit, and proves it cannot happen here.
   SendOrderGuard(setup_id);

   double planned_risk=0.0;
   double quantity = AuditQuantity(decision.trigger,decision.stop,planned_risk);
   g_order.active=true;
   g_order.direction=decision.direction;
   g_order.setup_id=setup_id;
   g_order.signal_time=bar.time+STEP_SECONDS;
   g_order.created_time=bar.time+STEP_SECONDS;
   g_order.trigger=decision.trigger;
   g_order.stop=decision.stop;
   g_order.expiry_time=bar.time+STEP_SECONDS*A4_PENDING_BARS;
   g_order.created_bar_index=g_bar_index;
   g_order.expiry_bar_index=g_bar_index+A4_PENDING_BARS;
   g_order.quantity=quantity;
   g_order.planned_risk=planned_risk;
  }

//+------------------------------------------------------------------+
//| Process exactly one just-closed M15 bar                           |
//+------------------------------------------------------------------+
void ProcessClosedBar(const int shift)
  {
   BarView bar;
   bar.time  = iTime(_Symbol,PERIOD_M15,shift);
   bar.open  = iOpen(_Symbol,PERIOD_M15,shift);
   bar.high  = iHigh(_Symbol,PERIOD_M15,shift);
   bar.low   = iLow(_Symbol,PERIOD_M15,shift);
   bar.close = iClose(_Symbol,PERIOD_M15,shift);
   bar.tick_volume = iTickVolume(_Symbol,PERIOD_M15,shift);
   bar.spread_points = (int)iSpread(_Symbol,PERIOD_M15,shift);

   //--- A missing bar breaks indicator continuity. The Python engine splits
   //--- the dataset into continuous segments and resets; mirror that here.
   if(g_last_processed!=0 && bar.time-g_last_processed!=STEP_SECONDS)
     {
      ResetAll();
      Print("Data gap before ",TimeToString(bar.time),": indicators and state reset.");
     }
   g_last_processed=bar.time;

   //--- 1. order lifecycle on this bar, before the strategy sees it
   string pending_status="";
   double exit_price=0.0, realized_r=0.0;
   string exit_reason="";
   bool filled = TryFill(bar,pending_status);
   bool closed = TryExit(bar,exit_price,exit_reason,realized_r);
   if(filled) { g_a4.trades_today++; g_t3.trades_today++; ResetPullback(false); }

   //--- 2. indicators
   H1Update(g_h1,bar.time,bar.open,bar.high,bar.low,bar.close);
   bar.ema20 = EmaUpdate(g_ema20,bar.close);
   bar.ema50 = EmaUpdate(g_ema50,bar.close);
   bar.has_atr = AtrUpdate(g_atr,bar.high,bar.low,bar.close,bar.atr);
   bar.has_rsi = RsiUpdate(g_rsi,bar.close,bar.rsi);
   bar.has_adx = DmiUpdate(g_dmi,bar.high,bar.low,bar.close,bar.plus_di,bar.minus_di,bar.adx);

   MqlDateTime parts;
   TimeToStruct(bar.time,parts);
   bar.in_session = (parts.hour>=SESSION_START_HOUR && parts.hour<SESSION_END_HOUR);
   int day_key = parts.year*10000+parts.mon*100+parts.day;
   if(day_key!=g_day_key)
     { g_day_key=day_key; g_a4.trades_today=0; g_t3.trades_today=0; }

   //--- 3. prior-bar windows, read BEFORE this bar joins the buffer
   double prior_high=0.0, trend_low=0.0, trend_high=0.0;
   bool has_prior_high = BufferHighest(g_prior,A4_STRUCTURE_LOOKBACK,prior_high);
   bool has_trend_low  = BufferLowest(g_prior,T3_STRUCTURE_LOOKBACK,trend_low);
   bool has_trend_high = BufferHighest(g_prior,T3_STRUCTURE_LOOKBACK,trend_high);
   double previous_high = (g_prior.count>0) ? g_prior.high[g_prior.count-1] : 0.0;
   double previous_low  = (g_prior.count>0) ? g_prior.low[g_prior.count-1]  : 0.0;
   bool has_previous = (g_prior.count>0);
   //--- trend_stop_lookback = 2 -> one prior bar plus the current bar
   double stop_high = has_previous ? MathMax(previous_high,bar.high) : bar.high;
   double stop_low  = has_previous ? MathMin(previous_low,bar.low)   : bar.low;

   bool blocked = (g_order.active || g_position.active);
   string a4_blocked_code = g_order.active ? "A4_BLOCKED_PENDING" : "A4_BLOCKED_POSITION";
   string t3_blocked_code = g_order.active ? "T3_BLOCKED_PENDING" : "T3_BLOCKED_POSITION";

   Decision a4, t3;
   string regime_label="";
   EvaluateA4(bar,prior_high,has_prior_high,previous_high,has_previous,
              blocked,a4_blocked_code,a4);
   EvaluateT3(bar,trend_low,has_trend_low,stop_high,blocked,t3_blocked_code,regime_label,t3);

   //--- 4. Core composition: A4 has deterministic priority (btc_v3_core_v1.py)
   string signal_side="", signal_setup="";
   if(!blocked)
     {
      if(a4.signal_pass)
        { CreateAuditOrder(a4,bar,A4_SETUP_ID); signal_side="LONG"; signal_setup=A4_SETUP_ID; pending_status="CREATED"; }
      else if(t3.signal_pass)
        { CreateAuditOrder(t3,bar,T3_SETUP_ID); signal_side="SHORT"; signal_setup=T3_SETUP_ID; pending_status="CREATED"; }
     }
   if(pending_status=="" && g_order.active) pending_status="ACTIVE";

   BufferPush(g_prior,bar.time,bar.open,bar.high,bar.low,bar.close);
   g_bar_index++;

   //--- 5. log
   double slope=0.0; bool has_slope = H1Slope(g_h1,slope);
   double separation=0.0; bool has_separation = H1SeparationAtr(g_h1,separation);
   FileWrite(g_file,
     IsoUtc(bar.time,true),_Symbol,
     Num(bar.open,true),Num(bar.high,true),Num(bar.low,true),Num(bar.close,true),
     Num((double)bar.tick_volume,true),
     Num((double)bar.spread_points,true),Num(bar.spread_points*g_point,true),
     IsoUtc(g_h1.confirmed_hour,g_h1.confirmed),
     Num(g_h1.confirmed_open,g_h1.confirmed),Num(g_h1.confirmed_high,g_h1.confirmed),
     Num(g_h1.confirmed_low,g_h1.confirmed),Num(g_h1.confirmed_close,g_h1.confirmed),
     Num(g_h1.confirmed_fast,g_h1.confirmed),Num(g_h1.confirmed_slow,g_h1.confirmed),
     Num(g_h1.confirmed_past,g_h1.has_past),Num(g_h1.confirmed_atr,g_h1.has_atr),
     Num(slope,has_slope),
     Num(has_slope && g_h1.has_atr && g_h1.confirmed_atr>0.0 ? slope/g_h1.confirmed_atr : 0.0,
         has_slope && g_h1.has_atr && g_h1.confirmed_atr>0.0),
     Num(separation,has_separation),
     Num(bar.ema20,true),Num(bar.ema50,true),Num(bar.atr,bar.has_atr),
     Num(bar.rsi,bar.has_rsi),Num(bar.adx,bar.has_adx),
     Num(bar.plus_di,bar.has_adx),Num(bar.minus_di,bar.has_adx),
     Num(BodyPercent(bar.open,bar.high,bar.low,bar.close),true),
     Flag(a4.context_pass,true),Flag(a4.signal_pass,true),a4.reject_code,
     Flag(bar.in_session,true),IntegerToString(g_a4.trades_today),
     Flag(bar.has_atr && bar.atr>0.0 && bar.close<bar.ema50-A4_MATERIAL_EMA50_ATR*bar.atr,true),
     Flag(g_a4.pullback_active,true),
     Num(g_a4.pullback_low,g_a4.has_pullback_low),
     Num(g_a4.pullback_max_depth_atr,true),IntegerToString(g_a4.pullback_bars),
     g_a4.pullback_touch,Num(g_a4.structure_level,g_a4.has_structure),
     Num(prior_high,has_prior_high),
     Num(a4.trigger,a4.has_levels),Num(a4.stop,a4.has_levels),Num(a4.stop_atr,a4.has_levels),
     regime_label,Flag(t3.context_pass,true),Flag(t3.signal_pass,true),t3.reject_code,
     Num(trend_high,has_trend_high),Num(trend_low,has_trend_low),
     Num(stop_high,true),Num(stop_low,true),
     Num(bar.has_atr ? (bar.high-bar.low)/bar.atr : 0.0,bar.has_atr),
     Num(bar.has_atr ? MathAbs(bar.close-bar.ema20)/bar.atr : 0.0,bar.has_atr),
     Num(t3.trigger,t3.has_levels),Num(t3.stop,t3.has_levels),Num(t3.stop_atr,t3.has_levels),
     signal_side,signal_setup,IsoUtc(bar.time+STEP_SECONDS,signal_side!=""),
     pending_status,
     Num(g_order.trigger,g_order.active),Num(g_order.stop,g_order.active),
     IsoUtc(g_order.expiry_time,g_order.active),
     IsoUtc(g_position.entry_time,filled),Num(g_position.entry,filled),
     Num(g_position.stop,filled),Num(g_position.target,filled),
     IsoUtc(bar.time,closed),Num(exit_price,closed),exit_reason,Num(realized_r,closed),
     "UNVERIFIED","UNVERIFIED","UNVERIFIED");
   FileFlush(g_file);
  }

//+------------------------------------------------------------------+
//| MT5 entry points                                                  |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_halted=false; g_halt_reason="";
   if(_Symbol!=InpSymbolExpected)
     { g_halt_reason="Symbol is "+_Symbol+", expected "+InpSymbolExpected; }
   g_digits=(int)SymbolInfoInteger(_Symbol,SYMBOL_DIGITS);
   g_point=SymbolInfoDouble(_Symbol,SYMBOL_POINT);
   if(g_halt_reason=="" && g_digits!=2)
      g_halt_reason="Expected 2 digits for BTCUSDm; broker reports "+IntegerToString(g_digits);
   if(g_halt_reason=="" && MathAbs(g_point-0.01)>1e-12)
      g_halt_reason="Expected point 0.01; broker reports "+DoubleToString(g_point,10);
   if(g_halt_reason=="" && InpRequireUtcServer)
     {
      int offset=(int)(TimeTradeServer()-TimeGMT());
      if(MathAbs(offset)>60)
         g_halt_reason="Server clock is not UTC (offset "+IntegerToString(offset)+"s). "
                       "R1 recorded a zero offset; parity would be meaningless otherwise.";
     }
   if(g_halt_reason!="")
     {
      g_halted=true;
      Print("BTC CORE V1 HALTED: ",g_halt_reason);
      Comment("BTC CORE V1 — HALTED — ",g_halt_reason);
      return INIT_SUCCEEDED;   // stay loaded so the operator can read the reason
     }
   if(!OpenLog())
      return INIT_FAILED;
   ResetAll();
   g_last_bar_time=0;
   g_last_processed=0;
   Comment("BTC CORE V1 — AUDIT ONLY — NO ORDERS");
   Print("BTC CORE V1 — AUDIT ONLY — NO ORDERS. Fingerprint ",CORE_FINGERPRINT);
   if(InpMode!=AUDIT_ONLY)
      Print("WARNING: DEMO_EXECUTION selected, but transmission is not implemented; "
            "the EA still sends nothing.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_file!=INVALID_HANDLE) FileClose(g_file);
   Comment("");
  }

void OnTick()
  {
   if(g_halted) return;
   datetime current = iTime(_Symbol,PERIOD_M15,0);
   if(current==0 || current==g_last_bar_time)
      return;
   //--- A new forming bar exists, so shift 1 is the bar that just closed.
   if(g_last_bar_time!=0)
      ProcessClosedBar(1);
   g_last_bar_time=current;
   Comment("BTC CORE V1 — ",(InpMode==AUDIT_ONLY ? "AUDIT ONLY — NO ORDERS" : "NO TRANSMISSION IMPLEMENTED"),
           "\nBars audited: ",IntegerToString(g_bar_index),
           "\nPending: ",(g_order.active?"YES":"no"),
           "  Position: ",(g_position.active?"YES":"no"),
           "\nBalance (simulated): ",DoubleToString(g_balance,2));
  }

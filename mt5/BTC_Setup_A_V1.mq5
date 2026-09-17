//+------------------------------------------------------------------+
//| BTC Setup A V1 Research Candidate                                |
//| FROZEN RESEARCH: AUDIT_ONLY by default; demo account orders only. |
//| Pine V2.2.0 standalone Setup A; no Setup B or volatility gate.    |
//+------------------------------------------------------------------+
#property strict
#property version "1.00"
#property description "Frozen BTC Setup A V1; research and demo validation only"
#include <Trade/Trade.mqh>

enum EA_MODE { AUDIT_ONLY=0, DEMO_TRADE=1 };
input EA_MODE InpMode=AUDIT_ONLY;
input ulong InpMagicNumber=515010220;

const string FREEZE_HASH="b9c1f07ed3ec4b068f65d0ede59e6a94dc6985c4ad8824ae606c168c7f33b649";
const string EA_NAME="BTC Setup A V1";
const string AUDIT_FILE="BTC_Setup_A_V1_Audit.csv";
const double START_BALANCE=10000.0;
const double RISK_PERCENT=0.25;
const double REWARD=3.0;
const int STEP_SECONDS=900;
const int MAGIC_DIGITS=2;
CTrade g_trade;
int g_file=INVALID_HANDLE;
datetime g_current_open=0, g_last_processed=0, g_segment_start=0;
bool g_halted=false;
string g_halt_reason="";

// M15 streaming Pine-compatible state. RMA counts include seed values.
int g_bar_index=0, g_last_touch_index=-1;
bool g_have_prev=false, g_have_ema=false;
double g_prev_close=0,g_prev_high=0,g_prev_low=0,g_ema20=0,g_ema50=0;
double g_atr=0,g_atr_sum=0; int g_atr_count=0;
double g_gain=0,g_gain_sum=0; int g_gain_count=0;
double g_loss=0,g_loss_sum=0; int g_loss_count=0;
double g_dtr=0,g_dtr_sum=0; int g_dtr_count=0;
double g_plus=0,g_plus_sum=0; int g_plus_count=0;
double g_minus=0,g_minus_sum=0; int g_minus_count=0;
double g_adx=0,g_adx_sum=0; int g_adx_count=0;
double g_rsi_value=-1,g_adx_value=-1,g_plus_di=-1,g_minus_di=-1;

// Complete H1 only after bars at minute 00,15,30,45 have all closed.
datetime g_h1_bucket=0,g_h1_confirmed_time=0;
int g_h1_bucket_count=0,g_h1_completed_count=0,g_h1_slow_count=0;
bool g_h1_bucket_valid=true,g_h1_ema_ready=false,g_h1_ready=false;
double g_h1_bucket_close=0,g_h1_fast=0,g_h1_slow=0;
double g_h1_slow_history[6];
double g_h1_confirmed_close=0,g_h1_confirmed_fast=0;
double g_h1_confirmed_slow=0,g_h1_confirmed_past=0;

// Isolated strategy-account telemetry. It does not include the user's Gold EA.
double g_balance=START_BALANCE,g_day_start_equity=START_BALANCE;
double g_month_start_equity=START_BALANCE,g_all_time_high=START_BALANCE;
int g_day_key=-1,g_month_key=-1,g_trades_today=0,g_loss_streak=0;
bool g_daily_dd_lock=false,g_daily_streak_lock=false,g_monthly_lock=false;
bool g_all_time_lock=false;
string g_global_prefix="";

struct AuditOrder
  {
   bool active;
   datetime signal_time;
   datetime expiry_time;
   int direction; // +1 LONG, -1 SHORT
   double trigger;
   double stop;
   double volume;
  };
struct AuditPosition
  {
   bool active;
   datetime signal_time;
   datetime fill_time;
   int direction;
   double entry;
   double stop;
   double target;
   double volume;
   double planned_risk;
  };
AuditOrder g_paper_order;
AuditPosition g_paper_position;

string Stamp(datetime value)
  {
   if(value<=0) return "";
   return TimeToString(value,TIME_DATE|TIME_SECONDS);
  }
string Side(int direction) { return direction>0 ? "LONG" : (direction<0 ? "SHORT" : "NONE"); }
string BoolText(bool value) { return value ? "true" : "false"; }
void AddReason(string &reasons,const string fragment)
  {
   if(reasons!="") reasons+=";";
   reasons+=fragment;
  }

void LogRecord(const string event_name,datetime event_time,datetime signal_time,
               int direction,bool qualified,const string reason,
               double signal_price,double trigger,double stop,double target,
               double planned_cash_risk,double raw_volume,double volume,double actual_risk,
               ulong ticket,datetime fill_time,double fill_price,
               datetime exit_time,double exit_price,double pnl,double realized_r)
  {
   MqlTick tick; ZeroMemory(tick);
   SymbolInfoTick(_Symbol,tick);
   double spread=tick.ask-tick.bid;
   if(g_file!=INVALID_HANDLE)
     {
      FileWrite(g_file,event_name,Stamp(event_time),
                Stamp(signal_time>0 ? signal_time+STEP_SECONDS : 0),Stamp(signal_time),_Symbol,"A",
                Side(direction),BoolText(qualified),reason,
                DoubleToString(g_ema20,8),DoubleToString(g_ema50,8),
                DoubleToString(g_atr_count>=14 ? g_atr : -1,8),
                DoubleToString(g_rsi_value,8),DoubleToString(g_adx_value,8),
                DoubleToString(g_plus_di,8),DoubleToString(g_minus_di,8),
                Stamp(g_h1_confirmed_time),DoubleToString(g_h1_confirmed_close,8),
                DoubleToString(g_h1_confirmed_fast,8),DoubleToString(g_h1_confirmed_slow,8),
                DoubleToString(g_h1_confirmed_past,8),
                DoubleToString(signal_price,8),DoubleToString(trigger,8),
                DoubleToString(stop,8),DoubleToString(target,8),
                DoubleToString(planned_cash_risk,8),DoubleToString(raw_volume,8),
                DoubleToString(volume,8),DoubleToString(actual_risk,8),
                IntegerToString((long)ticket),IntegerToString((long)InpMagicNumber),
                DoubleToString(tick.bid,8),DoubleToString(tick.ask,8),DoubleToString(spread,8),
                Stamp(fill_time),DoubleToString(fill_price,8),
                Stamp(exit_time),DoubleToString(exit_price,8),
                DoubleToString(pnl,8),DoubleToString(realized_r,8));
      FileFlush(g_file);
     }
   Print(EA_NAME," ",event_name," ",Side(direction)," signal=",Stamp(signal_time),
         " reason=",reason," ticket=",IntegerToString((long)ticket));
  }

bool OpenLog()
  {
   g_file=FileOpen(AUDIT_FILE,FILE_READ|FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_SHARE_READ,',');
   if(g_file==INVALID_HANDLE) { Print("Audit FileOpen failed: ",GetLastError()); return false; }
   if(FileSize(g_file)==0)
      FileWrite(g_file,"event","event_time_utc","signal_time","signal_candle_time","symbol","setup",
                "direction","qualified","reason","ema20","ema50","atr","rsi","adx",
                "plus_di","minus_di","h1_time_utc","h1_close","h1_ema50","h1_ema200",
                "h1_ema200_past","signal_price","trigger","stop","target",
                "planned_cash_risk","raw_volume","volume","actual_planned_risk",
                "ticket","magic","bid","ask","spread","fill_time","fill_price",
                "exit_time","exit_price","pnl","realized_r");
   FileSeek(g_file,0,SEEK_END);
   return true;
  }

double RmaUpdate(double value,int length,double &average,double &seed_sum,int &count)
  {
   if(count<length)
     {
      seed_sum+=value; count++;
      if(count==length) average=seed_sum/length;
     }
   else average+=(value-average)/length;
   return average;
  }
void ResetIndicators(datetime start_time)
  {
   g_segment_start=start_time; g_bar_index=0; g_last_touch_index=-1;
   g_have_prev=false; g_have_ema=false;
   g_prev_close=0; g_prev_high=0; g_prev_low=0; g_ema20=0; g_ema50=0;
   g_atr=0; g_atr_sum=0; g_atr_count=0;
   g_gain=0; g_gain_sum=0; g_gain_count=0;
   g_loss=0; g_loss_sum=0; g_loss_count=0;
   g_dtr=0; g_dtr_sum=0; g_dtr_count=0;
   g_plus=0; g_plus_sum=0; g_plus_count=0;
   g_minus=0; g_minus_sum=0; g_minus_count=0;
   g_adx=0; g_adx_sum=0; g_adx_count=0;
   g_rsi_value=-1; g_adx_value=-1; g_plus_di=-1; g_minus_di=-1;
   g_h1_bucket=0; g_h1_confirmed_time=0; g_h1_bucket_count=0;
   g_h1_completed_count=0; g_h1_slow_count=0;
   g_h1_bucket_valid=true; g_h1_ema_ready=false; g_h1_ready=false;
   g_h1_bucket_close=0; g_h1_fast=0; g_h1_slow=0;
   g_h1_confirmed_close=0; g_h1_confirmed_fast=0;
   g_h1_confirmed_slow=0; g_h1_confirmed_past=0;
   ArrayInitialize(g_h1_slow_history,0.0);
  }
void CompleteH1()
  {
   if(g_h1_bucket_count!=4 || !g_h1_bucket_valid) return;
   if(!g_h1_ema_ready)
     {
      g_h1_fast=g_h1_bucket_close;
      g_h1_slow=g_h1_bucket_close;
      g_h1_ema_ready=true;
     }
   else
     {
      g_h1_fast+=2.0/51.0*(g_h1_bucket_close-g_h1_fast);
      g_h1_slow+=2.0/201.0*(g_h1_bucket_close-g_h1_slow);
     }
   if(g_h1_slow_count<6) g_h1_slow_history[g_h1_slow_count++]=g_h1_slow;
   else
     {
      for(int k=0;k<5;k++) g_h1_slow_history[k]=g_h1_slow_history[k+1];
      g_h1_slow_history[5]=g_h1_slow;
     }
   g_h1_completed_count++;
   g_h1_confirmed_time=g_h1_bucket;
   g_h1_confirmed_close=g_h1_bucket_close;
   g_h1_confirmed_fast=g_h1_fast;
   g_h1_confirmed_slow=g_h1_slow;
   g_h1_confirmed_past=(g_h1_slow_count==6 ? g_h1_slow_history[0] : 0);
   g_h1_ready=(g_h1_slow_count==6);
  }
void UpdateH1(MqlRates &bar)
  {
   datetime hour=(datetime)(((long)bar.time/3600)*3600);
   if(g_h1_bucket!=0 && hour!=g_h1_bucket)
     {
      CompleteH1(); g_h1_bucket_count=0; g_h1_bucket_valid=true;
     }
   if(hour!=g_h1_bucket) g_h1_bucket=hour;
   if(bar.time!=g_h1_bucket+g_h1_bucket_count*STEP_SECONDS)
      g_h1_bucket_valid=false;
   g_h1_bucket_count++;
   g_h1_bucket_close=bar.close;
  }

datetime FirstSearchTime()
  {
   long ceil_hour=((long)g_segment_start+3599)/3600*3600;
   datetime m15_ready=g_segment_start+49*STEP_SECONDS;
   datetime h1_ready=(datetime)(ceil_hour+205*3600);
   return (m15_ready>h1_ready ? m15_ready : h1_ready);
  }
double VirtualMarkedEquity(double bid_close)
  {
   double equity=g_balance;
   if(InpMode==AUDIT_ONLY && g_paper_position.active)
      equity+=g_paper_position.direction*(bid_close-g_paper_position.entry)*g_paper_position.volume;
   if(InpMode==DEMO_TRADE)
     {
      for(int i=0;i<PositionsTotal();i++)
        {
         ulong ticket=PositionGetTicket(i);
         if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
         if(PositionGetString(POSITION_SYMBOL)!=_Symbol ||
            (ulong)PositionGetInteger(POSITION_MAGIC)!=InpMagicNumber) continue;
         int sign=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1);
         equity+=sign*(bid_close-PositionGetDouble(POSITION_PRICE_OPEN))*
                 PositionGetDouble(POSITION_VOLUME); // frozen marked-Bid convention
        }
     }
   return equity;
  }

int UtcDayKey(datetime moment)
  {
   MqlDateTime value; TimeToStruct(moment,value);
   return value.year*10000+value.mon*100+value.day;
  }
int UtcMonthKey(datetime moment)
  {
   MqlDateTime value; TimeToStruct(moment,value);
   return value.year*100+value.mon;
  }
void PersistRisk()
  {
   if(InpMode!=DEMO_TRADE) return;
   GlobalVariableSet(g_global_prefix+"_day",(double)g_day_key);
   GlobalVariableSet(g_global_prefix+"_month",(double)g_month_key);
   GlobalVariableSet(g_global_prefix+"_dayeq",g_day_start_equity);
   GlobalVariableSet(g_global_prefix+"_montheq",g_month_start_equity);
   GlobalVariableSet(g_global_prefix+"_peak",g_all_time_high);
   GlobalVariableSet(g_global_prefix+"_dlock",g_daily_dd_lock ? 1.0 : 0.0);
   GlobalVariableSet(g_global_prefix+"_slock",g_daily_streak_lock ? 1.0 : 0.0);
   GlobalVariableSet(g_global_prefix+"_mlock",g_monthly_lock ? 1.0 : 0.0);
  }
bool RestoreRisk()
  {
   if(InpMode!=DEMO_TRADE) return true;
   if(!GlobalVariableCheck(g_global_prefix+"_day") ||
      !GlobalVariableCheck(g_global_prefix+"_month") ||
      !GlobalVariableCheck(g_global_prefix+"_dayeq") ||
      !GlobalVariableCheck(g_global_prefix+"_montheq") ||
      !GlobalVariableCheck(g_global_prefix+"_peak")) return false;
   g_day_key=(int)GlobalVariableGet(g_global_prefix+"_day");
   g_month_key=(int)GlobalVariableGet(g_global_prefix+"_month");
   g_day_start_equity=GlobalVariableGet(g_global_prefix+"_dayeq");
   g_month_start_equity=GlobalVariableGet(g_global_prefix+"_montheq");
   g_all_time_high=GlobalVariableGet(g_global_prefix+"_peak");
   g_daily_dd_lock=GlobalVariableGet(g_global_prefix+"_dlock")>0;
   g_daily_streak_lock=GlobalVariableGet(g_global_prefix+"_slock")>0;
   g_monthly_lock=GlobalVariableGet(g_global_prefix+"_mlock")>0;
   return true;
  }

ulong OwnOrderTicket()
  {
   for(int i=0;i<OrdersTotal();i++)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket)) continue;
      if(OrderGetString(ORDER_SYMBOL)==_Symbol &&
         (ulong)OrderGetInteger(ORDER_MAGIC)==InpMagicNumber) return ticket;
     }
   return 0;
  }
ulong OwnPositionTicket()
  {
   for(int i=0;i<PositionsTotal();i++)
     {
      ulong ticket=PositionGetTicket(i);
      if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
      if(PositionGetString(POSITION_SYMBOL)==_Symbol &&
         (ulong)PositionGetInteger(POSITION_MAGIC)==InpMagicNumber) return ticket;
     }
   return 0;
  }
void RefreshOwnHistory(datetime at_time)
  {
   if(InpMode!=DEMO_TRADE) return;
   g_balance=START_BALANCE; g_trades_today=0; g_loss_streak=0;
   if(!HistorySelect((datetime)0,at_time)) return;
   ulong own_position_ids[];
   int own_count=0;
   for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0 || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol ||
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagicNumber ||
         HistoryDealGetInteger(deal,DEAL_ENTRY)!=DEAL_ENTRY_IN) continue;
      ulong id=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
      bool known=false;
      for(int j=0;j<own_count;j++) if(own_position_ids[j]==id) known=true;
      if(!known)
        { ArrayResize(own_position_ids,own_count+1); own_position_ids[own_count++]=id; }
     }
   ulong seen_ids[32]; int seen_count=0;
   int today=UtcDayKey(at_time);
   for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0 || HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol) continue;
      ulong position_id=(ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID);
      bool ours=false;
      for(int j=0;j<own_count;j++) if(own_position_ids[j]==position_id) ours=true;
      if(!ours) continue;
      double net=HistoryDealGetDouble(deal,DEAL_PROFIT)+
                 HistoryDealGetDouble(deal,DEAL_COMMISSION)+
                 HistoryDealGetDouble(deal,DEAL_SWAP)+HistoryDealGetDouble(deal,DEAL_FEE);
      g_balance+=net;
      datetime when=(datetime)HistoryDealGetInteger(deal,DEAL_TIME);
      if(UtcDayKey(when)!=today) continue;
      ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal,DEAL_ENTRY);
      if(entry==DEAL_ENTRY_IN)
        {
         bool already=false;
         for(int j=0;j<seen_count;j++) if(seen_ids[j]==position_id) already=true;
         if(!already) { g_trades_today++; if(seen_count<32) seen_ids[seen_count++]=position_id; }
        }
      else if(entry==DEAL_ENTRY_OUT)
        {
         if(net<0) g_loss_streak++;
         else if(net>0) g_loss_streak=0;
        }
     }
  }
void UpdateRisk(MqlRates &bar)
  {
   if(InpMode==DEMO_TRADE) RefreshOwnHistory(bar.time+STEP_SECONDS-1);
   double equity=VirtualMarkedEquity(bar.close);
   int day=UtcDayKey(bar.time),month=UtcMonthKey(bar.time);
   if(day!=g_day_key)
     {
      g_day_key=day; g_day_start_equity=equity;
      g_daily_dd_lock=false; g_daily_streak_lock=false;
      if(InpMode==AUDIT_ONLY) { g_trades_today=0; g_loss_streak=0; }
     }
   if(month!=g_month_key)
     {
      g_month_key=month; g_month_start_equity=equity; g_monthly_lock=false;
     }
   g_all_time_high=MathMax(g_all_time_high,equity);
   if(g_day_start_equity>0 &&
      (g_day_start_equity-equity)/g_day_start_equity*100.0>=1.0) g_daily_dd_lock=true;
   if(g_loss_streak>=3) g_daily_streak_lock=true;
   if(g_month_start_equity>0 &&
      (g_month_start_equity-equity)/g_month_start_equity*100.0>=6.0) g_monthly_lock=true;
   // Frozen all-time protection is OFF. The original optional threshold is 10%.
   PersistRisk();
  }
string PermissionReason(MqlRates &bar)
  {
   MqlDateTime value; TimeToStruct(bar.time,value); // Exness server is verified UTC+0
   if(value.hour<7 || value.hour>=20) return "UTC trading session ended";
   if(g_trades_today>=3) return "Maximum trades per UTC day reached";
   if(g_daily_dd_lock) return "Daily equity drawdown limit reached";
   if(g_daily_streak_lock) return "Daily consecutive closed-loss limit reached";
   if(g_monthly_lock) return "Monthly equity drawdown limit reached";
   if(g_all_time_lock) return "All-time equity drawdown limit reached";
   return ""; // All seven UTC weekdays are enabled in the frozen candidate.
  }

void CancelOwnPending(const string reason,datetime at_time)
  {
   if(InpMode==AUDIT_ONLY)
     {
      if(!g_paper_order.active) return;
      LogRecord("ORDER_CANCELED",at_time,g_paper_order.signal_time,
                g_paper_order.direction,false,reason,0,g_paper_order.trigger,
                g_paper_order.stop,0,0,0,g_paper_order.volume,0,0,0,0,0,0,0,0);
      g_paper_order.active=false;
      return;
     }
   for(int i=OrdersTotal()-1;i>=0;i--)
     {
      ulong ticket=OrderGetTicket(i);
      if(ticket==0 || !OrderSelect(ticket)) continue;
      if(OrderGetString(ORDER_SYMBOL)!=_Symbol ||
         (ulong)OrderGetInteger(ORDER_MAGIC)!=InpMagicNumber) continue;
      string comment=OrderGetString(ORDER_COMMENT);
      datetime signal_time=0;
      if(StringFind(comment,"A1|")==0) signal_time=(datetime)StringToInteger(StringSubstr(comment,3));
      int direction=(OrderGetInteger(ORDER_TYPE)==ORDER_TYPE_BUY_STOP ? 1 : -1);
      double trigger=OrderGetDouble(ORDER_PRICE_OPEN),stop=OrderGetDouble(ORDER_SL);
      double volume=OrderGetDouble(ORDER_VOLUME_CURRENT);
      if(g_trade.OrderDelete(ticket) && g_trade.ResultRetcode()==TRADE_RETCODE_DONE)
         LogRecord("ORDER_CANCELED",at_time,signal_time,direction,false,reason,
                   0,trigger,stop,0,0,0,volume,
                   0,ticket,0,0,0,0,0,0);
      else Print("Own pending cancellation failed ticket=",ticket,
                 " retcode=",g_trade.ResultRetcode());
     }
  }

int UpdateIndicators(MqlRates &bar)
  {
   UpdateH1(bar); // H1 state excludes the current, unfinished H1 bucket.
   g_bar_index++;
   if(!g_have_ema) { g_ema20=bar.close; g_ema50=bar.close; g_have_ema=true; }
   else
     {
      g_ema20+=2.0/21.0*(bar.close-g_ema20);
      g_ema50+=2.0/51.0*(bar.close-g_ema50);
     }
   double tr=bar.high-bar.low;
   if(g_have_prev) tr=MathMax(tr,MathMax(MathAbs(bar.high-g_prev_close),
                                        MathAbs(bar.low-g_prev_close)));
   RmaUpdate(tr,14,g_atr,g_atr_sum,g_atr_count);
   if(g_have_prev)
     {
      double change=bar.close-g_prev_close;
      RmaUpdate(MathMax(change,0.0),14,g_gain,g_gain_sum,g_gain_count);
      RmaUpdate(MathMax(-change,0.0),14,g_loss,g_loss_sum,g_loss_count);
      if(g_gain_count>=14 && g_loss_count>=14)
         g_rsi_value=(g_loss==0 ? (g_gain>0 ? 100.0 : 50.0) :
                      100.0-100.0/(1.0+g_gain/g_loss));
      double up=bar.high-g_prev_high,down=g_prev_low-bar.low;
      double p=(up>down && up>0 ? up : 0.0);
      double m=(down>up && down>0 ? down : 0.0);
      RmaUpdate(tr,14,g_dtr,g_dtr_sum,g_dtr_count);
      RmaUpdate(p,14,g_plus,g_plus_sum,g_plus_count);
      RmaUpdate(m,14,g_minus,g_minus_sum,g_minus_count);
      if(g_dtr_count>=14 && g_plus_count>=14 && g_minus_count>=14)
        {
         double divisor=(g_dtr!=0 ? g_dtr : 1.0);
         g_plus_di=100.0*g_plus/divisor;
         g_minus_di=100.0*g_minus/divisor;
         double total=g_plus_di+g_minus_di;
         double dx=100.0*MathAbs(g_plus_di-g_minus_di)/(total!=0 ? total : 1.0);
         RmaUpdate(dx,14,g_adx,g_adx_sum,g_adx_count);
         if(g_adx_count>=14) g_adx_value=g_adx;
        }
     }
   else RmaUpdate(tr,14,g_dtr,g_dtr_sum,g_dtr_count);
   int prior_touch=(g_last_touch_index<0 ? -1 : g_bar_index-1-g_last_touch_index);
   if((bar.high>=g_ema20 && g_ema20>=bar.low) ||
      (bar.high>=g_ema50 && g_ema50>=bar.low)) g_last_touch_index=g_bar_index;
   g_prev_close=bar.close; g_prev_high=bar.high; g_prev_low=bar.low;
   g_have_prev=true;
   return prior_touch;
  }

double FloorVolume(double raw)
  {
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   if(step<=0 || raw<minimum) return 0;
   double rounded=MathFloor(raw/step+1e-10)*step;
   rounded=MathMin(rounded,maximum);
   return (rounded+1e-10>=minimum ? NormalizeDouble(rounded,2) : 0);
  }
double PriceTick(double price)
  {
   double tick=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_TICK_SIZE);
   if(tick<=0) tick=_Point;
   return NormalizeDouble(MathRound(price/tick)*tick,_Digits);
  }
bool OwnStateActive()
  {
   if(InpMode==AUDIT_ONLY) return g_paper_order.active || g_paper_position.active;
   return OwnOrderTicket()!=0 || OwnPositionTicket()!=0;
  }

void PlaceSetupA(MqlRates &bar,int direction,double trigger,double stop)
  {
   double distance=MathAbs(trigger-stop);
   double cash_risk=VirtualMarkedEquity(bar.close)*RISK_PERCENT/100.0;
   double raw_by_risk=(distance>0 ? cash_risk/distance : 0);
   double raw_by_leverage=(trigger>0 ? g_balance/trigger : 0);
   double raw=MathMin(raw_by_risk,raw_by_leverage);
   double volume=FloorVolume(raw);
   double target=trigger+direction*REWARD*distance;
   if(volume<=0)
     {
      LogRecord("ORDER_BLOCKED",bar.time+STEP_SECONDS,bar.time,direction,false,
                "Below 0.01 lot minimum after rounding down",bar.close,trigger,stop,
                target,cash_risk,raw,volume,0,0,0,0,0,0,0,0);
      return;
     }
   Print("Setup A sizing planned_risk_$=",cash_risk," raw_lots=",raw,
         " rounded_lots=",volume," actual_planned_risk_$=",volume*distance);
   if(InpMode==AUDIT_ONLY)
     {
      g_paper_order.active=true;
      g_paper_order.signal_time=bar.time;
      g_paper_order.expiry_time=bar.time+3*STEP_SECONDS;
      g_paper_order.direction=direction;
      g_paper_order.trigger=trigger;
      g_paper_order.stop=stop;
      g_paper_order.volume=volume;
      LogRecord("ORDER_CREATED",bar.time+STEP_SECONDS,bar.time,direction,true,"AUDIT_ONLY",
                bar.close,trigger,stop,target,cash_risk,raw,volume,volume*distance,
                0,0,0,0,0,0,0);
      return;
     }
   double broker_trigger=PriceTick(trigger),broker_stop=PriceTick(stop);
   double provisional_target=PriceTick(broker_trigger+direction*REWARD*
                                       MathAbs(broker_trigger-broker_stop));
   datetime expiry=bar.time+3*STEP_SECONDS;
   string comment="A1|"+IntegerToString((long)bar.time);
   bool sent=(direction>0 ?
              g_trade.BuyStop(volume,broker_trigger,_Symbol,broker_stop,provisional_target,
                              ORDER_TIME_SPECIFIED,expiry,comment) :
              g_trade.SellStop(volume,broker_trigger,_Symbol,broker_stop,provisional_target,
                               ORDER_TIME_SPECIFIED,expiry,comment));
   ulong ticket=g_trade.ResultOrder();
   if(!sent || ticket==0)
     {
      LogRecord("ORDER_REJECTED",bar.time+STEP_SECONDS,bar.time,direction,false,
                "Broker pending rejection retcode="+IntegerToString((long)g_trade.ResultRetcode()),
                bar.close,broker_trigger,broker_stop,provisional_target,cash_risk,raw,volume,
                volume*MathAbs(broker_trigger-broker_stop),ticket,0,0,0,0,0,0);
      return;
     }
   LogRecord("ORDER_CREATED",bar.time+STEP_SECONDS,bar.time,direction,true,"DEMO_TRADE",
             bar.close,broker_trigger,broker_stop,provisional_target,cash_risk,raw,volume,
             volume*MathAbs(broker_trigger-broker_stop),ticket,0,0,0,0,0,0);
  }

void EvaluateBar(MqlRates &bar,int prior_touch)
  {
   UpdateRisk(bar);
   string permission=PermissionReason(bar);
   if(permission!="")
     {
      CancelOwnPending(permission,bar.time+STEP_SECONDS);
      LogRecord("SIGNAL_BLOCKED",bar.time+STEP_SECONDS,bar.time,0,false,
                permission,bar.close,0,0,0,0,0,0,0,0,0,0,0,0,0,0);
      return;
     }
   if(OwnStateActive())
     {
      LogRecord("SIGNAL_BLOCKED",bar.time+STEP_SECONDS,bar.time,0,false,
                "Own active pending or position",bar.close,0,0,0,0,0,0,0,
                0,0,0,0,0,0,0);
      return;
     }
   if(bar.time<FirstSearchTime()) return;
   double range=bar.high-bar.low;
   double location=(range>0 ? (bar.close-bar.low)/range : -1);
   int chosen=0; double chosen_trigger=0,chosen_stop=0;
   for(int direction=1;direction>=-1;direction-=2)
     {
      string reason="";
      bool h1=(g_h1_ready &&
               (direction>0 ? g_h1_confirmed_close>g_h1_confirmed_slow &&
                              g_h1_confirmed_fast>g_h1_confirmed_slow &&
                              g_h1_confirmed_slow>g_h1_confirmed_past :
                              g_h1_confirmed_close<g_h1_confirmed_slow &&
                              g_h1_confirmed_fast<g_h1_confirmed_slow &&
                              g_h1_confirmed_slow<g_h1_confirmed_past));
      if(!h1) AddReason(reason,"H1 trend");
      if(!(direction>0 ? g_ema20>g_ema50 : g_ema20<g_ema50)) AddReason(reason,"M15 EMA alignment");
      if(g_adx_value<18.0) AddReason(reason,"ADX below 18");
      if(!(direction>0 ? g_rsi_value>=54.0 && g_rsi_value<=68.0 :
                        g_rsi_value>=32.0 && g_rsi_value<=46.0)) AddReason(reason,"Directional RSI");
      if(prior_touch<0 || prior_touch>=5) AddReason(reason,"No recent prior EMA touch");
      if(g_atr_count<14 || g_atr<=0) AddReason(reason,"ATR unavailable");
      if(!(range>0 && (direction>0 ? bar.close>bar.open && location>=.60 &&
                       bar.low>=g_ema50-.50*g_atr :
                       bar.close<bar.open && location<=.40 &&
                       bar.high<=g_ema50+.50*g_atr))) AddReason(reason,"Rejection candle");
      if(range>2.50*g_atr) AddReason(reason,"Candle range above 2.5 ATR");
      double trigger=(direction>0 ? bar.high+.20*g_atr : bar.low-.20*g_atr);
      double stop=(direction>0 ? bar.low-.30*g_atr : bar.high+.30*g_atr);
      double distance=MathAbs(trigger-stop);
      if(trigger<=0 || stop<=0 || distance<=0 || g_atr<=0 ||
         distance/g_atr<.60 || distance/g_atr>3.00)
         AddReason(reason,"Stop distance outside 0.6 to 3 ATR");
      bool passed=reason=="";
      LogRecord("SIGNAL_EVALUATED",bar.time+STEP_SECONDS,bar.time,direction,passed,
                reason,bar.close,trigger,stop,trigger+direction*3.0*distance,
                0,0,0,0,0,0,0,0,0,0,0);
      if(passed && chosen==0)
        { chosen=direction; chosen_trigger=trigger; chosen_stop=stop; }
     }
   if(chosen!=0) PlaceSetupA(bar,chosen,chosen_trigger,chosen_stop);
  }

void AuditTick(MqlTick &tick)
  {
   if(g_paper_order.active && (datetime)tick.time>=g_paper_order.expiry_time)
     {
      LogRecord("ORDER_EXPIRED",(datetime)tick.time,g_paper_order.signal_time,
                g_paper_order.direction,false,"Two pending bars elapsed",0,
                g_paper_order.trigger,g_paper_order.stop,0,0,0,g_paper_order.volume,
                0,0,0,0,0,0,0,0);
      g_paper_order.active=false;
     }
   if(g_paper_order.active && !g_paper_position.active)
     {
      bool crossed=(g_paper_order.direction>0 ? tick.ask>=g_paper_order.trigger :
                                                    tick.bid<=g_paper_order.trigger);
      if(crossed)
        {
         double fill=(g_paper_order.direction>0 ? tick.ask : tick.bid);
         double risk=MathAbs(fill-g_paper_order.stop);
         if(risk<=0) { g_paper_order.active=false; return; }
         g_paper_position.active=true;
         g_paper_position.signal_time=g_paper_order.signal_time;
         g_paper_position.fill_time=(datetime)tick.time;
         g_paper_position.direction=g_paper_order.direction;
         g_paper_position.entry=fill;
         g_paper_position.stop=g_paper_order.stop;
         g_paper_position.target=fill+g_paper_order.direction*REWARD*risk;
         g_paper_position.volume=g_paper_order.volume;
         g_paper_position.planned_risk=risk*g_paper_order.volume;
         g_paper_order.active=false;
         g_trades_today++;
         LogRecord("ORDER_FILLED",(datetime)tick.time,g_paper_position.signal_time,
                   g_paper_position.direction,true,"AUDIT_ONLY quote-side trigger",0,
                   g_paper_order.trigger,g_paper_position.stop,g_paper_position.target,
                   0,0,g_paper_position.volume,g_paper_position.planned_risk,0,
                   (datetime)tick.time,fill,0,0,0,0);
        }
     }
   if(!g_paper_position.active) return;
   double exit_side=(g_paper_position.direction>0 ? tick.bid : tick.ask);
   bool stopped=(g_paper_position.direction>0 ? exit_side<=g_paper_position.stop :
                                                  exit_side>=g_paper_position.stop);
   bool target=(g_paper_position.direction>0 ? exit_side>=g_paper_position.target :
                                                 exit_side<=g_paper_position.target);
   if(!stopped && !target) return;
   double pnl=g_paper_position.direction*(exit_side-g_paper_position.entry)*
              g_paper_position.volume;
   double realized_r=(g_paper_position.planned_risk>0 ?
                      pnl/g_paper_position.planned_risk : 0);
   string why=(stopped ? "STOP_LOSS" : "TAKE_PROFIT");
   LogRecord(why,(datetime)tick.time,g_paper_position.signal_time,
             g_paper_position.direction,true,"AUDIT_ONLY tick-side exit",0,
             g_paper_order.trigger,g_paper_position.stop,g_paper_position.target,
             0,0,g_paper_position.volume,g_paper_position.planned_risk,0,
             g_paper_position.fill_time,g_paper_position.entry,
             (datetime)tick.time,exit_side,pnl,realized_r);
   LogRecord("POSITION_CLOSED",(datetime)tick.time,g_paper_position.signal_time,
             g_paper_position.direction,true,why,0,g_paper_order.trigger,
             g_paper_position.stop,g_paper_position.target,0,0,
             g_paper_position.volume,g_paper_position.planned_risk,0,
             g_paper_position.fill_time,g_paper_position.entry,
             (datetime)tick.time,exit_side,pnl,realized_r);
   g_balance+=pnl;
   if(pnl<0) g_loss_streak++;
   else if(pnl>0) g_loss_streak=0;
   g_paper_position.active=false;
  }

void ManageDemoTarget()
  {
   ulong ticket=OwnPositionTicket();
   if(ticket==0 || !PositionSelectByTicket(ticket)) return;
   double fill=PositionGetDouble(POSITION_PRICE_OPEN);
   double stop=PositionGetDouble(POSITION_SL);
   int direction=(PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY ? 1 : -1);
   if(stop<=0 || MathAbs(fill-stop)<=0)
     {
      Print("CRITICAL: own position lacks valid structural stop ticket=",ticket);
      g_halted=true; g_halt_reason="Own position lacks structural stop";
      return;
     }
   double target=PriceTick(fill+direction*REWARD*MathAbs(fill-stop));
   double current_target=PositionGetDouble(POSITION_TP);
   if(MathAbs(target-current_target)<=_Point/2) return;
   if(!g_trade.PositionModify(ticket,stop,target) ||
      g_trade.ResultRetcode()!=TRADE_RETCODE_DONE)
     {
      Print("CRITICAL: own 3R target placement failed ticket=",ticket,
            " retcode=",g_trade.ResultRetcode());
      g_halted=true; g_halt_reason="Actual-fill 3R target modification failed";
      return;
     }
   LogRecord("TARGET_SET",(datetime)TimeTradeServer(),0,direction,true,
             "3R from actual fill; broker modification",0,0,stop,target,0,0,
             PositionGetDouble(POSITION_VOLUME),0,ticket,0,fill,0,0,0,0);
  }

void ProcessCompletedBar(MqlRates &bar,bool evaluate)
  {
   if(g_last_processed!=0 && bar.time!=g_last_processed+STEP_SECONDS)
     {
      Print("BTC M15 DATA GAP from ",Stamp(g_last_processed)," to ",Stamp(bar.time),
            "; indicator and H1 state reset; no candle fabricated");
      CancelOwnPending("M15 data gap; pending cannot cross segment",bar.time);
      ResetIndicators(bar.time);
      if((InpMode==AUDIT_ONLY && g_paper_position.active) ||
         (InpMode==DEMO_TRADE && OwnPositionTicket()!=0))
        {
         g_halted=true;
         g_halt_reason="Own filled position across missing-data gap; manual review";
        }
     }
   int prior_touch=UpdateIndicators(bar);
   g_last_processed=bar.time;
   if(evaluate && !g_halted) EvaluateBar(bar,prior_touch);
  }

bool ValidateEnvironment()
  {
   bool valid=true;
   if(_Symbol!="BTCUSDm") { Print("Wrong symbol: attach only to BTCUSDm"); valid=false; }
   if(_Period!=PERIOD_M15) { Print("Wrong timeframe: use M15"); valid=false; }
   if(_Digits!=MAGIC_DIGITS || MathAbs(_Point-.01)>1e-9)
     { Print("Unexpected BTCUSDm digits/point: ",_Digits," / ",_Point); valid=false; }
   double contract=SymbolInfoDouble(_Symbol,SYMBOL_TRADE_CONTRACT_SIZE);
   double minimum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MIN);
   double maximum=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_MAX);
   double step=SymbolInfoDouble(_Symbol,SYMBOL_VOLUME_STEP);
   Print("Broker spec contract=",contract," min=",minimum," max=",maximum,
         " step=",step," digits=",_Digits," point=",_Point);
   if(MathAbs(contract-1.0)>1e-9 || MathAbs(minimum-.01)>1e-9 ||
      MathAbs(step-.01)>1e-9 || MathAbs(maximum-200.0)>1e-9)
     { Print("Broker contract/volume differs from frozen BTCUSDm profile"); valid=false; }
   if(SymbolInfoInteger(_Symbol,SYMBOL_CHART_MODE)!=SYMBOL_CHART_MODE_BID)
     { Print("BTCUSDm chart mode is not Bid; signal feed differs from frozen strategy"); valid=false; }
   if(InpMagicNumber==0) { Print("Magic Number must be nonzero and unique"); valid=false; }
   if(!MQLInfoInteger(MQL_TESTER))
     {
      long delta=(long)TimeTradeServer()-(long)TimeGMT();
      if(MathAbs((double)delta)>120)
        { Print("MT5 server offset from UTC exceeds two minutes: ",delta,
                " seconds. Stop until server timezone is verified."); valid=false; }
     }
   if(InpMode==DEMO_TRADE)
     {
      if(AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO)
        { Print("DEMO_TRADE requires an MT5 demo account. Live orders are disabled."); valid=false; }
      if(AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
        { Print("DEMO_TRADE requires hedging account to isolate symbol + Magic Number."); valid=false; }
      long expiration=SymbolInfoInteger(_Symbol,SYMBOL_EXPIRATION_MODE);
      if((expiration&SYMBOL_EXPIRATION_SPECIFIED)==0)
        { Print("BTCUSDm does not support specified pending expiry; cannot match two bars."); valid=false; }
     }
   return valid;
  }

int OnInit()
  {
   Print(EA_NAME," freeze hash ",FREEZE_HASH," mode=",EnumToString(InpMode),
         " magic=",InpMagicNumber);
   if(!ValidateEnvironment()) return INIT_FAILED;
   g_trade.SetExpertMagicNumber(InpMagicNumber);
   g_trade.SetAsyncMode(false);
   g_global_prefix="BTC_SETUP_A_V1_"+IntegerToString((long)AccountInfoInteger(ACCOUNT_LOGIN))+
                   "_"+_Symbol+"_"+IntegerToString((long)InpMagicNumber);
   if(!OpenLog()) return INIT_FAILED;
   ZeroMemory(g_paper_order); ZeroMemory(g_paper_position);
   if(InpMode==DEMO_TRADE)
     {
      bool restored=RestoreRisk();
      if(!restored && (OwnOrderTicket()!=0 || OwnPositionTicket()!=0))
        { Print("Cannot restore own protection references with active state. Halt."); return INIT_FAILED; }
     }
   MqlRates rates[];
   ArraySetAsSeries(rates,false);
   int copied=CopyRates(_Symbol,PERIOD_M15,1,Bars(_Symbol,PERIOD_M15)-1,rates);
   if(copied<=0) { Print("No completed BTCUSDm M15 bars to warm indicators"); return INIT_FAILED; }
   ResetIndicators(rates[0].time);
   for(int i=0;i<copied;i++) ProcessCompletedBar(rates[i],false);
   g_current_open=iTime(_Symbol,PERIOD_M15,0);
   if(InpMode==DEMO_TRADE) ManageDemoTarget();
   Print("EA SOURCE GENERATED; MT5 parity remains unverified. Warm bars=",copied,
         " confirmed H1=",Stamp(g_h1_confirmed_time));
   return INIT_SUCCEEDED;
  }

void OnTick()
  {
   MqlTick tick;
   if(!SymbolInfoTick(_Symbol,tick)) return;
   if(InpMode==AUDIT_ONLY) AuditTick(tick);
   else ManageDemoTarget();
   datetime now_open=iTime(_Symbol,PERIOD_M15,0);
   if(now_open<=0 || now_open==g_current_open) return;
   datetime prior_open=g_current_open;
   g_current_open=now_open;
   if(prior_open>0 && now_open-prior_open>STEP_SECONDS)
      Print("Terminal missed M15 boundaries; replaying indicators only until current closed bar");
   MqlRates missed[];
   ArraySetAsSeries(missed,false);
   int copied=CopyRates(_Symbol,PERIOD_M15,g_last_processed+STEP_SECONDS,
                        now_open-STEP_SECONDS,missed);
   if(copied<=0) return;
   for(int i=0;i<copied;i++)
      ProcessCompletedBar(missed[i],i==copied-1 && missed[i].time==now_open-STEP_SECONDS);
   if(InpMode==AUDIT_ONLY) AuditTick(tick); // first B+1 tick may trigger a new order
  }

bool EntryForPosition(ulong position_id,datetime &signal_candle,
                      datetime &fill_time,double &fill_price,double &stop)
  {
   signal_candle=0; fill_time=0; fill_price=0; stop=0;
   if(position_id==0 || !HistorySelect((datetime)0,TimeTradeServer())) return false;
   for(int i=0;i<HistoryDealsTotal();i++)
     {
      ulong deal=HistoryDealGetTicket(i);
      if(deal==0 || (ulong)HistoryDealGetInteger(deal,DEAL_POSITION_ID)!=position_id ||
         HistoryDealGetInteger(deal,DEAL_ENTRY)!=DEAL_ENTRY_IN ||
         HistoryDealGetString(deal,DEAL_SYMBOL)!=_Symbol ||
         (ulong)HistoryDealGetInteger(deal,DEAL_MAGIC)!=InpMagicNumber) continue;
      ulong order=(ulong)HistoryDealGetInteger(deal,DEAL_ORDER);
      fill_time=(datetime)HistoryDealGetInteger(deal,DEAL_TIME);
      fill_price=HistoryDealGetDouble(deal,DEAL_PRICE);
      if(!HistoryOrderSelect(order)) return false;
      string comment=HistoryOrderGetString(order,ORDER_COMMENT);
      if(StringFind(comment,"A1|")==0)
         signal_candle=(datetime)StringToInteger(StringSubstr(comment,3));
      stop=HistoryOrderGetDouble(order,ORDER_SL);
      return signal_candle>0 && stop>0;
     }
   return false;
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(InpMode!=DEMO_TRADE) return;
   if(trans.type==TRADE_TRANSACTION_HISTORY_ADD && trans.order!=0)
     {
      if(!HistoryOrderSelect(trans.order)) return;
      if(HistoryOrderGetString(trans.order,ORDER_SYMBOL)!=_Symbol ||
         (ulong)HistoryOrderGetInteger(trans.order,ORDER_MAGIC)!=InpMagicNumber) return;
      ENUM_ORDER_STATE state=(ENUM_ORDER_STATE)HistoryOrderGetInteger(trans.order,ORDER_STATE);
      if(state==ORDER_STATE_EXPIRED || state==ORDER_STATE_CANCELED)
        {
         string comment=HistoryOrderGetString(trans.order,ORDER_COMMENT);
         datetime sig=(StringFind(comment,"A1|")==0 ?
                       (datetime)StringToInteger(StringSubstr(comment,3)) : 0);
         ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)HistoryOrderGetInteger(trans.order,ORDER_TYPE);
         int direction=(type==ORDER_TYPE_BUY_STOP ? 1 : -1);
         LogRecord(state==ORDER_STATE_EXPIRED ? "ORDER_EXPIRED" : "ORDER_CANCELED",
                   (datetime)TimeTradeServer(),sig,direction,false,
                   "Broker order history state",0,
                   HistoryOrderGetDouble(trans.order,ORDER_PRICE_OPEN),
                   HistoryOrderGetDouble(trans.order,ORDER_SL),
                   HistoryOrderGetDouble(trans.order,ORDER_TP),0,0,
                   HistoryOrderGetDouble(trans.order,ORDER_VOLUME_INITIAL),0,
                   trans.order,0,0,0,0,0,0);
        }
      return;
     }
   if(trans.type!=TRADE_TRANSACTION_DEAL_ADD || trans.deal==0) return;
   if(!HistoryDealSelect(trans.deal)) return;
   if(HistoryDealGetString(trans.deal,DEAL_SYMBOL)!=_Symbol) return;
   ulong position_id=(ulong)HistoryDealGetInteger(trans.deal,DEAL_POSITION_ID);
   if((ulong)HistoryDealGetInteger(trans.deal,DEAL_MAGIC)!=InpMagicNumber)
     {
      datetime sig=0,fill=0; double price0=0,stop0=0;
      if(!EntryForPosition(position_id,sig,fill,price0,stop0)) return;
     }
   ulong order=(ulong)HistoryDealGetInteger(trans.deal,DEAL_ORDER);
   ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(trans.deal,DEAL_ENTRY);
   ENUM_DEAL_TYPE kind=(ENUM_DEAL_TYPE)HistoryDealGetInteger(trans.deal,DEAL_TYPE);
   ENUM_DEAL_REASON deal_reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(trans.deal,DEAL_REASON);
   int direction=(kind==DEAL_TYPE_BUY ? 1 : -1);
   if(entry==DEAL_ENTRY_OUT) direction=-direction;
   datetime when=(datetime)HistoryDealGetInteger(trans.deal,DEAL_TIME);
   double price=HistoryDealGetDouble(trans.deal,DEAL_PRICE);
   double pnl=HistoryDealGetDouble(trans.deal,DEAL_PROFIT)+
              HistoryDealGetDouble(trans.deal,DEAL_COMMISSION)+
              HistoryDealGetDouble(trans.deal,DEAL_SWAP);
   double volume=HistoryDealGetDouble(trans.deal,DEAL_VOLUME);
   datetime signal_candle=0,entry_time=0;
   double entry_price=0,structural_stop=0;
   bool found=EntryForPosition(position_id,signal_candle,entry_time,
                               entry_price,structural_stop);
   double initial_risk=(found ? MathAbs(entry_price-structural_stop)*volume : 0);
   double actual_target=(found ? entry_price+direction*REWARD*
                         MathAbs(entry_price-structural_stop) : 0);
   if(entry==DEAL_ENTRY_IN)
     {
      LogRecord("ORDER_FILLED",when,signal_candle,direction,true,
                "Broker execution; target set from actual fill on next tick",
                0,0,structural_stop,actual_target,0,0,volume,initial_risk,
                order,when,price,0,0,0,0);
      ManageDemoTarget();
     }
   else if(entry==DEAL_ENTRY_OUT)
     {
      string exit_reason=(deal_reason==DEAL_REASON_SL ? "STOP_LOSS" :
                          (deal_reason==DEAL_REASON_TP ? "TAKE_PROFIT" : "POSITION_CLOSED"));
      LogRecord(exit_reason,when,signal_candle,direction,true,"Broker deal",0,0,
                structural_stop,actual_target,0,0,volume,initial_risk,
                order,entry_time,entry_price,when,price,pnl,
                initial_risk>0 ? pnl/initial_risk : 0);
      RefreshOwnHistory(when);
     }
  }

void OnDeinit(const int reason)
  {
   PersistRisk();
   if(g_file!=INVALID_HANDLE) FileClose(g_file);
  }

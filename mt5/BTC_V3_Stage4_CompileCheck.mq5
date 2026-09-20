//+------------------------------------------------------------------+
//|  BTC_V3_Stage4_CompileCheck.mq5                                   |
//|                                                                   |
//|  Compile-only harness for the R4 Stage 4 demo execution layer.     |
//|                                                                   |
//|  WHY A SCRIPT, NOT AN EXPERT ADVISOR:                              |
//|  a script runs once when dropped on a chart and exits. It has no   |
//|  OnTick, cannot be left attached, and cannot act on a later bar.   |
//|  An EA harness could be forgotten on a chart; this cannot.         |
//|                                                                   |
//|  WHAT IT DOES: includes BTC_V3_Stage4_Demo.mqh so MetaEditor       |
//|  compiles every line of it, then calls the pure validation,        |
//|  normalisation and refusal paths and prints what they return.      |
//|                                                                   |
//|  WHAT IT DOES NOT DO: transmit. There is no OrderSend or           |
//|  OrderSendAsync here or in the included layer, and Stage4Transmit  |
//|  refuses unconditionally. The one call that touches MqlTradeRequest|
//|  is OrderCheck, which validates without sending, and it is behind  |
//|  an input that defaults to false.                                  |
//|                                                                   |
//|  It does not touch BTC_V3_Core_V1.mq5 and does not wire Stage 4    |
//|  into it. Stage 3 keeps running untouched.                         |
//+------------------------------------------------------------------+
#property copyright "R4 Stage 4 compile harness"
#property version   "1.00"
#property script_show_inputs
#property strict

//--- OrderCheck() validates margin and request validity without transmitting.
//--- Default false so the harness is pure computation unless asked otherwise.
input bool InpRunOrderCheck = false;

#include "BTC_V3_Stage4_Demo.mqh"

void OnStart()
  {
   Print("=== R4 Stage 4 compile harness — NO ORDER IS SENT ===");

   //--- 1. Gates. Deliberately given a configuration that must be refused, so
   //--- the refusal path is the one exercised.
   Stage4Config cfg;
   cfg.enabled            = false;              // not DEMO_EXECUTION
   cfg.expected_symbol    = "BTCUSDm";
   cfg.expected_broker    = "Exness Technologies Ltd";
   cfg.expected_server    = "Exness-MT5Trial5";
   cfg.stage3_certificate = "stage3_certificate.csv";
   cfg.operator_ack       = "";                 // no acknowledgement
   cfg.twin_build         = "compile-harness";
   cfg.max_spread_points  = 5000.0;
   cfg.risk_percent       = 0.25;
   cfg.max_leverage       = 1.0;
   cfg.deviation_points   = 50;

   Stage4Gate gate = Stage4EvaluateGates(cfg);
   Print("gates passed=",gate.passed," failed_code=",gate.failed_code,
         " detail=",gate.detail);
   if(gate.passed)
      Print("UNEXPECTED: gates passed in the compile harness. Investigate.");

   //--- 2. Normalisation and validation, pure computation.
   double price = Stage4NormalisePrice(100123.456);
   string reject = "";
   double volume = Stage4NormaliseVolume(0.12345,reject);
   Print("normalised price=",DoubleToString(price,2),
         "  volume=",DoubleToString(volume,4),"  reject=",reject);

   bool stops_ok = Stage4StopsAreValid(1,100000.0,99000.0,103000.0,reject);
   Print("stops valid(long)=",stops_ok," reject=",reject);
   stops_ok = Stage4StopsAreValid(1,100000.0,101000.0,103000.0,reject);
   Print("stops valid(inverted, expect false)=",stops_ok," reject=",reject);

   bool spread_ok = Stage4SpreadAcceptable(cfg,reject);
   Print("spread acceptable=",spread_ok," reject=",reject,
         "  live spread points=",(int)SymbolInfoInteger(_Symbol,SYMBOL_SPREAD));

   //--- 3. Retcode classification and retry policy.
   Print("retcode DONE -> ",Stage4ClassifyRetcode(TRADE_RETCODE_DONE));
   Print("retcode REQUOTE -> ",Stage4ClassifyRetcode(TRADE_RETCODE_REQUOTE),
         " retryable=",Stage4IsRetryable(Stage4ClassifyRetcode(TRADE_RETCODE_REQUOTE)));
   Print("retcode NO_MONEY -> ",Stage4ClassifyRetcode(TRADE_RETCODE_NO_MONEY),
         " retryable=",Stage4IsRetryable(Stage4ClassifyRetcode(TRADE_RETCODE_NO_MONEY)));
   Print("retcode INVALID_STOPS -> ",Stage4ClassifyRetcode(TRADE_RETCODE_INVALID_STOPS));

   //--- 4. Ownership and orphan detection, read-only over broker state.
   string tag = Stage4ClientTag("BTC_V3_A4_PULLBACK_LONG_FROZEN",TimeGMT());
   Print("client tag=",tag);
   Print("already submitted=",Stage4AlreadySubmitted(tag),
         "  orphans=",Stage4OrphanCount(tag));

   //--- 5. Request construction. Compiled always; executed only on request,
   //--- because it is the one path that builds an MqlTradeRequest.
   Stage4Order order;
   order.valid=false; order.reject_code="NOT_RUN"; order.reject_detail="";
   order.volume=0.0; order.price=0.0; order.sl=0.0; order.tp=0.0;
   order.direction=1; order.magic=STAGE4_MAGIC; order.client_tag=tag;
   if(InpRunOrderCheck)
     {
      double ask = SymbolInfoDouble(_Symbol,SYMBOL_ASK);
      if(ask>0.0)
         order = Stage4BuildOrder(cfg,1,ask*1.01,ask*0.99,ask*1.04,
                                  AccountInfoDouble(ACCOUNT_BALANCE),tag);
      Print("OrderCheck pre-flight: valid=",order.valid,
            " reject=",order.reject_code," detail=",order.reject_detail);
     }
   else
      Print("OrderCheck pre-flight skipped (InpRunOrderCheck=false).");

   //--- 6. The refusal path. This must always return false.
   string outcome = "";
   ulong ticket = 0;
   bool sent = Stage4Transmit(cfg,order,outcome,ticket);
   Print("Stage4Transmit returned ",sent," outcome=",outcome," ticket=",ticket);
   if(sent)
      Print("CRITICAL: Stage4Transmit returned true. It must never do so.");

   Print("=== harness complete — nothing was transmitted ===");
  }

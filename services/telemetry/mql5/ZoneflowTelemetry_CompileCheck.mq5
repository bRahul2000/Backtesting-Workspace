//+------------------------------------------------------------------+
//| ZoneflowTelemetry_CompileCheck.mq5 - SCRIPT (runs once, exits)   |
//|                                                                  |
//| Compiles every strategy-side hook in ZoneflowTelemetry.mqh and,  |
//| when run, writes a handful of clearly-labelled self-test events  |
//| under writer "selftest" (strategy_id "selftest"), which Zoneflow |
//| reconciliation never matches to a real strategy. It sends no      |
//| order: the MqlTradeRequest/Result below are filled by hand and    |
//| only passed to the telemetry functions.                           |
//+------------------------------------------------------------------+
#property script_show_inputs
#property strict

#include "ZoneflowTelemetry.mqh"

void OnStart()
  {
   ZfInit("selftest", "selftest", "compile-check", "", "strategy");
   ZfObject state;
   state.Str("note", "self-test \"quoted\" \\ backslash");
   state.Num("example_indicator", 1.2345, 4);
   ZfStrategySignal(_Symbol, 1, "buy", SymbolInfoDouble(_Symbol, SYMBOL_ASK), TimeTradeServer(), state.Json());
   MqlTradeRequest request;
   MqlTradeResult result;
   ZeroMemory(request);
   ZeroMemory(result);
   request.action = TRADE_ACTION_PENDING;
   request.symbol = _Symbol;
   request.magic = 1;
   request.type = ORDER_TYPE_BUY_STOP;
   request.volume = 0.01;
   request.price = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   result.retcode = TRADE_RETCODE_INVALID;          // hand-filled: nothing was sent
   result.comment = "self-test, not sent";
   ZfStrategyOrderRequested(request);
   ZfStrategyOrderResult(request, result, 0);
   ZfStrategyExitRequested(_Symbol, 1, 0, "self-test");
   ZfStrategyError(_Symbol, 1, 0, "self-test");
   PrintFormat("Zoneflow telemetry self-test: %I64d events written, %I64d failures, run %s",
               ZfEventsWritten(), ZfWriteFailures(), ZfRunId());
  }
//+------------------------------------------------------------------+

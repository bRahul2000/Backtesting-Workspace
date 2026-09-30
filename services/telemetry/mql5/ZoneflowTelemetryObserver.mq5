//+------------------------------------------------------------------+
//| ZoneflowTelemetryObserver.mq5 - Telemetry V1 broker-side observer |
//|                                                                  |
//| Attach to ANY chart in the terminal that runs the strategy EA.   |
//| It watches the account's trade transactions for the configured   |
//| magic numbers and writes raw facts to the telemetry spool:       |
//|   position_opened / position_closed  (every fill, from the deal) |
//|   order_accepted / order_cancelled / order_expired / order_rejected |
//|   position_modified (SL/TP changes), heartbeat every 60 s,       |
//|   broker_disconnect / broker_reconnect, ea_started / ea_stopped  |
//| and once per UTC day exports MT5's own deal/order history for    |
//| the previous day (the authority for daily reconciliation).       |
//|                                                                  |
//| IT CANNOT TRADE: no OrderSend, OrderSendAsync, CTrade, position  |
//| close or order modification exists in this program or its       |
//| include (a Zoneflow test enforces this). It never changes the    |
//| strategy EA, which keeps running exactly as before.              |
//+------------------------------------------------------------------+
#property copyright "Zoneflow"
#property version   "1.00"
#property strict

#include "ZoneflowObserverCore.mqh"

int  OnInit()                { return ObsInit(); }
void OnDeinit(const int reason) { ObsDeinit(reason); }
void OnTimer()               { ObsTimer(); }
void OnTick()                { }
void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request, const MqlTradeResult &result)
  {
   ObsTradeTransaction(trans, request, result);
  }
//+------------------------------------------------------------------+

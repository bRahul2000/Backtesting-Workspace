# Frozen Setup B cost audit

Baseline: 955 completed frozen trades. Entry and exit prices, quantities, and planned risk are held fixed in cost repricing.

- Commission: **0.05% per side**, entry notional `entry fill × BTC quantity`, exit notional `exit fill × BTC quantity`.
- Formula: `(entry fill × quantity + exit fill × quantity) × 0.0005`.
- Charged on entry and exit. No minimum commission.
- Slippage: **0%**. Engine can worsen entry and exit by a configured percent; current baseline has none.
- Spread: no separate spread model. Market OHLC candles do not represent bid/ask.
- Average entry notional: $3,903.94; median $3,439.77.
- Average round-trip commission: $3.90; median $3.44.
- Average commission as percentage of planned risk: 15.83%.
- Commission drag: 0.1583R/trade; slippage drag 0R/trade.

Cost scenarios reprice the same historical fills and exits. They do not resize positions or model a new spread. This isolates fees but is not an execution-quality forecast.

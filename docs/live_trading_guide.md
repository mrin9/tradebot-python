## Live Trading Guide

This guide explains how the **live trading engine** works and how to operate it safely. It focuses on the core engine, XTS sockets, and Mongo persistence.

---

## 1. Conceptual Overview

Live trading is powered by:

- **XTS sockets** for real‑time ticks.
- **`LiveTradeEngine`** in `packages/livetrade/live_trader.py`.
- **`FundManager`** in `packages/tradeflow/fund_manager.py` for decision‑making.
- **`PositionManager`** and `PaperTradingOrderManager` for risk control and PnL.
- **MongoDB** collections for:
  - `livetrade`: high‑level session summaries.
  - `papertrade`: detailed event stream for audit.

The core idea:

1. XTS sockets stream ticks into `LiveTradeEngine`.
2. `LiveTradeEngine` passes normalized data to `FundManager.on_tick_or_base_candle`.
3. `FundManager`:
   - Resamples candles.
   - Computes indicators.
   - Calls your Python strategy.
   - Executes entries/exits via `PositionManager`.
4. Events are logged and (optionally) persisted to Mongo.

---

## 2. Requirements & Setup

### 2.1 Environment

In `.env`:

```env
MARKET_API_KEY=your_market_api_key
MARKET_API_SECRET=your_market_api_secret
INTERACTIVE_API_KEY=your_interactive_api_key
INTERACTIVE_API_SECRET=your_interactive_api_secret

DB_NAME=tradebot
MONGODB_URI=mongodb://localhost:27017/
```

### 2.2 Database Preparation

- Ensure instrument master and recent history are up‑to‑date:

```bash
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "2dago|now"
```

- Ensure indexes exist:

```bash
python apps/cli/main.py ensure_indexes
```

### 2.3 Strategy Configuration

In the `strategy_indicator` collection:

- Each strategy document includes:
  - `strategyId` (e.g., `triple-confirmation`).
  - `indicators` array (indicator IDs, shorthand notation, instrument types).
  - `python_strategy_path` (e.g., `packages/tradeflow/python_strategies.py:TripleLockStrategy`).
  - Optional `tslIndicatorId` (e.g., `active-ema-5`).

Seed default strategies if needed:

```bash
python apps/cli/main.py seed_strategies
```

---

## 3. Running Live Trading

### 3.1 Direct CLI Command

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000-inr \
  --sl-pct 10.0 \
  --target-pct 10,20,30 \
  --tsl-pct 0.0 \
  --use-be \
  --tsl-id trade-ema-5 \
  --record-papertrade \
  --log-active-indicator \
  --debug
```

**Parameter semantics (engine view):**

- **`--strategy-id`**:
  - Fetches strategy config and indicator set from Mongo.
  - Determines which Python strategy implementation is loaded.
- **`--strike-selection`** (`ATM`, `ITM`, `OTM`):
  - Guides `DriftManager` and `ContractDiscoveryService` to pick the current tradable contract.
- **`--budget`**:
  - Initial capital (e.g., `200000-inr`) or fixed lot count (e.g., `10-lots`). Used to compute position size based on option price and lot size.
- **`--sl-pct`**:
  - Stop loss as a percentage of entry premium (e.g., 10.0 for 10%). Default: `10.0`.
- **`--target-pct`**:
  - Comma‑separated profit target percentages (e.g., `10,20,30`). Default: `10,20,30`.
- **`--tsl-pct`**:
  - Trailing stop loss percentage (e.g., 1.0 for 1%). Default: `0.0` (disabled).
- **`--tsl-id`**:
  - Indicator‑based trailing SL (e.g., `trade-ema-5`). Default: `trade-ema-5`.
- **`--use-be`**:
  - Move SL to entry price after first target is hit. Default: `True`.
- **`--record-papertrade`**:
  - Persist detailed trade lifecycle events to `papertrade` collection.
- **`--log-active-indicator`**:
  - Dump active instrument data (OHLC + Indicators) to a CSV file in `logs/diagnostics/` upon receiving an entry signal. Default is `True`.
- **`--debug`**:
  - More verbose socket and engine logs.

### 3.2 Interactive Live Trading via Menu

```bash
python apps/cli/main.py menu
```

Choose **Live Trading**:

1. Pick one of the enabled strategies from Mongo.
2. Enter budget, SL, target points.
3. CLI calls `live_trade(...)` under the hood with your inputs.

---

## 4. Engine Behavior in Live Mode

### 4.1 Warm‑Up Phase

On start, the engine:

1. Identifies current SPOT, CE, and PE instruments using `DriftManager`.
2. Uses `MarketHistoryService` to fetch a configurable number of warm‑up candles (based on `GLOBAL_WARMUP_CANDLES`).
3. Feeds historical candles into:
   - `CandleResampler` (to build initial higher‑timeframe candles).
   - `IndicatorCalculator` (to prime indicator values).

During warm‑up:

- Signals from the strategy are **ignored** (`meta-is-warming-up` flag set in indicator state).
- The goal is to ensure indicators are in a stable state before live decisions.

### 4.2 Live Tick Processing

For each incoming tick / base candle:

1. **Timestamp & instrument** are inspected; tick is tagged as SPOT or option (CE/PE/traded).
2. **PositionManager** is updated:
   - For the active traded symbol only.
   - Using trailing SL, BE rules, pyramiding, etc.
3. **CandleResampler** is updated:
   - All tracked instruments (SPOT, CE, PE, traded) receive ticks for resampling.
   - When SPOT higher‑timeframe candle closes:
     - Indicators are recalculated.
     - Strategy is executed.
4. **Strategy Output**:
   - `SignalType.LONG` / `SHORT`:
     - `FundManager` decides target contract ID (e.g., current ATM CE).
     - Uses latest tick or fallback price (`_get_fallback_option_price`).
     - Recalculates quantity based on capital and lot size.
     - Delegates to `PositionManager.on_signal`.
   - `SignalType.EXIT`:
     - Uses tick cache / history / last known price to exit.
   - `SignalType.NEUTRAL`:
     - No position changes.

### 4.3 EOD Settlement

At the configured EOD timestamp (typically `15:30 IST`):

- `LiveTradeEngine` calls `FundManager.handle_eod_settlement(...)`.
- Any open position is:
  - Closed using last known tick or position price.
  - Logged as an EOD exit via `trade_formatter`.
  - Persisted to Mongo.

---

## 5. Monitoring & Observability

### 5.1 Console Logs

Engine logs include:

- **Heartbeats** (optional):
  - When `log_heartbeat=True`, prints indicators snapshot each SPOT candle.
- **Signals**:
  - LONG / SHORT / EXIT with reasons and time window.
- **Trades**:
  - Entries, targets, SL/TSL hits, PnL.
- **Drift updates**:
  - Contract rollover and drift handling messages.

### 5.2 MongoDB Collections

Typical collections involved:

- `livetrade`:
  - High‑level summary per live session / strategy.
  - Session start/end, total PnL, high‑level stats.
- `papertrade`:
  - Fine‑grained events:
    - Entry, partial exits, targets, SL/TSL moves, EOD exits.
- `nifty_candle`, `options_candle`:
  - Historical data used for warm‑up and fallback.

Use MongoDB Compass or your preferred tool to inspect:

- `papertrade` for detailed audit trail.
- `livetrade` for aggregate results.

---

## 6. Safety Considerations

### 6.1 Dry‑Run in Paper Mode

The engine already logs detailed papertrade events. For an additional safety layer:

- Start with **small budget** and/or **papertrade only** (no actual orders).
- Verify:
  - Signals match expectations.
  - SL/TSL behavior under volatile conditions.
  - Drift handling (weekly expiry and ATM changes) works as intended.

### 6.2 Parameter Sanity

Before going live:

- Validate your config via **backtests** over multiple weeks.
- Avoid:
  - Zero or extremely tight SL/TSL that may cause over‑trading.
  - Budget so small that you cannot afford 1 lot at typical premiums.

### 6.3 Failover & Restarts

In case of process restart:

- Warm‑up will re‑load indicator state from history.
- Positions open at broker may not match in‑memory state.
  - The engine currently assumes it is the authority on positions.
  - Use conservative choices and consider manual reconciliation if needed.

---

## 7. Quick Start Checklist (Live)

- [ ] `.env` has valid XTS and Mongo credentials.
- [ ] `DB_NAME=tradebot` (or dedicated live DB).
- [ ] `update_master` & `sync_history` recently run.
- [ ] `seed_strategies` run and your strategy is enabled.
- [ ] Strategy behavior verified via backtests.
- [ ] CLI command chosen:

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000-inr \
  --sl-pct 10.0 \
  --target-pct 10,20,30 \
  --tsl-pct 0.0 \
  --use-be \
  --tsl-id trade-ema-5 \
  --record-papertrade \
  --debug
```

Monitor logs and Mongo collections during the session to ensure behavior matches expectations.


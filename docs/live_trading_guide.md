## Live Trading Guide

This guide explains how the **live trading engine** works and how to operate it safely. It focuses on the core engine, XTS sockets, order execution modes, and Mongo persistence.

---

## 1. Conceptual Overview

Live trading is powered by:

- **XTS sockets** for real‑time ticks.
- **`LiveTradeEngine`** in `packages/livetrade/live_trader.py`.
- **`FundManager`** in `packages/tradeflow/fund_manager.py` for decision‑making.
- **`PositionManager`** for risk control, SL/TSL/Targets and auto EOD square‑off.
- **`MockOrderManager`** (papertrading) **or** **`XTSOrderManager`** (live real money) for order execution.
- **MongoDB** collections for:
  - `livetrade`: high‑level session summaries.
  - `mock_api`: detailed event stream for papertrade audit.

The core idea:

1. XTS sockets stream ticks into `LiveTradeEngine`.
2. `LiveTradeEngine` passes normalized data to `FundManager.on_tick_or_base_candle`.
3. `FundManager`:
   - Resamples candles.
   - Computes indicators.
   - Calls your Python strategy.
   - Executes entries/exits via `PositionManager`.
4. `PositionManager` routes execution through either `MockOrderManager` (papertrade) or `XTSOrderManager` (live).
5. All events are logged and persisted to Mongo.

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

The key flag controlling execution mode is `--papertrade`:

| Flag | Order Manager | Real Orders? | Use Case |
|------|--------------|-------------|----------|
| `--papertrade` present | `MockOrderManager` | ❌ No | Simulation with live quotes |
| `--papertrade` absent | `XTSOrderManager` | ✅ Yes | Real money trading |

### 3.1 Paper Trade Mode (Simulated Orders)

Use `--papertrade` to run the engine on live XTS market data **without placing any real orders**. The system fires a real `get_quote` API call to get the true LTP at the moment of each simulated execution, then records the full mock order lifecycle to MongoDB.

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --use-be \
  --tsl-id trade-ema-5 \
  --papertrade
```

### 3.2 Live Trade Mode (Real Money)

Omitting `--papertrade` enables **real money mode**. The `XTSOrderManager` places actual `MARKET` orders via the XTS Interactive API and retrieves the true fill price via `get_order_history`.

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --use-be \
  --tsl-id trade-ema-5
```

> [!CAUTION]
> This places **real orders with real money**. Only use after validating the strategy in papertrade and mock mode first.

**Parameter semantics (engine view):**

- **`--strategy-id`**: Fetches strategy config and indicator set from Mongo.
- **`--strike-selection`** (`ATM`, `ITM-x`, `OTM-x`): Guides `ContractDiscoveryService` to pick the current tradable contract.
- **`--budget`**: Initial capital (e.g., `200000-inr`) or fixed lot count (e.g., `10-lots`). Used to compute position size.
- **`--sl-pct`**: Stop loss as a percentage of entry premium (e.g., 4.0 for 4%). Default: `4.0`.
- **`--target-pct`**: Comma‑separated profit target percentages (e.g., `"3"`). Default: `"3"`.
- **`--tsl-pct`**: Trailing stop loss percentage (e.g., 0.5 for 0.5%). Default: `0.5`.
- **`--tsl-id`**: Indicator‑based trailing SL (e.g., `trade-ema-5`). Default: `trade-ema-5`.
- **`--use-be`**: Move SL to entry price after first target is hit. Default: `True`.
- **`--papertrade`**: If present, simulates orders using `MockOrderManager` + live quotes. If absent, places real orders via `XTSOrderManager`.
- **`--log-active-indicator`**: Dump active instrument data (OHLC + Indicators) to a CSV file in `logs/diagnostics/` upon receiving an entry signal. Default: `True`.
- **`--debug`**: More verbose socket and engine logs.
- **`--mock`** (`-m`): Replay historical data from MongoDB via the embedded socket simulator instead of connecting to real XTS. Accepts a single date (`2026-04-10`) or a colon‑separated range (`2026-04-07:2026-04-10`).

### 3.3 Mock Mode Examples

Mock mode lets you validate the entire live trading pipeline against historical data without XTS credentials or market hours.

**Single day (papertrade):**

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --papertrade \
  --mock 2026-04-10
```

**Date range:**

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --papertrade \
  --mock 2025-04-07:2025-04-10
```

**How it works:**

1. `MockMarketService` (in `packages/services/mock_market.py`) replaces `LiveMarketService`.
2. It auto‑starts the `EmbeddedSimulator` on port 5050 (or connects if already running).
3. `SocketDataProvider` reads candles from MongoDB and replays them as XTS‑formatted `1501-json-full` socket events.
4. Real‑time EOD checks and health‑check reconnections are skipped; the simulator emits `simulation_complete` when done.

**When to use mock vs backtest:**

| Aspect | `--mock` (live‑trade) | `--mode socket` (backtest) |
|--------|----------------------|---------------------------|
| Code path | Full `LiveTradeEngine` pipeline | `BacktestEngine` wrapper |
| Event persistence | `livetrade` + `mock_api` collections | `backtest` collection |
| Session tracking | `TradeEventService` with live session ID | Backtest‑specific session ID |
| Use case | Validate live trading code end‑to‑end | Strategy PnL analysis |

### 3.4 Interactive Live Trading via Menu

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

### 4.3 EOD Safety Controls

The engine enforces three strict time‑based boundaries every trading session, configurable via `.env`:

| Setting | Default | Behaviour |
|---------|---------|-----------|
| `TRADE_EXPIRY_JUMP_CUTOFF` | `14:30:00` | On expiry day, switches execution from Current Week to Next Week contract to avoid Theta/Gamma explosions |
| `TRADE_LAST_ENTRY_TIME` | `15:00:00` | Blocks all **new** entries. Signal‑flip exits still work after this time |
| `TRADE_SQUARE_OFF_TIME` | `15:15:00` | Force‑closes all open positions at exactly this time with reason `EOD_SQUARE_OFF` |

> [!NOTE]
> **Why the expiry jump matters**: After `TRADE_EXPIRY_JUMP_CUTOFF`, `ContractDiscoveryService.resolve_option_contract` explicitly targetets the **Next Week** expiry for execution, while EMAs continue to be calculated on the Current Week contract. This prevents both stale pricing and rapid Theta decay that occurs in 0DTE options in the final hour. The log line `⏭️ Expiry Jump Triggered!` confirms when this rule activates.

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
- **EOD events**:
  - `🛑 Late Day Block` (entry blocked after `TRADE_LAST_ENTRY_TIME`).
  - `⏰ EOD SQUARE OFF Triggered` (forced flat at `TRADE_SQUARE_OFF_TIME`).
- **Drift updates**:
  - Contract rollover and drift handling messages.
  - `⏭️ Expiry Jump Triggered!` when switching to next week.

### 5.2 MongoDB Collections

Typical collections involved:

- `livetrade`:
  - High‑level summary per live session / strategy.
  - Session start/end, total PnL, high‑level stats.
- `mock_api`:
  - Fine‑grained events for both papertrade and real sessions (for audit trail):
    - Entry, partial exits, targets, SL/TSL moves, EOD exits.
- `nifty_candle`, `options_candle`:
  - Historical data used for warm‑up and fallback.

Use MongoDB Compass or your preferred tool to inspect:

- `mock_api` for detailed per-trade audit trail.
- `livetrade` for aggregate results.

---

## 6. Safety Considerations

### 6.1 Start in Papertrade Mode First

Before committing real capital:

1. Run with `--papertrade` for at least a few sessions.
2. Verify signals match expectations, SL/TSL fires correctly, and EOD square‑off works.
3. Then run `--papertrade --mock <date>` against historical data to batch‑validate.

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
- [ ] Validated with `--papertrade --mock <date>` first.
- [ ] CLI command chosen — **for real money**:

```bash
python apps/cli/main.py live-trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --use-be \
  --tsl-id trade-ema-5
```

Monitor logs and Mongo `livetrade` + `mock_api` collections during the session to ensure behavior matches expectations.

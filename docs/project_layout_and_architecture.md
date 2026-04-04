## Project Layout & Architecture

This document describes how the **core trading engine**, data layer, and services in `trade-bot-v2` are organized. It intentionally ignores the UI and HTTP API so you can focus on the parts that run strategies, backtests, and live trading.

---

## 1. High‑Level Overview

At a high level, the system is composed of:

- **CLI (`apps/cli`)**: Operational entry point for syncing data, running backtests, and starting live trading.
- **Core Engine (`packages/tradeflow`)**: Multi‑timeframe analysis (MTFA), indicator calculation, and order/position orchestration.
- **Domain Services (`packages/services`)**: Strategy configuration, market history, and contract discovery.
- **Data Layer (`packages/data`, `packages/db`, `packages/utils.mongo`)**: Historical data sync, master instruments, MongoDB abstraction.
- **Live Trading (`packages/livetrade`)**: Wraps the `FundManager` with XTS sockets and EOD handling.
- **Simulation / Backtest (`packages/simulator`, `tests/backtest`)**: High‑speed DB‑driven and high‑fidelity socket‑style backtests.

The **single source of truth** for trading logic is the `FundManager` in `packages/tradeflow/fund_manager.py`. Everything else is either feeding it data, persisting its decisions, or configuring how it should behave.

---

## 2. Directory Structure (Code‑Only)

```text
trade-bot-v2/
├── apps/
│   └── cli/
│       └── main.py           # Management CLI (sync, backtest, live trade, tests)
├── packages/
│   ├── settings.py           # Central configuration (env, DB names, collection suffixes, constants)
│   ├── data/                 # Historical data & instrument management
│   │   ├── age_out.py        # Prune old data
│   │   ├── contracts.py      # ContractManager – decide which contracts are “active”
│   │   ├── data_gaps.py      # Detect and repair gaps in historical data
│   │   ├── sync_history.py   # HistoricalDataCollector – sync NIFTY & options OHLC
│   │   └── sync_master.py    # MasterDataCollector – instrument master sync from XTS
│   ├── db/
│   │   ├── db_init.py        # DatabaseManager – indexes & base initialization
│   │   ├── seed_frozen_data.py
│   │   └── seed_strategy_indicators.py
│   ├── livetrade/
│   │   └── live_trader.py    # LiveTradeEngine – wraps FundManager + sockets + EOD
│   ├── services/
│   │   ├── backtest_engine.py      # Shared orchestration helpers for backtests
│   │   ├── contract_discovery.py   # ContractDiscoveryService – resolve ATM/rollovers
│   │   ├── live_market.py          # XTS socket glue for live mode
│   │   ├── market_history.py       # MarketHistoryService – DB/API historical candles
│   │   ├── trade_config_service.py # Strategy & position config builder/normalizer
│   │   └── trade_event.py          # Domain events (papertrade/live trade records)
│   ├── simulator/
│   │   ├── socket_data_provider.py # Feeds historical data over Socket.IO
│   │   └── socket_server.py        # Minimal Socket.IO server for backtest “socket mode”
│   ├── tradeflow/
│   │   ├── base_strategy.py        # Base Python strategy interface
│   │   ├── candle_resampler.py     # CandleResampler – 1m → N‑minute aggregation
│   │   ├── drift_manager.py        # DriftManager – handles weekly contract rollover / ATM tracking
│   │   ├── fund_manager.py         # FundManager – MTFA orchestrator
│   │   ├── indicator_calculator.py # IndicatorCalculator – Polars‑based indicators
│   │   ├── order_manager.py        # PaperTradingOrderManager – fills orders / PnL
│   │   ├── position_manager.py     # PositionManager – risk, SL/TSL/targets, pyramiding
│   │   ├── python_strategies.py    # Example concrete strategies (e.g., TripleLockStrategy)
│   │   ├── python_strategy_loader.py # PythonStrategy – dynamic import by “file:ClassName”
│   │   └── types.py                # Enums and shared type aliases
│   └── utils/
│       ├── date_utils.py     # Trading‑day calendars, timestamp conversions, date ranges
│       ├── log_utils.py      # Log formatting and logger setup
│       ├── mongo.py          # MongoRepository, suffix logic, DB helpers
│       ├── replay_utils.py   # Turn candles into virtual ticks for high‑fidelity backtests
│       ├── trade_formatter.py# Pretty console messages for signals / trades / heartbeats
│       └── trade_persistence.py # Save backtest and live session summaries
├── scripts/                  # One‑off utilities (e.g., crossover calculator)
└── tests/
    ├── no_db/                # Pure unit tests – no Mongo needed
    ├── backtest/             # Backtest runners & modes
    ├── readwrite_db/         # Tests that hit a test DB
    ├── frozen_db/            # Deterministic integration tests on seeded frozen DB
    └── xts/                  # XTS connectivity & normalization tests
```

---

## 3. Runtime Architecture

### 3.1 Core Trading Loop

The **core runtime** is the same for:

- High‑speed DB backtests
- High‑fidelity socket backtests
- Live trading with XTS sockets

Only the **data source** changes. In every mode:

1. **Market data (ticks or candles)** are received from:
   - DB cursor (`db_mode`)
   - Socket simulator (`socket_mode`)
   - XTS live sockets (`LiveTradeEngine`)
2. Data is passed into `FundManager.on_tick_or_base_candle(...)`.
3. `FundManager`:
   - Updates a **CandleResampler** per instrument (SPOT/CE/PE/traded contract).
   - Updates the **PositionManager** with every tick to maintain SL/TSL/targets.
   - On resampled candle close for SPOT:
     - Runs **IndicatorCalculator** for SPOT + CE + PE.
     - Generates a **signal** by calling the Python strategy (`PythonStrategy.on_resampled_candle_closed`).
     - Creates/updates a position via **PositionManager** (entry/exit, pyramiding).
     - Routes trade events to **PaperTradingOrderManager** and optional persistence.

`LiveTradeEngine` or the backtest runner then decide how to store the results (Mongo collections, frozen data, papertrade logs, etc.).

### 3.2 Configuration Flow

Strategy and engine behavior are configured via:

- **MongoDB Strategy Indicator**: Per‑strategy indicator definitions (`indicatorId`, `indicator`, `InstrumentType`).
- **`TradeConfigService`**:
  - Loads strategy config documents from Mongo (IDs like `triple-confirmation`).
  - Normalizes the document into:
    - `strategy_config` – timeframes, indicator specs, rule metadata.
    - `position_config` – budget, SL/TSL, target points, pyramiding, instrument type, `python_strategy_path`, etc.
- **`FundManager` constructor**:
  - Uses `TradeConfigService.normalize_strategy_config(...)`.
  - Uses `TradeConfigService.build_position_config(...)`.

The CLI (`apps/cli/main.py`) typically resolves a `strategy_id` via `TradeConfigService.fetch_strategy_config(...)` and passes the resulting `strategy_config` + `position_config` to `FundManager` or `LiveTradeEngine`.

---

## 4. Key Modules and Responsibilities

### 4.1 `FundManager` (`packages/tradeflow/fund_manager.py`)

**Role**: Orchestrator for MTFA. It wires together:

- **Contract discovery**: via `ContractDiscoveryService` + `DriftManager` to maintain current SPOT/CE/PE instruments.
- **Resampling**: per‑instrument **CandleResampler** instances.
- **Indicators**: **IndicatorCalculator** per strategy config.
- **Strategy logic**: dynamicaly imported via `PythonStrategy`.
- **Positions & orders**: **PositionManager** + `PaperTradingOrderManager`.

Key aspects:

- Maintains **latest tick prices** and uses fallbacks from `MarketHistoryService` when live ticks are missing.
- Supports **backtest** vs **live** modes by:
  - Switching price source (`open`/`close` vs `p`).
  - Exploding OHLC bars into **virtual ticks** in backtests (via `ReplayUtils`) to mimic real‑time trailing behavior.
- Handles **EOD settlement** (15:30 IST) via `handle_eod_settlement`.
- Maintains a **mapped indicator view**:
  - Raw SPOT indicators: `nifty-*`.
  - Current CE/PE indicators prefixed by `ce-*` / `pe-*`.
  - “Active” vs “Inverse” mappings based on long/short side (`active-*`, `inverse-*`).

This “mapped indicator” dictionary is exactly what Python strategies use to make decisions.

### 4.2 `IndicatorCalculator` (`packages/tradeflow/indicator_calculator.py`)

**Role**: Vectorized indicator engine powered by **Polars**.

- Maintains a **deque of candles per instrument**.
- On each new candle:
  - Builds a Polars `DataFrame` from the rolling window.
  - Evaluates indicators described by shorthand strings, for example:
    - `ema-5`, `sma-20`, `rsi-14`, `atr-14`, `supertrend-10-3`, `macd-12-26-9`, `bbands-20-2`, `vwap`, `obv`, `price`.
  - Writes indicator values back into the frame with keys like `fast_ema`, `bbands20-upper`, etc.
  - Extracts the latest and previous values into a flat dict keyed with prefixes per category:
    - `nifty-fast_ema`, `ce-supertrend-10-3-dir`, `pe-macd-12-26-9-hist-prev`, etc.

Strategies do not know about Polars or rolling windows; they just consume these flattened keys.

### 4.3 `CandleResampler` (`packages/tradeflow/candle_resampler.py`)

**Role**: Convert 1‑minute (or tick‑derived) candles into higher timeframes used by strategies.

- Maintains a **current candle** and **period start**.
- For each incoming candle (or tick turned into a 1‑min bar):
  - Calculates the period bucket using integer division by `interval_seconds`.
  - Aggregates open/high/low/close/volume until the bucket changes.
  - On bucket change:
    - Closes the existing candle (`is_final=True`).
    - Invokes `on_candle_closed(candle)` callback (usually in `FundManager`).

This isolates all “timeframe math” from the strategy and from the position manager.

### 4.4 `PositionManager` and `PaperTradingOrderManager`

**Role**: Encode risk logic and convert signals into fills and PnL.

- `PositionManager` is given:
  - Instrument kind (CASH/OPTIONS/FUTURES).
  - `sl_pct`, `target_pct`, `tsl_pct`, `pyramid_steps`, `pyramid_confirm_pts`.
  - `price_source` for backtests (`open`/`close`).
  - Optional `tsl_id` for **indicator‑driven trailing SL** (e.g. exit when `active-ema-5` is broken).
- It:
  - Creates and updates a single **current position** at a time.
  - Listens to ticks and indicator snapshots.
  - Decides when SL, TSL, targets, or BE are hit.
  - Emits structured trade events, handled by `PaperTradingOrderManager`.

`PaperTradingOrderManager` centralizes fills and PnL so that both backtests and live sessions can share the same accounting logic.

### 4.5 Python Strategies (`python_strategies.py` / `PythonStrategy`)

**Role**: Declarative trading rules that consume indicator state and emit signals.

- `PythonStrategy` dynamically loads a concrete class from a `file:ClassName` string stored in the DB (`python_strategy_path`).
- Strategies implement:
  - `on_resampled_candle_closed(candle, indicators, current_position_intent)` → `(SignalType, reason, confidence)`.
- The engine:
  - Interprets `SignalType.LONG`, `SignalType.SHORT`, `SignalType.EXIT`, and `SignalType.NEUTRAL`.
  - Handles continuity / flip / EOD logic around those signals.

---

## 5. CLI Integration

The CLI (`apps/cli/main.py`) is the main human‑facing interface for the engine:

- **Data maintenance**:
  - `update_master` – sync instrument master via `MasterDataCollector`.
  - `sync_history` – bulk NIFTY + options history via `HistoricalDataCollector`.
  - `age_out`, `check_gaps`, `fill_gaps` – manage DB size and data quality.
  - `refresh_contracts` – compute which contracts should be tracked.
- **Trading & backtests**:
  - `backtest` / `interactive_backtest` – interactive backtest launcher using `tests/backtest/backtest_runner`.
  - `live-trade` – start `LiveTradeEngine` for actual trading with XTS.
- **Support / safety**:
  - `ensure_indexes` – call `DatabaseManager.ensure_all_indexes`.
  - `seed_strategies` – populate `strategy_indicator` DB.
  - `menu` – interactive console that wraps the above operations.

For more operational detail, see `operational_guide.md`.

---

## 6. Extension Points

When extending the system:

- **New indicator**:
  - Add parsing and calculation logic to `IndicatorCalculator.calculate_indicator`.
  - Expose shorthand in DB configs (e.g., `indicator: "myind-10-3"`).
- **New strategy**:
  - Implement a new class in `python_strategies.py` or a new file.
  - Export a `file:ClassName` string and store it in the strategy config (`python_strategy_path`).
- **New data source**:
  - Implement a feeder that calls `FundManager.on_tick_or_base_candle(...)`.
  - Reuse existing `MarketHistoryService`, `DriftManager`, and `PositionManager` as needed.

This architecture keeps strategy logic thin and testable while making the engine reusable across live trading and backtesting.


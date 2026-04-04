## Operational Guide (Engine & CLI)

This guide explains how to work with the **core trading engine** and **CLI** for local development, backtesting, and live trading. It intentionally ignores the UI and HTTP API.

---

## 1. Environments & Prerequisites

- **Python**: 3.10+ (recommended 3.11)
- **MongoDB**: Local or remote instance reachable from your machine.
- **XTS Credentials** (for live trading):
  - Market and Interactive keys and secrets.

### 1.1 Environment Setup

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create and configure your environment file:

```bash
cp .env.example .env
# Edit .env with:
# - DB_NAME (e.g. tradebot, tradebot_test, tradebot_frozen)
# - Mongo connection URI
# - XTS credentials (for live trading)
```

---

## 2. Running the CLI

The CLI is the primary operational surface for the engine:

```bash
python apps/cli/main.py --help
```

### 2.1 Interactive Menu

For a guided workflow:

```bash
python apps/cli/main.py menu
```

You will see a menu with options like:

- **Update Master Instruments**
- **Sync History (Nifty and Options)**
- **Age Out History**
- **Check Data Gaps**
- **Fill Data Gaps**
- **Backtesting**
- **Live Trading**
- **Tests**
- **Configuration**
- **Refresh Active Contracts**
- **Seed Strategy Indicators**
- **EMA Crossover Analysis**
- **Ensure DB Indexes**

Use the arrow keys to navigate; each option maps to a CLI command documented below.

---

## 3. Data Management Operations (via CLI)

These commands operate on MongoDB and the historical data set.

### 3.1 Sync Instrument Master

Refresh internal instrument master from XTS:

```bash
python apps/cli/main.py update_master
```

Backed by `MasterDataCollector` in `packages/data/sync_master.py`.

### 3.2 Sync Historical OHLC (NIFTY + Options)

Bulk sync historical candles using `HistoricalDataCollector`:

```bash
# Default: last 2 days
python apps/cli/main.py sync_history

# Custom date range
python apps/cli/main.py sync_history --date-range "2024-01-01|2024-01-31"
python apps/cli/main.py sync_history --date-range "5dago|now"
```

### 3.3 Age‑Out Old Data

Prune older records to keep DB small:

```bash
python apps/cli/main.py age_out --days 60
```

You will be prompted for confirmation.

### 3.4 Check & Fill Data Gaps

Detect missing candles:

```bash
python apps/cli/main.py check_gaps --date-range "2dago|now"
```

Fill gaps found by the above:

```bash
python apps/cli/main.py fill_gaps --date-range "today"
```

For more detail on gap logic and collections, see `data_management.md`.

---

## 4. Backtesting Operations

Backtests ultimately run through `tests/backtest/backtest_runner.py`, but the recommended entry is via the CLI.

### 4.1 Direct Backtest Command

```bash
python apps/cli/main.py backtest \
  --strategy-id triple-confirmation \
  --start 2024-02-01 \
  --end 2024-02-02 \
  --mode db \
  --budget 200000-inr \
  --invest-mode compound \
  --sl-pct 10.0 \
  --target-pct 10,20,30 \
  --tsl-pct 0.0 \
  --strike-selection ATM
```

If you omit parameters, the CLI will prompt you:

- Strategy ID (pulled from `strategy_indicator` collection).
- Mode: `db` (fast, DB‑backed) or `socket` (high‑fidelity, socket style).
- Date range (pre‑filled with recent available trading days).
- Budget (e.g. `200000-inr` or `10-lots`), pyramiding, BE, SL/TSL, strike selection, targets.

Internally this builds a command that runs:

```bash
python -m tests.backtest.backtest_runner [...]
```

See `testing_guide.md` for more advanced usage and parameter reference.

### 4.2 Interactive Backtest

You can use a friendly wizard instead of a long command:

```bash
python apps/cli/main.py interactive_backtest
```

This simply calls `backtest()` with interactive prompts.

---

## 5. Live Trading Operations

Live trading is handled by `LiveTradeEngine` in `packages/livetrade/live-trader.py`, which wraps `FundManager` with XTS socket connections and EOD logic.

### 5.1 Prerequisites

- `.env` has valid XTS credentials (market & interactive).
- Instrument master and history are up to date:

```bash
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "2dago|now"
```

### 5.2 Direct Live Trade Command

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

Key parameters:

- `--strategy-id`: Strategy configuration ID in Mongo (includes indicators and `python_strategy_path`).
- `--budget`: Starting capital (e.g., `200000-inr`) or fixed lot count (e.g., `10-lots`).
- `--strike-selection`: `ATM`, `ITM-x`, or `OTM-x` (where x is the offset from ATM).
- `--sl-pct`, `--tsl-pct`, `--target-pct`: Risk profile in percentage of premium.
- `--tsl-id`: Indicator ID for trailing SL (e.g., `active-ema-5`).
- `--record-papertrade`: Persist detailed events to the `papertrade` collection.
- `--log-active-indicator`: Dump active instrument data to CSV on entry signal.

For a deeper conceptual explanation, see `live_trading_guide.md`.

### 5.3 Interactive Live Trading via Menu

```bash
python apps/cli/main.py menu
```

Then choose **Live Trading**:

1. Select an enabled strategy from `strategy_indicator`.
2. Specify budget, SL, and targets.
3. The CLI launches `live-trade` with those parameters.

---

## 6. Configuration & Environment Checks

From the menu, choose **Configuration** or call directly:

```bash
python apps/cli/main.py menu
```

Under **Configuration**:

- **Show Settings**: Print active settings (DB name, XTS root URL).
- **Environment Check**:
  - Verifies `.env` exists.
  - Ensures `logs/` directory is present.

You can also ensure DB indexes exist:

```bash
python apps/cli/main.py ensure_indexes
```

This calls `DatabaseManager.ensure_all_indexes()` in `packages/db/db_init.py`.

---

## 7. Quick Operational Checklist

- **First time on a new machine:**
  - [ ] Create virtualenv and install requirements.
  - [ ] Copy and edit `.env`.
  - [ ] Run `python apps/cli/main.py ensure_indexes`.
  - [ ] Run `python apps/cli/main.py seed_strategies`.
  - [ ] Run `python apps/cli/main.py update_master`.
  - [ ] Run `python apps/cli/main.py sync_history --date-range "5dago|now"`.

- **Before a backtest run:**
  - [ ] Ensure DB has enough history for your date range.
  - [ ] Confirm `DB_NAME=tradebot_test` or `tradebot_frozen` (never `tradebot` if you want isolation).

- **Before a live trading session:**
  - [ ] `DB_NAME=tradebot` (or dedicated live DB).
  - [ ] `.env` populated with XTS keys.
  - [ ] Recent history synced.
  - [ ] Dry‑run strategy via backtest for today’s data.


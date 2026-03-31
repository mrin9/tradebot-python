## CLI Cheat Sheet

This cheat sheet lists all **engine/CLI commands** with their options and defaults. Run any command with `--help` to see the authoritative Typer/Click help.

All commands below are invoked from the project root as:

```bash
python apps/cli/main.py <command> [options]
```

---

## 1. High‑Level Entrypoints

### 1.1 Interactive Menu

**Command**

```bash
python apps/cli/main.py menu
```

**Description**

- Interactive text UI that wraps most operations:
  - Update master instruments
  - Sync history
  - Age‑out history
  - Check/fill data gaps
  - Backtesting (wizard)
  - Live trading (wizard)
  - Tests menu
  - Configuration checks
  - Refresh active contracts
  - Seed strategy indicators
  - EMA crossover analysis
  - Ensure DB indexes

**Notes**

- Uses `questionary` prompts.
- Ideal starting point when you’re not sure which command to run.

### 1.2 Interactive Backtest

**Command**

```bash
python apps/cli/main.py interactive_backtest
```

**Description**

- Shortcut to `backtest()` with a guided series of prompts for all parameters.

---

## 2. Data & Maintenance Commands

### 2.1 Ensure DB Indexes

**Command**

```bash
python apps/cli/main.py ensure_indexes
```

**Description**

- Verifies and creates all necessary MongoDB indexes via `DatabaseManager.ensure_all_indexes()`.

**Options**

- None.

### 2.2 Update Instrument Master

**Command**

```bash
python apps/cli/main.py update_master
```

**Description**

- Syncs `instrument_master` from XTS via `MasterDataCollector`.

**Options**

- None.

### 2.3 Sync Historical OHLC Data

**Command**

```bash
python apps/cli/main.py sync_history [--date-range TEXT]
```

**Options & Defaults**

- `--date-range TEXT`
  - Default: `"2dago|now"`
  - Help: `Date range (e.g., 2dago|now or YYYY-MM-DD|YYYY-MM-DD)`

**Description**

- Performs a bulk sync of historical OHLC data for NIFTY and all active options.

### 2.4 Age‑Out Old Data

**Command**

```bash
python apps/cli/main.py age_out [--days INT]
```

**Options & Defaults**

- `--days INT`
  - Default: `60`
  - Help: `Delete tick data older than X days`

**Description**

- Deletes data older than the given number of days after a confirmation prompt.

### 2.5 Check Data Gaps

**Command**

```bash
python apps/cli/main.py check_gaps [--date-range TEXT]
```

**Options & Defaults**

- `--date-range TEXT`
  - Default: `"2dago|now"`
  - Help: `Date Range for Gap Check`

**Description**

- Identifies missing ranges in NIFTY/options history between the given dates.

### 2.6 Fill Data Gaps

**Command**

```bash
python apps/cli/main.py fill_gaps [--date-range TEXT]
```

**Options & Defaults**

- `--date-range TEXT`
  - Default: `"today"`
  - Help: `Date Range to fill gaps`

**Description**

- Fetches and repairs missing data identified by gap checks.

### 2.7 Refresh Active Contracts

**Command**

```bash
python apps/cli/main.py refresh_contracts [--date-range TEXT]
```

**Options & Defaults**

- `--date-range TEXT`
  - Default: `"today"`
  - Help: `Date Range (today, yesterday, or YYYY-MM-DD)`

**Description**

- Recomputes which ATM/ITM/OTM contracts should be tracked for the given date.

### 2.8 Seed Strategy Indicators

**Command**

```bash
python apps/cli/main.py seed_strategies
```

**Description**

- Seeds the `strategy_indicator` collection with predefined strategy configs.

**Options**

- None.

---

## 3. Analysis & Utility Commands

### 3.1 EMA Crossover / Indicator Analysis

**Command**

```bash
python apps/cli/main.py crossover \
  [--instrument TEXT] \
  [--date TEXT] \
  [--crossover TEXT] \
  [--timeframe INT]
```

**Options & Defaults**

- `--instrument TEXT`
  - Default: `""`
  - Help: `Instrument description (e.g., NIFTY2630225400CE)`
- `--date TEXT`
  - Default: `None`
  - Help: `ISO Date (YYYY-MM-DD)`
- `--crossover TEXT`
  - Default: `"EMA-5-21"`
  - Help: `Crossover (e.g., EMA-5-21)`
- `--timeframe INT`
  - Default: `180`
  - Help: `Timeframe in seconds`

**Description**

- Runs `scripts/crossover_calculator.py` to calculate EMA crossovers and compare CE/PE.

---

## 4. Backtesting Commands

### 4.1 Backtest (CLI‑Driven)

**Command**

```bash
python apps/cli/main.py backtest \
  [--strategy-id TEXT] \
  [--start TEXT] \
  [--end TEXT] \
  [--mode TEXT] \
  [--budget TEXT] \
  [--invest-mode TEXT] \
  [--sl-points FLOAT] \
  [--use-be / --no-use-be] \
  [--tsl-points FLOAT] \
  [--strike-selection TEXT] \
  [--pyramid-steps TEXT] \
  [--pyramid-confirm-pts FLOAT] \
  [--target-points TEXT]
```

**Options & Defaults (from function signature)**

- `--strategy-id, -s TEXT`
  - Default: `"triple-confirmation"`
  - Interactive override: if omitted or `"SKIP"`, you get a prompt listing enabled strategies.
- `--start TEXT`
  - Default: `None`
  - Interactive prompt if not provided.
- `--end TEXT`
  - Default: `None`
  - Interactive prompt if not provided; defaults to `--start` if you choose “Manual”.
- `--mode TEXT`
  - Default: `None`
  - Prompted as `"db"` or `"socket"` if not provided.
- `--budget, -b TEXT`
  - Default: `"200000-inr"`
  - Help: `Initial Capital (e.g. 200000-inr or 10-lots)`
  - Prompted; default in prompt is `settings.TRADE_BUDGET`.
- `--invest-mode, -i TEXT`
  - Default: `None`
  - Prompted as `"fixed"` or `"compound"` if not provided.
- `--sl-points, -l FLOAT`
  - Default: `None`
  - Prompted; default `"15"` if omitted.
- `--use-be, -e`
  - Default: `None`
  - Prompted as `"Yes"`/`"No"`; interpreted as boolean.
- `--tsl-points, -L FLOAT`
  - Default: `0.0`
  - If left as `None` via interactive prompt, can be used with indicator‑based or point‑based TSL.
- `--strike-selection, -S TEXT`
  - Default: `None`
  - Help: `Option Strike Type (ATM, ITM-x, OTM-x where x is offset)`
  - Prompted as `"ATM"`, `"ITM-x"`, `"OTM-x"` if not provided.
- `--pyramid-steps TEXT`
  - Default: `None`
  - Prompted: `"25,50,25"` or `"100"` depending on whether you enable pyramiding.
- `--pyramid-confirm-pts FLOAT`
  - Default: `None`
  - Prompted; default `"10"` when pyramiding is enabled.
- `--target-points, -t TEXT`
  - Default: `None`
  - Prompted; default `"15,25,50"` if omitted.

**Description**

- Launches an **interactive** backtest workflow that ultimately runs `tests.backtest.backtest_runner` with the selected parameters.

---

## 5. Live Trading Command

### 5.1 Live Trade

**Command**

```bash
python apps/cli/main.py live_trade \
  [--strategy-id TEXT] \
  [--strike-selection TEXT] \
  [--budget TEXT] \
  [--sl-points FLOAT] \
  [--target-points TEXT] \
  [--tsl-points FLOAT] \
  [--use-be / --no-use-be] \
  [--tsl-id TEXT] \
  [--record-papertrade / --no-record-papertrade] \
  [--debug / --no-debug]
```

**Options & Defaults**

- `--strategy-id, -s TEXT`
  - Default: `"triple-confirmation"`
  - Strategy ID used to load indicators and Python strategy path.
- `--strike-selection, -S TEXT`
  - Default: `"ATM"`
  - Support for `ATM`, `ITM-x`, `OTM-x` (where x is the offset).
- `--budget, -b TEXT`
  - Default: `"200000-inr"`
- `--sl-points, -l FLOAT`
  - Default: `15.0`
- `--target-points, -t TEXT`
  - Default: `"15,25,45"`
- `--tsl-points, -L FLOAT`
  - Default: `0.0`
- `--use-be, -e / --no-use-be`
  - Default: `True`
- `--tsl-id, -T TEXT`
  - Default: `"active-ema-5"`
- `--record-papertrade / --no-record-papertrade`
  - Default: `True`
- `--debug / --no-debug`
  - Default: `False`

**Description**

- Starts the `LiveTradeEngine` for real‑time trading using XTS sockets and the configured strategy.

---

## 6. Testing Helpers (via Menu)

Tests are primarily run via `pytest`, but the `menu` command exposes a few shortcuts:

- **Unit Tests**:
  - Collectors → `tests/readwrite_db/test_collectors.py`
  - Fund Manager → (read/write or frozen DB tests)
  - Position Manager → `tests/no_db/test_position_manager.py`
  - Indicator Calculator → `tests/no_db/test_indicator_calculator.py`
  - Strategy Integration → `tests/frozen_db/test_strategy_integration.py`
  - Candle Resampler → `tests/no_db/test_candle_resampler.py`

- **Integration Tests**:
  - Full Strategy Flow → `tests/frozen_db/test_strategy_integration.py`
  - Market Utils → `tests/no_db/test_rolling_strikes.py`

- **Connectivity** (if present):
  - XTS API Connection
  - Market Stream Test

Use the `Tests` submenu in `python apps/cli/main.py menu` when you want guided, curated test runs.

---

## 7. API & UI Commands

Commands for running the optional web interface and API layer.

### 7.1 Run API Server (FastAPI)

**Command**

```bash
# Using Makefile shortcut
make api

# Or manually from root
python -m apps.api.run
```

**Description**

- Starts the FastAPI/Uvicorn server for strategy monitoring and data access.
- **Port**: 8000
- **Log Level**: Info (by default)

### 7.2 Run UI Dashboard (Nuxt)

**Command**

```bash
cd apps/ui
npm run dev
```

**Description**

- Starts the Nuxt.js development server for the trading dashboard.
- **Port**: 3000
- **Requirements**: Node.js and `npm install` (first-time only)


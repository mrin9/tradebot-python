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
  [--sl-pct FLOAT] \
  [--use-be / --no-use-be] \
  [--tsl-pct FLOAT] \
  [--strike-selection TEXT] \
  [--pyramid-steps TEXT] \
  [--pyramid-confirm-pts FLOAT] \
  [--target-pct TEXT]
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
- `--sl-pct, -l FLOAT`
  - Default: `None`
  - Default: `10.0`. Stop loss as a percentage of entry premium.
- `--use-be, -e`
  - Default: `None`
  - Prompted as `"Yes"`/`"No"`; interpreted as boolean.
- `--tsl-pct, -L FLOAT`
  - Default: `0.0`
  - Trailing stop loss percentage. Set to 0 to disable.
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
- `--target-pct, -t TEXT`
  - Default: `None`
  - Default: `"10,20,30"`. Comma-separated target percentages.

**Description**

- Launches an **interactive** backtest workflow that ultimately runs `tests.backtest.backtest_runner` with the selected parameters.

---

## 5. Live Trading Command

### 5.1 Live Trade

**Command**

```bash
python apps/cli/main.py live-trade \
  [--strategy-id TEXT] \
  [--strike-selection TEXT] \
  [--budget TEXT] \
  [--sl-pct FLOAT] \
  [--target-pct TEXT] \
  [--tsl-pct FLOAT] \
  [--use-be / --no-use-be] \
  [--tsl-id TEXT] \
  [--papertrade] \
  [--debug / --no-debug] \
  [--log-active-indicator / --no-log-active-indicator] \
  [--mock TEXT]
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
- `--sl-pct, -l FLOAT`
  - Default: `4.0`
- `--target-pct, -t TEXT`
  - Default: `"3"`
- `--tsl-pct, -L FLOAT`
  - Default: `0.5`
- `--use-be, -e / --no-use-be`
  - Default: `True`
- `--tsl-id, -T TEXT`
  - Default: `"trade-ema-5"`
- `--papertrade`
  - Boolean flag. If present, uses `MockOrderManager` (simulated orders with live quotes). If absent, uses `XTSOrderManager` (real money MARKET orders).
  - Default: absent (real money mode).
- `--debug / --no-debug`
  - Default: `False`
- `--log-active-indicator / --no-log-active-indicator`
  - Default: `True`
  - Dump active instrument data to CSV on entry signal.
- `--mock, -m TEXT`
  - Default: `None`
  - Replay historical data via the embedded socket simulator instead of real XTS.
  - Single date: `--mock 2026-04-10`
  - Date range: `--mock 2026-04-07:2026-04-10`

**Order Manager Selection**

| Flag | Manager | Orders |
|------|---------|--------|
| `--papertrade` | `MockOrderManager` | Simulated, live quote price |
| *(absent)* | `XTSOrderManager` | Real MARKET orders |

**EOD Controls (Configurable in `.env`)**

| Setting | Default | Effect |
|---------|---------|--------|
| `TRADE_EXPIRY_JUMP_CUTOFF` | `14:30:00` | Switch to Next Week contract on expiry day |
| `TRADE_LAST_ENTRY_TIME` | `15:00:00` | Block new entries after this time |
| `TRADE_SQUARE_OFF_TIME` | `15:15:00` | Force-close all open positions |

**Description**

- Starts the `LiveTradeEngine` for real-time trading using XTS sockets and the configured strategy.

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


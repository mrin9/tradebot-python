## Data Management Guide

This document explains how historical and live data is organized, how gaps are detected and repaired, and how to keep the MongoDB footprint under control.

---

## 1. Data Model Overview

### 1.1 Core Collections

The engine primarily works with the following logical collections (suffixes omitted):

- **Instrument & Reference**
  - `instrument_master`: Metadata for all tradable instruments (IDs, symbols, lot sizes, expiries).
- **Historical Candles**
  - `nifty_candle`: Spot index OHLCV.
  - `options_candle`: Options OHLCV (current and historical contracts).
- **Trading & Analytics**
  - `backtest`: Stored backtest summaries for later analysis.
  - `papertrade`: Fine‑grained trade events (used by backtests and live sessions).
  - `livetrade`: High‑level live session summaries.
- **Configuration**
  - `strategy_indicator`: Strategy definitions and indicator configs.

Collection names are dynamically suffixed based on `DB_NAME` (e.g., `_test`, `_frozen`) using logic in `packages/settings.py` and `packages/utils.mongo.py`.

### 1.2 Database Names & Suffixes

Recommended mapping:

| DB Name           | Suffix     | Example Collection          | Use Case                  |
|-------------------|------------|-----------------------------|---------------------------|
| `tradebot`        | (none)     | `nifty_candle`             | Live & primary history    |
| `tradebot_test`   | `_test`    | `nifty_candle_test`        | Development / integration |
| `tradebot_frozen` | `_frozen`  | `nifty_candle_frozen`      | Frozen snapshot for tests |

---

## 2. Master Data & Contract Discovery

### 2.1 Instrument Master

The master data is loaded from XTS and stored in `instrument_master`:

- **CLI command**:

```bash
python apps/cli/main.py update_master
```

Backed by `MasterDataCollector` in `packages/data/sync_master.py`.

### 2.2 Active Contracts

`ContractManager` (`packages/data/contracts.py`) and `ContractDiscoveryService`:

- Decide which contracts should be considered **active** (e.g., current weekly/monthly options for NIFTY).
- Refresh active contracts periodically or for a given date:

```bash
python apps/cli/main.py refresh_contracts --date-range today
```

This ensures the engine and backtester use the correct symbol IDs for SPOT, CE, PE, and any shifted contracts.

---

## 3. Historical Data Sync

### 3.1 HistoricalDataCollector

`HistoricalDataCollector` in `packages/data/sync_history.py` fetches and stores historical OHLC data for NIFTY and active options.

- **CLI entry**:

```bash
python apps/cli/main.py sync_history --date-range "2dago|now"
```

Supported formats for `--date-range` (parsed by `DateUtils.parse_date_range`):

- `"5dago|now"`
- `"2024-01-01|2024-01-10"`
- `"today|today"`

The collector:

- Queries instrument master to find relevant symbols.
- Calls XTS history endpoints (or uses cached data when available).
- Inserts or upserts candles into:
  - `nifty_candle[_suffix]`
  - `options_candle[_suffix]`

### 3.2 Usage in Engine & Backtests

`MarketHistoryService` (`packages/services/market_history.py`) uses these collections to:

- Run warm‑up for `FundManager` (before live or backtests).
- Provide fallback prices when live ticks are missing (e.g., `_get_fallback_option_price` in `FundManager`).

---

## 4. Gap Detection & Repair

### 4.1 Gap Checking

`packages/data/data_gaps.py` contains logic to:

- Compare expected vs actual data per trading day and timeframe.
- Detect missing candles or sessions.

Run via CLI:

```bash
python apps/cli/main.py check_gaps --date-range "2024-01-01|2024-01-10"
```

The gap checker typically:

- Uses calendar utilities from `DateUtils`.
- Expects a specific candle frequency (e.g., 1‑minute).
- Produces a report (logs and/or documents) about missing ranges.

### 4.2 Gap Filling

`fill_data_gaps` in `packages/data/data_gaps.py`:

- Re‑queries XTS or another source for missing periods.
- Inserts the missing candles into the appropriate collections.

CLI:

```bash
python apps/cli/main.py fill_gaps --date-range "today"
```

This closes gaps found by the previous step and ensures strategy results are based on complete data.

---

## 5. Aging Out Old Data

### 5.1 Rationale

Historical tick and 1‑minute data can grow quickly. To keep the DB responsive and cost‑effective:

- Use **age‑out** operations to delete data older than `N` days.

### 5.2 Age‑Out Task

`age_out_history` in `packages/data/age_out.py`:

- Deletes old data beyond a cutoff date (e.g., 60 days).
- Targets specific high‑volume collections (ticks, raw candles).

CLI:

```bash
python apps/cli/main.py age_out --days 60
```

You will be prompted:

- `Are you sure you want to delete data older than X days?`

This is a destructive operation – confirm carefully and ensure you are targeting the correct DB (`DB_NAME`).

---

## 6. Frozen Data for Deterministic Tests

### 6.1 Frozen DB

The **frozen DB** (`tradebot_frozen`) is:

- A curated snapshot of candles and trades used to:
  - Run deterministic test suites.
  - Validate engine behavior remains unchanged across refactors.

Collections:

- `nifty_candle_frozen`
- `options_candle_frozen`
- and others required by tests in `tests/frozen_db/`.

### 6.2 Seeding Frozen Data

Use `packages/db/seed_frozen_data.py`:

```bash
python packages/db/seed_frozen_data.py
```

Or in Docker:

```bash
docker compose exec api python packages/db/seed_frozen_data.py
```

Make sure:

- `DB_NAME=tradebot_frozen` when seeding and running frozen tests.

---

## 7. Data Usage in the Engine

### 7.1 Warm‑up & Historical Windows

`FundManager` uses `MarketHistoryService` to:

- Fetch recent candles for SPOT and active option instruments.
- Populate:
  - `CandleResampler` windows for the global timeframe.
  - `IndicatorCalculator` deques for each instrument/category.

This ensures indicators are stable before the first live tick or backtest candle is processed.

### 7.2 Fallback Logic

When a tick is missing (common in live environments):

- `FundManager._get_fallback_option_price`:
  1. Looks up last tick in `latest_tick_prices`.
  2. Queries `MarketHistoryService.fetch_historical_candles` for nearest prior candle.
  3. As a last resort, uses:
     - Position’s last known price (for exits).
     - Entry price as an extreme fallback.

This reduces the chance of hanging exits when the latest tick is not available.

---

## 8. Operational Checklists

### 8.1 Before Backtesting

- [ ] Ensure `DB_NAME` points to a test or frozen DB (`tradebot_test` or `tradebot_frozen`).
- [ ] Run:

```bash
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "5dago|now"
python apps/cli/main.py check_gaps --date-range "5dago|now"
python apps/cli/main.py fill_gaps --date-range "5dago|now"
```

- [ ] Confirm you have data in `nifty_candle[_suffix]` and `options_candle[_suffix]` for your backtest range.

### 8.2 Before Live Trading

- [ ] `DB_NAME=tradebot`.
- [ ] Run at least:

```bash
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "2dago|now"
python apps/cli/main.py check_gaps --date-range "2dago|now"
```

- [ ] Fix any critical gaps in today’s session before starting the engine.


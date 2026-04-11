## Testing & Backtest Guide

This guide describes how testing is organized around the core engine and how to use the backtest infrastructure to validate strategies and data quality.

---

## 1. Testing Philosophy

The project uses **pytest** with several layers of tests:

- **Unit tests (no DB)**: Pure Python behavior in isolation.
- **Read/Write DB tests**: Interact with a temporary DB for collectors and services.
- **Frozen DB tests**: Deterministic integration tests, seeded from a known snapshot.
- **XTS tests**: Connectivity and normalization for live market integration.
- **Backtest runners**: End‑to‑end tests that simulate complete trading sessions.

All tests live under `tests/`.

---

## 2. Test Layout

```text
tests/
├── no_db/          # Pure unit tests – no Mongo required
├── backtest/       # Backtest runners and modes
├── readwrite_db/   # Tests that write to a test DB
├── frozen_db/      # Deterministic end‑to‑end tests on seeded data
└── xts/            # XTS connectivity & stream tests
```

### 2.1 No‑DB Tests

Located in `tests/no_db/`, these cover:

- `test_candle_resampler.py`
- `test_position_manager.py`
- `test_engine_flow.py`
- `test_data_gaps_logic.py`
- `test_strategies_logic.py`
- `test_indicator_prefix_mapping.py`
- Strategy/domain logic that can run without a DB.

They are fast and safe to run anytime.

### 2.2 Read/Write DB Tests

Located in `tests/readwrite_db/`, using a **test DB**:

- Example: `test_collectors.py` for data collectors.
- Use `DB_NAME=tradebot_test` so that collections are suffixed with `_test`.

### 2.3 Frozen DB Tests

Located in `tests/frozen_db/`, backed by snapshot data:

- Example: `test_engine_pipeline.py`, `test_signal_orchestration.py`, `audit_golden_copy.py`.
- Use `DB_NAME=tradebot_frozen` and seed via `packages/db/seed_frozen_data.py`.

These tests guarantee deterministic behavior across runs.

### 2.4 XTS Tests

Located in `tests/xts/`:

- Validate:
  - Socket connectivity.
  - Epoch/timestamp shifts.
  - Data normalization.

Some are marked as **live** and require real credentials and market hours; others can be run offline with mocks.

---

## 3. Running Tests

From the project root:

```bash
pytest tests/
```

Verbose:

```bash
pytest -v tests/
```

### 3.1 Run Specific Files or Tests

Single file:

```bash
pytest tests/no_db/test_candle_resampler.py
```

Specific test case:

```bash
pytest tests/no_db/test_position_manager.py::TestPositionManager::test_basic_entry_exit
```

### 3.2 XTS Test Selection

If XTS tests are organized with markers (e.g., `live`), you can use:

```bash
# Non-live XTS tests (offline)
pytest tests/xts/ -m "not live"

# Live XTS tests
pytest tests/xts/ -m "live"
```

Check markers and available tests with:

```bash
pytest tests/xts/ --maxfail=1 -q
```

---

## 4. Database Namespacing & Safety

The engine uses:

- `DB_NAME` to select which database to connect to.
- Collection suffix logic in `packages/settings.py` and `packages/utils.mongo`.

Recommended mapping:

| Environment | DB Name           | Suffix     | Purpose                                   |
|------------|-------------------|------------|-------------------------------------------|
| Live       | `tradebot`        | (none)     | Real trading & live history               |
| Test       | `tradebot_test`   | `_test`    | Default DB for dev/test tasks             |
| Frozen     | `tradebot_frozen` | `_frozen`  | Deterministic integration & golden tests  |

Ensure `DB_NAME` is **not** pointing to `tradebot` when running tests unless you explicitly want to test against live data (generally not recommended).

---

## 5. Backtesting Framework

The backtest framework is a key part of testing:

- It reuses the **same `FundManager`, `PositionManager`, and strategies** used in live trading.
- It differs only in **how data is fed** to the engine and **which DB** is used.

### 5.1 Backtest Runner

Entry module:

```bash
python -m tests.backtest.backtest_runner --help
```

Two main modes:

- **DB mode (`--mode db`)**:
  - Reads historical candles from MongoDB.
  - Fast; good for iteration.
- **Socket mode (`--mode socket`)**:
  - Uses `packages/simulator/socket_server.py` to send data via Socket.IO.
  - High‑fidelity; mimics live tick stream.

### 5.2 Key Parameters

| Parameter | Default (if omitted) | Description |
|-----------|----------------------|-------------|
| `--mode` | `db` | Backtest source: `db` or `socket` |
| `--start` | (none) | Start date (YYYY-MM-DD) |
| `--end` | (same as start) | End date (YYYY-MM-DD) |
| `--strategy-id` | `triple-confirmation` | Strategy identifier from DB |
| `--sl-pct` | `4.0` | Stop loss percentage |
| `--target-pct` | `"3"` | Comma-separated target percentages |
| `--tsl-pct` | `0.5` | Trailing stop loss percentage (0 to disable) |
| `--invest-mode` | (prompted) | Investment mode: `fixed` or `compound` |
| `--verbose` | `false` | Enable verbose indicator/price logs |

Both modes:

- Build a `FundManager` with the same strategy and position configs.
- Use `ReplayUtils` to explode candles into virtual ticks when necessary.
- Persist results to `backtest` and papertrade‑style collections for analysis.

### 5.2 Example DB‑Mode Command

```bash
python -m tests.backtest.backtest_runner \
  --mode db \
  --start 2026-03-19 \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --invest-mode compound \
  --verbose
```

### 5.3 Example Socket‑Mode Command

```bash
python -m tests.backtest.backtest_runner \
  --mode socket \
  --start 2024-02-02 \
  --end 2024-02-02 \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --strike-selection ATM
```

If the socket simulator is not running, the runner can auto‑start it using `packages/simulator/socket_server.py`.

---

## 6. Using the CLI to Run Tests

For convenience, the CLI exposes a **Tests menu**:

```bash
python apps/cli/main.py menu
```

Choose **Tests**, then:

- **Unit Tests**:
  - Collectors, Fund Manager, Position Manager, Indicator Calculator, Strategy Integration, Candle Resampler.
- **Integration Tests**:
  - Full strategy flow, market utilities (e.g., rolling strikes).
- **Connectivity**:
  - XTS API connection, Market Stream tests (if configured).

Behind the scenes, the CLI calls `pytest` with mapped file paths.

---

## 7. Recommended Workflows

### 7.1 Developing a New Strategy

1. Write or extend a strategy class in `packages/tradeflow/python_strategies.py`.
2. Register the strategy in Mongo with `python_strategy_path` pointing to your class.
3. Create unit tests in `tests/no_db/` for any pure logic.
4. Run:
   - `pytest tests/no_db/test_indicator_calculator.py`
   - `pytest tests/no_db/test_engine_flow.py`
5. Run DB‑mode backtests using `tests.backtest.backtest_runner`.
6. Optionally, add a frozen DB test in `tests/frozen_db/` for a golden scenario.

### 7.2 Verifying a Data Change or Migration

1. Update your collectors or data migration scripts.
2. Run:
   - `pytest tests/readwrite_db/test_collectors.py`
3. If affecting core collections, re‑seed `tradebot_frozen` and re‑run:
   - `pytest tests/frozen_db/`

### 7.3 Pre‑Live Checklist

Before running a new strategy live:

- [ ] Run unit tests (`tests/no_db/`).
- [ ] Run at least one DB‑mode backtest over multiple days.
- [ ] Optionally run socket‑mode backtests to mimic live feed behavior.
- [ ] Run `live-trade --mock <date>` to validate the full live pipeline against historical data.
- [ ] Check PnL and event logs in backtest collections.


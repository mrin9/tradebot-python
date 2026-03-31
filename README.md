## Trade Bot V2

**Python Trading Engine for Indian Markets (XTS Connect)**

This project contains a **multi‑timeframe trading engine**, **backtest framework**, and **live trading wrapper** for the Indian markets using XTS. The focus of this README is the **core engine, data layer, and CLI**; the UI and HTTP API are optional layers and are not required to understand or operate the trading logic.

---

## Quickstart

### 1. Prerequisites

- **Python 3.10+** (3.11 recommended)
- **MongoDB** (local or remote)
- **XTS Credentials** (for live trading)

### 2. Setup

```bash
git clone <repo_url>
cd trade-bot-v2

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env with:
# - DB_NAME (e.g., tradebot, tradebot_test, tradebot_frozen)
# - Mongo connection details
# - XTS API keys (if you plan to trade live)
```

### 3. First‑Time Initialization

Run these once per environment:

```bash
# Ensure DB indexes
python apps/cli/main.py ensure_indexes

# Seed default strategy indicator configs
python apps/cli/main.py seed_strategies

# Sync instrument master and recent history
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "5dago|now"
```

---

## Core Workflows (CLI‑Driven)

The main entry point for operating the engine is the **CLI**:

```bash
python apps/cli/main.py --help
python apps/cli/main.py menu      # Interactive console
```

### Backtesting

Run a strategy against historical data:

```bash
python apps/cli/main.py backtest \
  --strategy-id triple-confirmation \
  --start 2024-02-01 \
  --end 2024-02-02 \
  --mode db \
  --budget 200000 \
  --invest-mode compound \
  --sl-pct 2.0 \
  --target-pct 2.0,5.0,10.0 \
  --tsl-pct 1.0 \
  --strike-selection ATM
```

You can also use `python apps/cli/main.py interactive_backtest` or the `menu` command for a guided flow. See `docs/testing_guide.md` for detailed backtest options and test suites.

### Live Trading

Start the live engine (XTS sockets + FundManager):

```bash
python apps/cli/main.py live_trade \
  --strategy-id triple-confirmation \
  --strike-selection ATM \
  --budget 200000 \
  --sl-pct 2.0 \
  --target-pct 2.0,3.0,4.0 \
  --tsl-pct 1.0 \
  --use-be \
  --tsl-id active-ema-5 \
  --record-papertrade \
  --log-active-indicator \
  --debug
```

See `docs/live_trading_guide.md` for a deeper explanation of how live trading works and how to operate it safely.

### Data Maintenance

```bash
# Sync instrument master and history
python apps/cli/main.py update_master
python apps/cli/main.py sync_history --date-range "2dago|now"

# Manage data quality and size
python apps/cli/main.py check_gaps --date-range "2dago|now"
python apps/cli/main.py fill_gaps --date-range "2dago|now"
python apps/cli/main.py age_out --days 60
```

See `docs/data_management.md` for full details on collections, suffixes, and gap handling.

---

## API & UI (Optional)

The project includes an optional FastAPI backend and a Nuxt.js frontend for monitoring trades and backtest results.

### 1. Start the API Server

The API provides data to the UI and can be started via the Makefile or directly using Uvicorn:

```bash
# Using Makefile
make api

# Or directly
python -m apps.api.run
```
The API runs on `http://localhost:8000`.

### 2. Start the UI Dashboard

The dashboard is built with Nuxt.js and requires Node.js/npm:

```bash
cd apps/ui
npm install    # First time only
npm run dev
```
The UI runs on `http://localhost:3000`.

---

## Documentation

Updated documentation is in the `docs/` folder:

- **Architecture & Layout**
  - `docs/project_layout_and_architecture.md` – Folder structure, core modules, and runtime architecture.
- **Operations & DevOps**
  - `docs/operational_guide.md` – Local setup, CLI usage, backtest and live workflows.
  - `docs/devops_guide.md` – Docker/compose usage, container logs, DB strategy.
- **Testing**
  - `docs/testing_guide.md` – Test layers (no‑DB, read/write DB, frozen DB, XTS) and backtest runner.
- **Trading & Data**
  - `docs/live_trading_guide.md` – How the live engine works with XTS and Mongo.
  - `docs/data_management.md` – Master data, history sync, gaps, age‑out, frozen DB.
- **Deep Dive**
  - `docs/functional_and_code_explanation.md` – Detailed mapping of concepts (indicators, resampling, fund manager, strategies) to concrete code.

If you see `old_docs/` in the repo, treat those files as historical notes; the `docs/` directory described above is the canonical, up‑to‑date documentation.

---

## Key Engine Features

- **Multi‑Timeframe Analysis (MTFA)** via `FundManager` and `CandleResampler`.
- **Vectorized Indicators** using Polars in `IndicatorCalculator` (EMA, RSI, Supertrend, MACD, Bollinger Bands, etc.).
- **Unified Strategy Runtime**:
  - Same `FundManager`, `PositionManager`, and Python strategy classes power both backtests and live trading.
- **Robust Risk Management**:
  - Fixed SL, multi‑target exits, pyramiding, BE, and indicator‑driven trailing SL.
- **Deterministic Testing**:
  - Frozen DB and a shared backtest runner for golden test scenarios.


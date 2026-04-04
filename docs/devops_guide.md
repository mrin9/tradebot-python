## DevOps Guide (Engine Services Only)

This guide focuses on running the **backend engine** and its dependencies in containerized environments. UI and HTTP API deployment details are intentionally omitted; we focus on the services required for data, backtests, and live trading.

---

## 1. Service Topology

Typical deployment (minimal stack):

- **API/Engine Container (`api`)**
  - Base Image: `python:3.11-slim`
  - Responsibilities:
    - Run CLI commands (`apps/cli/main.py`) for maintenance tasks.
    - Run backtests (`pytest` and `tests/backtest/backtest_runner`).
    - Run the live trading engine (`LiveTradeEngine` via `apps/cli/main.py live-trade`).
- **MongoDB Container (`mongo`)**
  - Image: `mongo:latest`
  - Volumes:
    - `mongo_data`: persist DB between restarts.

The stack is defined in `docker-compose.yml`.

---

## 2. Building & Running with Docker Compose

From the project root:

```bash
docker compose up -d --build
```

This will:

- Build the API/engine image.
- Start MongoDB with a persistent volume.

### 2.1 Rebuild Backend Only

If you’ve made changes to the engine code:

```bash
docker compose build api
docker compose up -d api
```

### 2.2 Full Rebuild (No Cache)

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

---

## 3. Environment & Configuration in Containers

The backend container reads configuration from **environment variables**, typically via `.env`.

Key environment variables:

- **Mongo / DB**
  - `DB_NAME` (e.g. `tradebot`, `tradebot_test`, `tradebot_frozen`)
  - `MONGODB_URI` (e.g. `mongodb://mongo:27017/`)
- **XTS**
  - `MARKET_API_KEY`, `MARKET_API_SECRET`
  - `INTERACTIVE_API_KEY`, `INTERACTIVE_API_SECRET`

In `docker-compose.yml`, ensure:

- The API service loads `.env`.
- The API service uses `mongo` as hostname for MongoDB (service name from compose).

Example (conceptual only):

```yaml
services:
  api:
    env_file:
      - .env
    environment:
      DB_NAME: tradebot
      MONGODB_URI: mongodb://mongo:27017/

  mongo:
    image: mongo:latest
    volumes:
      - mongo_data:/data/db
```

---

## 4. Logs, Monitoring & Debugging

### 4.1 Container Logs

Stream logs for all services:

```bash
docker compose logs -f
```

API/engine container only:

```bash
docker compose logs -f api
```

Mongo logs:

```bash
docker compose logs -f mongo
```

### 4.2 Structured Engine Logs

The engine uses `packages/utils/log_utils.py` and `trade_formatter.py` to produce:

- Heartbeat logs (indicators snapshot per candle).
- Signal logs (LONG/SHORT/EXIT, reason, timeframe).
- Trade lifecycle logs (entries, exits, EOD).

These go to stdout by default, so they appear in the container logs and can be scraped by your logging stack (ELK, Loki, etc.).

---

## 5. Running Tests in Containers

Run all tests inside the API container:

```bash
docker compose exec api pytest tests/
```

Run a specific test:

```bash
docker compose exec api pytest tests/no_db/test_candle_resampler.py
```

For backtest integration flows:

```bash
docker compose exec api python -m tests.backtest.backtest_runner --help
```

See `testing_guide.md` for details on the testing philosophy and specific suites.

---

## 6. One‑off Jobs & Maintenance Scripts

You can run any engine script inside a fresh container:

```bash
# Generic pattern
docker run --rm --env-file .env \
  --network=host \
  trade-bot-api:latest \
  python packages/db/seed_frozen_data.py
```

Examples:

- Seed frozen data:

```bash
docker compose exec api python packages/db/seed_frozen_data.py
```

- Seed strategy indicators:

```bash
docker compose exec api python packages/db/seed_strategy_indicators.py
```

- Update instrument master:

```bash
docker compose exec api python apps/cli/main.py update_master
```

---

## 7. Database Strategy

The engine uses a **collection suffix** strategy via `packages/settings.py` and `packages/utils/mongo.py`:

- **Live**: `DB_NAME=tradebot`
  - Collections: `nifty_candle`, `options_candle`, `papertrade`, `livetrade`, etc.
- **Test**: `DB_NAME=tradebot_test`
  - Collections: `nifty_candle_test`, `options_candle_test`, etc.
- **Frozen**: `DB_NAME=tradebot_frozen`
  - Collections: `nifty_candle_frozen`, `options_candle_frozen`, etc.

This allows you to:

- Run tests safely in `tradebot_test` or `tradebot_frozen`.
- Keep live data in `tradebot` without accidental contamination from tests.

When running containers for non‑production tasks, override `DB_NAME` appropriately.

---

## 8. Shell Access for Debugging

Drop into a shell inside the API container:

```bash
docker compose exec -it api bash
```

From there you can:

- Inspect logs or additional files.
- Run ad‑hoc Python scripts:

```bash
python -m pip list
python apps/cli/main.py menu
python apps/cli/main.py live-trade --help
```

---

## 9. Cleanup & Maintenance

Standard Docker cleanup commands (use with care):

```bash
# Remove all stopped containers
docker container prune

# Remove unused images
docker image prune -a

# Remove unused networks
docker network prune

# Full cleanup (containers, networks, dangling images)
docker system prune

# Full cleanup including unused images and volumes
docker system prune -a --volumes
```

Always verify you are on the correct host before doing aggressive cleanup, especially in production.


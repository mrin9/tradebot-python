.PHONY: all test test-db test-socket backtest api ui lint gaps

all: test

# --- Testing ---
test:
	pytest tests/

test-db:
	pytest tests/readwrite_db/ tests/no_db/ tests/frozen_db/

test-live:
	pytest tests/xts/ -m live

# --- Running Apps ---
api:
	python -m apps.api.main

cli:
	python -m apps.cli.main menu

# --- Backtesting Shortcuts ---
backtest:
	python -m tests.backtest.backtest_runner --mode db --start 2dago --rule-id custom-rule

# --- Maintenance ---
gaps:
	python -m apps.cli.main check-gaps --date-range "5dago|now"

update-master:
	python -m apps.cli.main update-master

sync-history:
	python -m apps.cli.main sync-history --date-range "2dago|now"

# --- Code Quality ---
lint:
	./.venv/bin/ruff check .
	./.venv/bin/mypy packages/ apps/


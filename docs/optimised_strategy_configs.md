python -m tests.backtest.backtest_runner \
  --mode db --start 2026-03-24 --end 2026-04-02 \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --invest-mode compound \
  --use-be



{
  "config": {
    "strategyId": "triple-confirmation",
    "name": "Triple Confirmation Momentum Strategy",
    "enabled": true,
    "timeframeSeconds": 180,
    "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
    "indicators": [
      "SPOT-EMA-5",
      "SPOT-EMA-21",
      "SPOT-EMA-5",
      "SPOT-EMA-21"
    ],
    "startDate": "2026-03-24",
    "endDate": "2026-03-24",
    "mode": "db",
    "tslId": "trade-ema-5",
    "budget": "200000-inr",
    "initialBudget": 200000,
    "investMode": "compound",
    "slPct": 4,
    "targets": [
      3
    ],
    "tslPct": 0.5,
    "useBe": true,
    "strikeSelection": "ATM",
    "priceSource": "open",
    "pyramidSteps": [
      100
    ],
    "pyramidConfirm": 10,
    "niftyLotSize": 65
  }
}
# Optimised Strategy Configuration

Optimised parameters for the Triple Confirmation strategy, derived from walk-forward backtesting on Mar 24 – Apr 2, 2026 data.

## Recommended Backtest Command

```bash
python -m tests.backtest.backtest_runner \
  --mode db \
  --start 2026-03-24 \
  --end 2026-04-02 \
  --strategy-id triple-confirmation \
  --budget 200000-inr \
  --sl-pct 4.0 \
  --target-pct "3" \
  --tsl-pct 0.5 \
  --invest-mode compound \
  --use-be
```

## Full Configuration Reference

```json
{
  "strategyId": "triple-confirmation",
  "name": "Triple Confirmation Momentum Strategy",
  "enabled": true,
  "timeframeSeconds": 180,
  "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
  "indicators": [
    { "indicator": "ema-5", "InstrumentType": "SPOT" },
    { "indicator": "ema-21", "InstrumentType": "SPOT" },
    { "indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH" },
    { "indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH" }
  ],
  "backtestRange": {
    "startDate": "2026-03-24",
    "endDate": "2026-04-02"
  },
  "positionConfig": {
    "mode": "db",
    "budget": "200000-inr",
    "investMode": "compound",
    "slPct": 4.0,
    "targetPct": [3],
    "tslPct": 0.5,
    "tslId": "trade-ema-5",
    "useBe": true,
    "strikeSelection": "ATM",
    "priceSource": "open",
    "pyramidSteps": [100],
    "pyramidConfirmPts": 10.0,
    "niftyLotSize": 65
  }
}
```

## Key Parameter Choices

- **SL 4%**: Limits max loss per trade to ~₹8K on a ₹200K budget. Wide enough to avoid noise exits, tight enough to prevent catastrophic single-trade losses.
- **Target 3% (single)**: Books profit quickly. On a 3-minute timeframe, option moves are fast but short-lived.
- **TSL 0.5%**: After break-even triggers, locks in nearly all gains. Produces many small winners.
- **Break-Even enabled**: Once target 1 is hit, SL moves to entry price — converts potential losers into scratch trades.
- **Compound mode**: Winning days increase position size for subsequent trades within the same session.

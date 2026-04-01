import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("seed_strategy_indicators")

INDICATORS = [
    {
        "strategyId": "dummy-reference-strategy",
        "name": "Reference indicators dictionary",
        "enabled": False,
        "timeframeSeconds": 300,
        "pythonStrategyPath": None,
        "indicators": [
            {"indicator": "ema-5", "InstrumentType": "SPOT"},
            {"indicator": "sma-50", "InstrumentType": "SPOT"},
            {"indicator": "rsi-14", "InstrumentType": "SPOT"},
            {"indicator": "atr-14", "InstrumentType": "SPOT"},
            {"indicator": "macd-12-26-9", "InstrumentType": "SPOT"},
            {"indicator": "supertrend-10-3", "InstrumentType": "SPOT"},
            {"indicator": "bbands-20-2", "InstrumentType": "SPOT"},
            {"indicator": "vwap", "InstrumentType": "SPOT"},
            {"indicator": "obv", "InstrumentType": "SPOT"},
            {"indicator": "price", "InstrumentType": "SPOT"},
        ],
    },
    {
        "strategyId": "triple-confirmation",
        "name": "Triple Confirmation Momentum Strategy",
        "enabled": True,
        "timeframeSeconds": 180,
        "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "indicators": [
            {"indicator": "ema-5", "InstrumentType": "SPOT"},
            {"indicator": "ema-21", "InstrumentType": "SPOT"},
            {"indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH"},
            {"indicator": "ema-21", "InstrumentType": "OPTIONS_BOTH"},
        ],
    },
]


def seed_strategy_indicators():
    col = MongoRepository.get_collection(settings.STRATEGY_INDICATORS_COLLECTION)

    # Complete Refresh
    col.delete_many({})
    col.insert_many(INDICATORS)

    logger.info(f"Seeded {len(INDICATORS)} strategies into {settings.STRATEGY_INDICATORS_COLLECTION} collection")
    for r in INDICATORS:
        logger.info(f"  → {r['strategyId']}: {r['name']} | Indicators: {len(r['indicators'])}")


if __name__ == "__main__":
    seed_strategy_indicators()

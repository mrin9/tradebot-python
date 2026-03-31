import os
import sys

from pymongo import ASCENDING, DESCENDING

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.db.seed_strategy_indicators import seed_strategy_indicators
from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)


class DatabaseManager:
    """
    Manages database schema, specifically ensuring collections and indexes exist.
    """

    @classmethod
    def ensure_all_indexes(cls):
        """
        Ensures all required indexes are created for all core collections.
        """
        db = MongoRepository.get_db()
        logger.info("Synchronizing database indexes...")

        try:
            # 1. Instrument Master
            master_coll = db[settings.INSTRUMENT_MASTER_COLLECTION]
            master_coll.create_index([("exchangeInstrumentID", ASCENDING)], unique=True)
            master_coll.create_index([("name", ASCENDING), ("series", ASCENDING)])
            master_coll.create_index([("contractExpiration", ASCENDING)])

            # 2. NIFTY Candles
            nifty_coll = db[settings.NIFTY_CANDLE_COLLECTION]
            nifty_coll.create_index([("i", ASCENDING), ("t", ASCENDING)], unique=True)
            nifty_coll.create_index([("t", DESCENDING)])
            nifty_coll.create_index([("isoDt", DESCENDING)])

            # 3. Options Candles
            options_coll = db[settings.OPTIONS_CANDLE_COLLECTION]
            options_coll.create_index([("i", ASCENDING), ("t", ASCENDING)], unique=True)
            options_coll.create_index([("t", DESCENDING)])
            options_coll.create_index([("isoDt", DESCENDING)])

            # 4. Active Contracts
            active_coll = db[settings.ACTIVE_CONTRACT_COLLECTION]
            active_coll.create_index([("exchangeInstrumentID", ASCENDING)], unique=True)
            active_coll.create_index([("activeDates", ASCENDING)])

            # 5. Backtest Results
            results_coll = db[settings.BACKTEST_RESULT_COLLECTION]
            results_coll.create_index([("sessionId", ASCENDING)], unique=True)
            results_coll.create_index([("timestamp", DESCENDING)])

            # 6. Live Trades
            live_coll = db.get_collection(settings.LIVE_TRADES_COLLECTION)
            live_coll.create_index([("sessionId", ASCENDING)], unique=True)
            live_coll.create_index([("timestamp", DESCENDING)])

            # 7. Paper Trades
            paper_coll = db.get_collection(settings.PAPERTRADE_COLLECTION)
            paper_coll.create_index([("sessionId", ASCENDING)], unique=True)
            paper_coll.create_index([("timestamp", DESCENDING)])

            # 8. Strategy Indicators
            strategy_coll = db.get_collection(settings.STRATEGY_INDICATORS_COLLECTION)
            strategy_coll.create_index([("strategyId", ASCENDING)], unique=True)

            logger.info("✅ Database indexes synchronized successfully.")

            # 9. Seed Strategies
            seed_strategy_indicators()

        except Exception as e:
            logger.error(f"❌ Failed to synchronize indexes: {e}")


if __name__ == "__main__":
    DatabaseManager.ensure_all_indexes()

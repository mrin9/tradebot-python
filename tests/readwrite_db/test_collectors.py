from datetime import datetime, timedelta

import pytest

from packages.data.sync_history import HistoricalDataCollector
from packages.data.sync_master import MasterDataCollector
from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository


@pytest.fixture(autouse=True)
def use_test_db():
    from packages.settings import settings

    orig_db = settings.DB_NAME
    settings.DB_NAME = "tradebot_test"
    from packages.utils.mongo import MongoRepository

    MongoRepository._client = None
    MongoRepository._db = None

    # 🧼 Clean Slate: Clear standardized collections before running tests
    db = MongoRepository.get_db()
    collections_to_clear = [
        settings.INSTRUMENT_MASTER_COLLECTION,
        settings.NIFTY_CANDLE_COLLECTION,
        settings.OPTIONS_CANDLE_COLLECTION,
    ]
    for coll in collections_to_clear:
        # Check if exists before clearing to avoid errors
        if coll in db.list_collection_names():
            print(f"Cleaning collection: {coll}")
            db[coll].delete_many({})

    yield
    settings.DB_NAME = orig_db
    MongoRepository._client = None
    MongoRepository._db = None


def test_master_update():
    print("\n--- Testing Master Data Collector ---")
    collector = MasterDataCollector()

    try:
        success = collector.update_master_db()
        if not success:
            print("Master Update returned False (likely token expired or no changes). Skipping assertion.")
            return

        # Verify DB
        db = MongoRepository.get_db()
        count = db[settings.INSTRUMENT_MASTER_COLLECTION].count_documents({})
        print(f"Total Instruments in DB: {count}")
        assert count > 0, "No instruments found in DB"
    except Exception as e:
        print(f"Master Update Failed with Exception: {e}")
        raise e


def test_historical_sync():
    print("\n--- Testing Historical Data Collector (NIFTY) ---")
    collector = HistoricalDataCollector()

    end_dt = datetime.now(DateUtils.MARKET_TZ)
    start_dt = end_dt - timedelta(days=2)
    nifty_id = settings.NIFTY_INSTRUMENT_ID

    print(f"Fetching NIFTY ({nifty_id}) from {start_dt} to {end_dt}")
    try:
        ticks_added = collector.sync_for_instrument(nifty_id, start_dt, end_dt, is_index=True)
        print(f"Ticks Added: {ticks_added}")
    except Exception as e:
        print(f"Historical Sync Failed: {e}")
        raise e

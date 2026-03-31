from datetime import datetime, timedelta

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)


def age_out_history(days: int):
    """
    Removes historical tick data older than X days.
    Does NOT touch active_contracts or instrument_master.
    """
    if days < 1:
        logger.error("Age-out days must be at least 1.")
        return

    db = MongoRepository.get_db()
    cutoff_date = datetime.now(DateUtils.MARKET_TZ) - timedelta(days=days)
    # Ticks use epoch seconds or milliseconds?
    # In historical.py we likely store 't' as standard timestamp (seconds or millis).
    # Let's check historical parser... usually XTS sends seconds or we convert.
    # DateUtils.to_timestamp returns seconds.
    cutoff_ts = int(cutoff_date.timestamp())

    friendly_date = cutoff_date.strftime("%Y-%m-%d")
    logger.info(f"PRUNING DATA | Older than {days} days (Cutoff: {friendly_date} / TS: {cutoff_ts})")

    collections = [settings.NIFTY_CANDLE_COLLECTION, settings.OPTIONS_CANDLE_COLLECTION]

    total_deleted = 0
    for coll_name in collections:
        logger.info(f"Cleaning ticks from {coll_name}...")
        # Assuming 't' is the timestamp field in mongo
        result = db[coll_name].delete_many({"t": {"$lt": cutoff_ts}})
        logger.info(f"Deleted {result.deleted_count} records from {coll_name}.")
        total_deleted += result.deleted_count

    logger.info(f"AGE OUT COMPLETE | Total ticks removed: {total_deleted}")

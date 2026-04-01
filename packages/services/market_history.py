from collections.abc import Callable
from datetime import datetime

from pymongo import UpdateOne

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("MarketHistoryService")


class MarketHistoryService:
    """
    Consolidates historical data access, warmup logic, and replay orchestration.
    Used by both FundManager and LiveTradeEngine.
    """

    def __init__(self, db=None, fetch_ohlc_api_fn: Callable | None = None):
        self.db = db if db is not None else MongoRepository.get_db()
        self.fetch_ohlc_api_fn = fetch_ohlc_api_fn

    def fetch_historical_candles(
        self,
        instrument_id: int,
        start_ts: float,
        end_ts: float,
        limit: int = settings.GLOBAL_WARMUP_CANDLES,
        timeframeSeconds: int = 60,
        segment: int = 1,
        use_api: bool = False,
        save_to_db: bool = False,
    ) -> list[dict]:
        """
        Fetches historical 1m candles from API or DB.
        If use_api is True, it first checks the DB and only calls the API if DB is insufficient.
        """
        collection = settings.NIFTY_CANDLE_COLLECTION if instrument_id == 26000 else settings.OPTIONS_CANDLE_COLLECTION

        # 1. DB Logic (Check first)
        query = {"i": instrument_id, "t": {"$lt": end_ts}}  # Use < end_ts as current tick is live
        if start_ts:
            query["t"]["$gte"] = start_ts

        # Adjust fetch limit based on timeframe (e.g. 200 * 3 = 600 for 3m)
        # 🔴 PARITY FIX: Match Java's logic which fetches exactly 'limit' 1-min candles.
        fetch_limit = limit
        
        history_cursor = list(self.db[collection].find(query).sort("t", -1).limit(fetch_limit))
        db_history = sorted(history_cursor, key=lambda x: x["t"])

        # If we have enough data in DB, return it
        if len(db_history) >= fetch_limit:
            return db_history

        # 2. API Logic (Fallback or Enrichment)
        if use_api and self.fetch_ohlc_api_fn:
            fmt = "%b %d %Y %H%M%S"
            start_dt = DateUtils.market_timestamp_to_datetime(start_ts)
            end_dt = DateUtils.market_timestamp_to_datetime(end_ts)

            logger.info(
                f"🌐 DB insufficient ({len(db_history)}/{fetch_limit}). Fetching API History for {instrument_id}: {start_dt} -> {end_dt}"
            )
            history = self.fetch_ohlc_api_fn(segment, instrument_id, start_dt.strftime(fmt), end_dt.strftime(fmt))

            if history:
                if save_to_db:
                    self._save_candles_to_db(collection, history)
                return history[-fetch_limit:]

            logger.warning(f"⚠️ API returned no data for {instrument_id}. Returning DB partials.")

        return db_history

    def _save_candles_to_db(self, collection_name: str, candles: list[dict]):
        """Persists fetched candles to MongoDB using upsert."""
        if not candles:
            return
        try:
            ops = [UpdateOne({"i": c["i"], "t": c["t"]}, {"$set": c}, upsert=True) for c in candles]
            result = self.db[collection_name].bulk_write(ops)
            logger.info(f"💾 Saved {len(candles)} candles to {collection_name} (Upserted: {result.upserted_count})")
        except Exception as e:
            logger.error(f"❌ Failed to save candles to {collection_name}: {e}")

    def run_warmup(
        self,
        fund_manager,
        instrument_id: int,
        current_ts: float,
        category: str,
        limit: int = settings.GLOBAL_WARMUP_CANDLES,
        timeframeSeconds: int = 60,
        use_api: bool = False,
        save_to_db: bool = False,
    ) -> int:
        """
        Orchestrates the warmup for a specific instrument and category inside FundManager.
        """
        # Determine sync range (10 days covers weekends even for 1500+ minutes)
        start_ts = current_ts - (3600 * 24 * 10)

        # Segment 1 for Nifty (SPOT), 2 for Options (NSEFO)
        segment = 1 if instrument_id == 26000 else 2

        history = self.fetch_historical_candles(
            instrument_id=instrument_id,
            start_ts=start_ts,
            end_ts=current_ts,
            limit=limit,
            timeframeSeconds=timeframeSeconds,
            segment=segment,
            use_api=use_api,
            save_to_db=save_to_db,
        )

        if not history:
            pretty_time = DateUtils.market_timestamp_to_iso(current_ts)
            if not getattr(fund_manager, "reduced_log", False):
                logger.warning(f"No history found for warmup: {category} ({instrument_id}) at {pretty_time}")
            return 0

        count = 0
        # Suppress heartbeats and signals during warmup
        saved_warming_up = fund_manager.is_warming_up
        fund_manager.is_warming_up = True
        
        # Suppress diagnostic logs
        fund_manager.indicator_calculator.suppress_logs = True
        for r in fund_manager.resamplers.values():
            r.suppress_logs = True

        try:
            for candle in history:
                if candle["t"] < current_ts:
                    fund_manager.on_tick_or_base_candle(candle)
                    count += 1
        except Exception as e:
            logger.exception(f"Error during warmup for {category} ({instrument_id}): {e}")
            return 0
        finally:
            fund_manager.is_warming_up = saved_warming_up
            is_reduced = getattr(fund_manager, "reduced_log", False)
            fund_manager.indicator_calculator.suppress_logs = is_reduced
            for r in fund_manager.resamplers.values():
                r.suppress_logs = is_reduced

        if not getattr(fund_manager, "reduced_log", False):
            logger.info(f"✅ Warmup complete for {category} ({instrument_id}): {count} candles processed.")
        return count

    def run_full_backtest_warmup(self, fund_manager, start_date: str, warmup_candles: int | None = None):
        """
        Feeds historical data into FundManager to warm up indicators before backtest.
        """
        if warmup_candles is None:
            warmup_candles = settings.GLOBAL_WARMUP_CANDLES

        if warmup_candles <= 0:
            return

        logger.info(f"🔥 Warming up indicators with {warmup_candles} candles...")
        dt = DateUtils.parse_iso(start_date)
        start_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())

        warmup_cursor = (
            self.db[settings.NIFTY_CANDLE_COLLECTION]
            .find({"i": settings.NIFTY_INSTRUMENT_ID, "t": {"$lt": start_ts}})
            .sort("t", -1)
            .limit(warmup_candles)
        )

        warmup_ticks = list(warmup_cursor)
        warmup_ticks.reverse()  # Chronological

        if warmup_ticks:
            logger.info(f"Feeding {len(warmup_ticks)} warmup candles.")
            # Temporarily disable logging and TRADING for warmup
            original_log_heartbeat = fund_manager.log_heartbeat
            fund_manager.log_heartbeat = False
            fund_manager.is_warming_up = True

            original_on_signal = fund_manager.position_manager.on_signal
            fund_manager.position_manager.on_signal = lambda x: None
            
            fund_manager.indicator_calculator.suppress_logs = True
            for r in fund_manager.resamplers.values():
                r.suppress_logs = True

            for tick in warmup_ticks:
                fund_manager.on_tick_or_base_candle(tick)

            fund_manager.log_heartbeat = original_log_heartbeat
            fund_manager.is_warming_up = False
            fund_manager.position_manager.on_signal = original_on_signal
            fund_manager.indicator_calculator.suppress_logs = False
            for r in fund_manager.resamplers.values():
                r.suppress_logs = False
        else:
            logger.warning("No historical data found for warmup.")

    def get_last_nifty_price(self, dt: datetime) -> float | None:
        """
        Centrally retrieves the last known NIFTY spot price for a given day.
        """
        start_dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        start_ts = DateUtils.to_timestamp(start_dt)
        end_ts = DateUtils.to_timestamp(dt, end_of_day=True)

        doc = self.db[settings.NIFTY_CANDLE_COLLECTION].find_one(
            {"i": settings.NIFTY_INSTRUMENT_ID, "t": {"$gte": start_ts, "$lte": end_ts}}, sort=[("t", -1)]
        )

        return doc["p"] if doc else None


from datetime import datetime, timedelta

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.xts.xts_normalizer import XTSNormalizer
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger(__name__)


class MasterDataCollector:
    """
    Collector for Master Instrument Data (Contract Specs).
    Fetches raw master dump from XTS, parses it, filters irrelevant contracts,
    and updates the local MongoDB.
    """

    def update_master_db(self):
        """
        Main execution method to sync master data.
        """
        # 1. Fetch Data
        from packages.xts.xts_api import XtsApi

        segments = [XtsApi.EXCHANGE_NSECM, XtsApi.EXCHANGE_NSEFO]
        logger.info(f"Fetching master data for segments: {segments}")

        response = XtsSessionManager.call_api("market", "get_master", exchange_segment_list=segments)

        content = response["result"]
        logger.info(f"Master data received. Size: {len(content)} chars. Parsing...")

        # 2. Parse
        raw_docs = XTSNormalizer.parse_xts_master_data(content)

        # 3. Filter Logic (Replicated from legacy update_master_instrument.py)
        filtered_data = self._filter_instruments(raw_docs)

        # 4. Special Case: Ensure NIFTY Index (26000) is preserved/restored
        filtered_data = self._ensure_nifty_index(filtered_data)

        if not filtered_data:
            logger.warning("No instruments remained after filtering.")
            return False

        # 5. Update DB
        self._update_mongo(filtered_data)
        return True

    def _ensure_nifty_index(self, data: list):
        """
        Special case: Indices like NIFTY 50 are often missing from general master dumps.
        This explicitly fetches the NIFTY index record and adds it to the dataset.
        """
        nifty_id = settings.NIFTY_INSTRUMENT_ID
        if any(d.get("exchangeInstrumentID") == nifty_id for d in data):
            return data

        logger.info(f"NIFTY Index ({nifty_id}) missing from master dump. Fetching via search API...")
        try:
            instruments = [{"exchangeSegment": 1, "exchangeInstrumentID": nifty_id}]
            response = XtsSessionManager.call_api("market", "search_by_instrumentid", instruments=instruments)
            if response.get("type") == "success" and response.get("result"):
                raw_nifty = response["result"][0]
                # Normalize just enough for our master collection (matching XTSNormalizer.parse_xts_master_line style)
                nifty_doc = {
                    "exchangeSegment": "NSECM",
                    "exchangeInstrumentID": nifty_id,
                    "instrumentTypeNum": raw_nifty.get("InstrumentType"),
                    "name": raw_nifty.get("Name"),
                    "description": raw_nifty.get("Description"),
                    "series": raw_nifty.get("Series"),
                    "nameWithSeries": raw_nifty.get("NameWithSeries"),
                    "instrumentID": raw_nifty.get("InstrumentID"),
                    "lotSize": raw_nifty.get("LotSize", 1),
                    "tickSize": raw_nifty.get("TickSize", 0.05),
                    "displayName": raw_nifty.get("DisplayName"),
                }
                data.append(nifty_doc)
                logger.info("NIFTY Index record restored.")
        except Exception as e:
            logger.error(f"Failed to restore NIFTY Index: {e}")
        return data

    def _filter_instruments(self, raw_data):
        now = datetime.now(DateUtils.MARKET_TZ)
        # 30 days window logic
        cutoff_date = now + timedelta(days=30)

        filtered = []
        skipped_expired = 0
        skipped_future = 0
        skipped_equity = 0

        # We need naive ISO strings for comparison with XTS format strings
        # XTS Expiry format: YYYY-MM-DDT00:00:00 (usually)
        # Let's ensure strict string comparison
        now_str = now.strftime("%Y-%m-%dT%H:%M:%S")
        cutoff_str = cutoff_date.strftime("%Y-%m-%dT%H:%M:%S")

        allowed_series = ["INDEX", "FUTIDX", "OPTIDX"]

        for doc in raw_data:
            # Filter 1: Series check (Only allow INDEX, FUTIDX, OPTIDX)
            # ALSO: Always preserve the NIFTY Index ID (26000)
            series = doc.get("series")
            inst_id = doc.get("exchangeInstrumentID")
            if series not in allowed_series and inst_id != settings.NIFTY_INSTRUMENT_ID:
                continue

            # Filter 2: Remove Instruments with Type 8 (Equity?) - legacy rule
            if doc.get("instrumentTypeNum") == 8:
                skipped_equity += 1
                continue

            # Filter 2: NSEFO Expiry Checks
            if doc.get("exchangeSegment") == "NSEFO":
                expiry = doc.get("contractExpiration")
                if not expiry:
                    # Keep if no expiry (e.g. continuous futures? usually have expiry though)
                    filtered.append(doc)
                    continue

                if expiry < now_str:
                    skipped_expired += 1
                    continue

                if expiry > cutoff_str:
                    skipped_future += 1
                    continue

            # If passed all checks
            filtered.append(doc)

        logger.info(f"Filtered {len(raw_data)} -> {len(filtered)} instruments.")
        logger.info(f"Skipped: Equity={skipped_equity}, Expired={skipped_expired}, Future={skipped_future}")
        return filtered

    def _update_mongo(self, data):
        db = MongoRepository.get_db()
        coll = db[settings.INSTRUMENT_MASTER_COLLECTION]

        # Mark all as old
        logger.info("Marking existing instruments as 'isOld=True'...")
        coll.update_many({}, {"$set": {"isOld": True}})

        # Tag new data
        for d in data:
            d["isOld"] = False

        # Bulk Upsert
        logger.info(f"Upserting {len(data)} instruments to MongoDB...")

        # Using DB handler or raw pymongo
        # We can use bulk_write for efficiency
        from pymongo import UpdateOne

        ops = [UpdateOne({"exchangeInstrumentID": d["exchangeInstrumentID"]}, {"$set": d}, upsert=True) for d in data]

        if ops:
            try:
                res = coll.bulk_write(ops, ordered=False)
                logger.info(f"Sync Complete. Matched: {res.matched_count}, Upserted: {res.upserted_count}")
            except Exception as e:
                logger.error(f"Error during bulk_write to MongoDB: {e}")

        # 5. Cleanup: Remove records that don't match our series criteria
        allowed_series = ["INDEX", "FUTIDX", "OPTIDX"]
        logger.info(f"Cleaning up instrument_master: Removing records NOT in {allowed_series}")
        delete_res = coll.delete_many(
            {"series": {"$nin": allowed_series}, "exchangeInstrumentID": {"$ne": settings.NIFTY_INSTRUMENT_ID}}
        )
        if delete_res.deleted_count > 0:
            logger.info(f"Cleanup Complete. Removed {delete_res.deleted_count} irrelevant instruments.")

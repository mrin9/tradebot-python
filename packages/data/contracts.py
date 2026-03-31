from datetime import datetime, timedelta

from pymongo import UpdateOne

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)


class ContractManager:
    """
    Manages the selection of 'Active' contracts for data collection and trading.
    Filters the massive master list down to relevant ATM/Near-OTM/ITM contracts.
    """

    def refresh_active_contracts(self, date_range_keyword: str = "today"):
        """
        Refreshes active contracts for a given date range.
        Uses NIFTY spot price to determine ATM.
        """
        db = MongoRepository.get_db()
        db[settings.NIFTY_CANDLE_COLLECTION]
        db[settings.INSTRUMENT_MASTER_COLLECTION]
        output_coll = db[settings.ACTIVE_CONTRACT_COLLECTION]

        # 1. Resolve Dates
        start_dt, end_dt = DateUtils.parse_date_range(date_range_keyword)

        # Get list of days to process (naive loop for now, or just process start_dt to end_dt)
        # We need actual market days.
        # Let's just iterate day by day.

        current = start_dt
        total_days = 0

        # Ensure indices
        output_coll.create_index("exchangeInstrumentID", unique=True)
        output_coll.create_index("activeDates")

        while current <= end_dt:
            date_str = DateUtils.to_iso_date(current)  # YYYY-MM-DD

            # 2. Get NIFTY Spot Price for this day
            price = self._get_nifty_closing_price(db, current)

            if not price:
                logger.warning(f"No NIFTY data found for {date_str}. Skipping.")
                current += timedelta(days=1)
                continue

            total_days += 1
            logger.info(f"Processing {date_str} | NIFTY Spot: {price}")

            # 3. Identify Contracts
            contracts = self._identify_contracts(db, price, current)

            if contracts:
                # 4. Upsert
                ops = [
                    UpdateOne(
                        {"exchangeInstrumentID": c["exchangeInstrumentID"]},
                        {"$set": c, "$addToSet": {"activeDates": date_str}},
                        upsert=True,
                    )
                    for c in contracts
                ]
                res = output_coll.bulk_write(ops, ordered=False)
                logger.debug(f" - {date_str}: {len(contracts)} active contracts. (Upserted: {res.upserted_count})")

            current += timedelta(days=1)

        logger.info(f"Active Contract Refresh Complete. Processed {total_days} days.")

    def _get_nifty_closing_price(self, db, dt: datetime):
        """Gets the last traded price of NIFTY for the active day."""
        from packages.services.market_history import MarketHistoryService

        history_service = MarketHistoryService(db)
        return history_service.get_last_nifty_price(dt)

    def _identify_contracts(self, db, spot_price, dt: datetime):
        """Identifies ATM, ITM, OTM options and Futures."""
        contracts = []
        master = db[settings.INSTRUMENT_MASTER_COLLECTION]
        nifty_id = settings.NIFTY_INSTRUMENT_ID

        # 1. Index itself
        idx_doc = master.find_one({"exchangeInstrumentID": nifty_id})
        if idx_doc:
            contracts.append(
                {
                    "exchangeInstrumentID": nifty_id,
                    "exchangeSegment": "NSECM",
                    "description": idx_doc.get("description", "NIFTY Index"),
                    "instrumentType": "index",
                }
            )

        # 2. Futures (Near Month)
        # XTS Expiry Format logic...
        # Simplified: Find futures expiring >= dt
        dt_str = dt.strftime("%Y-%m-%dT00:00:00")

        fut = master.find_one(
            {"exchangeSegment": "NSEFO", "name": "NIFTY", "series": "FUTIDX", "contractExpiration": {"$gte": dt_str}},
            sort=[("contractExpiration", 1)],
        )

        if fut:
            contracts.append(
                {
                    "exchangeInstrumentID": fut["exchangeInstrumentID"],
                    "exchangeSegment": "NSEFO",
                    "description": fut["description"],
                    "instrumentType": "future",
                    "contractExpiration": fut["contractExpiration"],
                }
            )

        # 3. Options (ATM +/- 10)
        strike_step = 50
        atm_strike = round(spot_price / strike_step) * strike_step
        target_strikes = [atm_strike + (i * strike_step) for i in range(-10, 11)]

        # Find nearest expiry
        opt_ref = master.find_one(
            {"exchangeSegment": "NSEFO", "name": "NIFTY", "series": "OPTIDX", "contractExpiration": {"$gte": dt_str}},
            sort=[("contractExpiration", 1)],
        )

        if opt_ref:
            expiry = opt_ref["contractExpiration"]

            options = master.find(
                {
                    "exchangeSegment": "NSEFO",
                    "name": "NIFTY",
                    "series": "OPTIDX",
                    "contractExpiration": expiry,
                    "strikePrice": {"$in": target_strikes},
                }
            )

            for opt in options:
                strike = opt.get("strikePrice")
                is_call = opt.get("optionType") == 3

                # Determine Moneyness
                if strike == atm_strike:
                    moneyness = "ATM"
                elif is_call:
                    moneyness = "ITM" if strike < spot_price else "OTM"
                else:
                    moneyness = "ITM" if strike > spot_price else "OTM"  # Put

                contracts.append(
                    {
                        "exchangeInstrumentID": opt["exchangeInstrumentID"],
                        "exchangeSegment": "NSEFO",
                        "description": opt["description"],
                        "instrumentType": "option",
                        "optionType": "CALL" if is_call else "PUT",
                        "strikePrice": strike,
                        "moneyness": moneyness,
                        "contractExpiration": expiry,
                    }
                )

        return contracts

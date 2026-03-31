import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from tests.backtest.backtest_base import BacktestDataFeeder

logger = setup_logger("DBFeeder")


class DBFeeder(BacktestDataFeeder):
    """
    Feeds data from MongoDB into the FundManager synchronously.
    """

    def start(self, bot, fund_manager):
        iso_start, iso_end, db = self.setup_backtest(bot, fund_manager)

        # 1. Get available trading days
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        trading_days = sorted([d for d in available_days if iso_start <= d <= iso_end])

        bot._log_config(trading_days)

        if not trading_days:
            logger.error("No trading days found in range.")
            return

        logger.info(f"🧪 DB Mode Backtest Started: {len(trading_days)} days.")

        for day_str in trading_days:
            self._run_day(day_str, fund_manager, db)
            bot.record_daily_pnl(day_str)

    def _run_day(self, day_str, fund_manager, db):
        logger.info(f"📅 Trade Day: {day_str}")

        dt = DateUtils.parse_iso(day_str)
        day_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())
        eod_ts = int(dt.replace(hour=15, minute=30, second=0).timestamp())

        nifty_id = settings.NIFTY_INSTRUMENT_ID

        # Retrieve ticks
        nifty_cursor = db[settings.NIFTY_CANDLE_COLLECTION].find({"i": nifty_id, "t": {"$gte": day_ts, "$lte": eod_ts}})
        ticks = list(nifty_cursor)

        # If trading derivatives, also fetch option ticks for that day
        if fund_manager.trade_instrument_type != "CASH":
            logger.info("Fetching Options ticks...")
            opt_cursor = db[settings.OPTIONS_CANDLE_COLLECTION].find({"t": {"$gte": day_ts, "$lte": eod_ts}})
            ticks.extend(list(opt_cursor))

        # Chronological Sort with Priority
        # We want NIFTY (spot) to be processed LAST for any given timestamp
        # This ensures Option Indicators are updated before SPOT triggers strategy evaluation.
        ticks.sort(key=lambda x: (x["t"], 1 if x["i"] == nifty_id else 0))
        if not ticks:
            logger.warning(f"No ticks found for {day_str}")
            return

        for tick in ticks:
            # Route tick to FundManager (which resamples and calculates indicators internally)
            fund_manager.on_tick_or_base_candle(tick)

        # EOD Settlement delegated to FundManager
        fund_manager.handle_eod_settlement(eod_ts)

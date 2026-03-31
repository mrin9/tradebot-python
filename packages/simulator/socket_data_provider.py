import asyncio
import heapq
from datetime import datetime

import socketio

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("SocketDataProvider")


class SocketDataProvider:
    def __init__(self, sio: socketio.AsyncServer):
        self.sio = sio
        self.running = False
        self.task = None

    async def start_simulation(
        self, instrument_id: int | None, start_dt: datetime, end_dt: datetime, delay: float = 0.01
    ):
        """
        Starts the simulation as a background task.
        Cancels any existing task.
        """
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        self.running = True
        logger.info(f"Starting Simulation Task for {instrument_id if instrument_id else 'ALL'} (TICK)")

        self.task = asyncio.create_task(self.stream_data(instrument_id, start_dt, end_dt, delay))

    async def stop_simulation(self):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        self.running = False
        logger.info("Simulation Stopped.")

    async def stream_data(self, instrument_id: int | None, start_dt: datetime, end_dt: datetime, delay: float):
        try:
            db = MongoRepository.get_db()

            # Query constraints
            query = {"t": {"$gte": int(start_dt.timestamp()), "$lte": int(end_dt.timestamp())}}
            if instrument_id:
                query["i"] = instrument_id

            # Prepare cursors from both collections
            nifty_coll = db[settings.NIFTY_CANDLE_COLLECTION]
            options_coll = db[settings.OPTIONS_CANDLE_COLLECTION]

            nifty_cursor = nifty_coll.find(query).sort("t", 1)
            options_cursor = options_coll.find(query).sort("t", 1)

            # 1. Helper to explode bars into a flat tick stream
            from packages.utils.replay_utils import ReplayUtils

            def _tick_generator(cursor, priority):
                for doc in cursor:
                    ticks = ReplayUtils.explode_bar_to_ticks(doc["i"], doc, doc["t"])
                    for t in ticks:
                        yield (t["t"], priority, t)

            # 2. Use heapq.merge to union and sort ALL virtual ticks by time 't'
            # We add a priority (0 for options, 1 for nifty) to ensure
            # Option indicators are updated before the Spot candle close triggers strategy evaluation.
            merged_stream = heapq.merge(
                _tick_generator(nifty_cursor, 1),
                _tick_generator(options_cursor, 0),
                key=lambda x: (x[0], x[1]),
            )

            logger.info(f"Replaying TICK data from {start_dt} to {end_dt}...")

            count = 0
            for timestamp, _priority, v_tick in merged_stream:
                if not self.running:
                    break

                if count % 5000 == 0:
                    logger.info(f"Replay progress: {count} ticks emitted. Current T: {timestamp}")

                inst_id = v_tick["i"]

                if v_tick["is_snapshot"]:
                    await self._emit_1512_snapshot(inst_id, v_tick["p"], v_tick["t"], v_tick["v"])
                else:
                    await self._emit_1501_tick(inst_id, v_tick["p"], v_tick["t"], v_tick["v"])

                if delay > 0:
                    await asyncio.sleep(delay)

                count += 1
                if count % 100 == 0:
                    await asyncio.sleep(0)  # Yield control

            logger.info(f"Replay Finished. Total ticks emitted: {count}")
            await self.sio.emit("simulation_complete", {"status": "done"})
            self.running = False

        except asyncio.CancelledError:
            logger.info("Simulation Cancelled.")
        except Exception as e:
            logger.error(f"Simulation Error: {e}", exc_info=True)
            await self.sio.emit("error", {"message": f"Streaming failed: {e!s}"})
            self.running = False

    def _get_xts_timestamp(self, ts: int) -> int:
        """
        Converts Unix UTC epoch to XTS IST-shifted 1980-epoch.
        1. Add 19800 seconds (IST shift)
        2. Subtract 315532800 seconds (Epoch shift 1970 -> 1980)
        """
        from packages.utils.date_utils import DateUtils

        return ts + settings.XTS_TIME_OFFSET - DateUtils.XTS_EPOCH_OFFSET

    async def _emit_1501_tick(self, instrument_id: int, price: float, timestamp: int, volume: int):
        """Emits Touchline (1501) full and partial events."""
        xts_ts = self._get_xts_timestamp(timestamp)

        # 1. Full JSON (Flat structure as per user request)
        payload = {
            "MessageCode": 1501,
            "ExchangeSegment": 1,
            "ExchangeInstrumentID": instrument_id,
            "ExchangeTimeStamp": xts_ts,
            "LastTradedPrice": float(price),
            "LastTradedQunatity": int(volume),
            "TotalTradedQuantity": 0,
            "LastTradedTime": xts_ts,
            "LastUpdateTime": xts_ts,
            "PercentChange": 0.0,
            "Open": 0.0,
            "High": 0.0,
            "Low": 0.0,
            "Close": 0.0,
            "BidInfo": {"Price": 0.0, "Size": 0, "TotalOrders": 0},
            "AskInfo": {"Price": 0.0, "Size": 0, "TotalOrders": 0},
        }
        await self.sio.emit("1501-json-full", payload)

    async def _emit_1512_snapshot(self, instrument_id: int, price: float, timestamp: int, volume: int):
        """Emits Snapshot/L2 (1512) full and partial events."""
        xts_ts = self._get_xts_timestamp(timestamp)

        # 1. Full JSON
        payload = {
            "MessageCode": 1512,
            "ExchangeSegment": 1,
            "ExchangeInstrumentID": instrument_id,
            "ExchangeTimeStamp": xts_ts,
            "LastTradedPrice": float(price),
            "LastTradedQuantity": int(volume),
            "TotalTradedQuantity": 0,
        }
        await self.sio.emit("1501-json-full", payload)  # Standardized to 1501-json-full for consumer
        await self.sio.emit("1512-json-full", payload)

        # 2. Partial String
        partial_str = f"i:{instrument_id},ltp:{price},ltq:{volume},v:0,ltt:{xts_ts}"
        await self.sio.emit("1501-json-partial", partial_str)

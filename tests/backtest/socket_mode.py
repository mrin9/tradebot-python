import asyncio
import queue
import threading
import time
from urllib.parse import urlparse

import socketio

from packages.settings import settings
from packages.simulator.socket_server import SocketDataService
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.xts.xts_normalizer import XTSNormalizer
from tests.backtest.backtest_base import BacktestDataFeeder

logger = setup_logger("SocketFeeder")


def is_port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


class EmbeddedSimulator:
    """Runs a SocketDataService via a background app without Typer loops"""

    def __init__(self, port=None):
        if port is None:
            url = urlparse(settings.SOCKET_SIMULATOR_URL)
            port = url.port or 5050
        self.port = port
        self.sim = SocketDataService()
        self.runner = None
        self.site = None

    async def start_async(self):
        from aiohttp import web

        self.runner = web.AppRunner(self.sim.app, access_log=None)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await self.site.start()
        logger.info(f"Embedded Simulator Started on port {self.port}")

    async def stop_async(self):
        if self.runner:
            await self.runner.cleanup()

    def run_in_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.start_async())
        # Block forever
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(self.stop_async())
            loop.close()


class SocketFeeder(BacktestDataFeeder):
    """
    Feeds data from the Socket Simulator into the FundManager synchronously.
    """

    def __init__(self):
        self.sio = socketio.Client(logger=False, engineio_logger=False)

        url = urlparse(settings.SOCKET_SIMULATOR_URL)
        self.port = url.port or 5050
        self.is_finished = threading.Event()
        self.embedded_sim_thread = None

        self.tick_queue = queue.Queue()
        self.worker_thread = None

    def _worker_loop(self, fund_manager):
        while True:
            try:
                tick = self.tick_queue.get(timeout=1.0)
                if tick is None:  # Poison pill
                    break
                fund_manager.on_tick_or_base_candle(tick)
                self.tick_queue.task_done()
            except queue.Empty:
                if self.is_finished.is_set():
                    break

    def _start_embedded_simulator(self):
        if is_port_in_use(self.port):
            logger.info(f"Socket service already running on port {self.port}. Connecting...")
            return

        logger.info(f"Port {self.port} is free. Auto-starting embedded simulator.")
        sim = EmbeddedSimulator(port=self.port)
        self.embedded_sim_thread = threading.Thread(target=sim.run_in_thread, daemon=True)
        self.embedded_sim_thread.start()

        # Wait until port is actually bound
        while not is_port_in_use(self.port):
            time.sleep(0.5)

    def start(self, bot, fund_manager):
        # 1. Lifecycle: Ensure Simulator is up
        self._start_embedded_simulator()

        start_date = bot.args.start
        end_date = bot.args.end

        _iso_start, _iso_end, _db = self.setup_backtest(bot, fund_manager)

        bot._log_config()
        logger.info("🧪 Socket Mode Backtest Started listening on '1501-json-full'")

        # Start worker thread for sequential processing
        self.worker_thread = threading.Thread(target=self._worker_loop, args=(fund_manager,), daemon=True)
        self.worker_thread.start()

        # 2. Setup Socket.IO Subscriptions
        @self.sio.event
        def connect():
            logger.info("✅ Connected to Socket Simulator")

            # Start Simulation
            # If trading CASH, only stream NIFTY. If Options/Futures, stream ALL instruments (None).
            req_instrument = (
                settings.NIFTY_INSTRUMENT_ID if fund_manager.trade_instrument_type == "CASH" else None
            )

            payload = {
                "instrument_id": req_instrument,
                "start": DateUtils._parse_keyword(start_date, is_end=False).replace(hour=9, minute=15).isoformat(),
                "end": DateUtils._parse_keyword(end_date, is_end=True).replace(hour=15, minute=30).isoformat(),
                "delay": 0.001,  # Extremely fast
            }
            logger.info(f"Triggering Start with {payload}")
            self.sio.emit("start_simulation", payload)

        @self.sio.on("1501-json-full")
        def on_market_event(data):
            # Parse based on event type
            try:
                tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
                if not tick:
                    return

                # Queue chronologically to the MTFA orchestrator worker
                if tick.get("p") is not None or tick.get("c") is not None:
                    # Maintain compatibility with FundManager which might expect 'c' instead of 'p'
                    # for candle-like structures or 'LastTradedPrice'
                    if "c" not in tick and "p" in tick:
                        tick["c"] = tick["p"]
                    if "p" not in tick and "c" in tick:
                        tick["p"] = tick["c"]

                    self.tick_queue.put(tick)
            except Exception as e:
                logger.error(f"Error parsing market event: {e}")

        @self.sio.on("simulation_complete")
        def on_complete(data):
            logger.info("🏁 Simulator Finished Batch.")
            # Ensure worker processes all pending ticks before settlement
            self.tick_queue.join()

            # Trigger EOD settlement
            eod_ts = DateUtils.to_timestamp(DateUtils.parse_iso(bot.args.end), end_of_day=True)
            fund_manager.handle_eod_settlement(eod_ts)
            self.is_finished.set()

        @self.sio.on("error")
        def on_error(data):
            logger.error(f"Simulator returned error: {data}")
            self.is_finished.set()

        @self.sio.event
        def disconnect():
            logger.info("Disconnected from Simulator.")
            # Put poison pill to terminate worker
            self.tick_queue.put(None)
            self.is_finished.set()

        # 3. Connect and Block
        try:
            url = settings.SOCKET_SIMULATOR_URL
            self.sio.connect(url, socketio_path="/apimarketdata/socket.io", transports=["websocket", "polling"])

            # Wait for completion
            while not self.is_finished.wait(timeout=1.0):
                pass

        except KeyboardInterrupt:
            logger.info("Backtest interrupted by User.")
        except Exception as e:
            logger.error(f"Socket Error: {e}")
        finally:
            if self.sio.connected:
                self.sio.disconnect()

            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=5.0)

            # Record PnL mapping for today
            bot.record_daily_pnl(start_date)

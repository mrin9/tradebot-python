"""
Drop-in replacement for LiveMarketService that connects to the EmbeddedSimulator.
Usage: LiveTradeEngine(... , mock=True) to swap real XTS for the local simulator.
"""

import asyncio
import queue
import threading
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import socketio

from packages.settings import settings

# Python 3.11+ compat patch for old socketio (4.6.0)
_original_asyncio_wait = asyncio.wait


def _patched_asyncio_wait(fs, *args, **kwargs):
    tasks = [asyncio.create_task(f) if asyncio.iscoroutine(f) else f for f in fs]
    return _original_asyncio_wait(tasks, *args, **kwargs)


asyncio.wait = _patched_asyncio_wait
from packages.simulator.socket_server import SocketDataService
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.xts.xts_normalizer import XTSNormalizer

logger = setup_logger("MockMarketService")


def _is_port_in_use(port: int) -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("localhost", port)) == 0


class MockMarketService:
    """
    Mimics LiveMarketService interface but streams data from the EmbeddedSimulator.
    """

    def __init__(self, start_date: str, end_date: str, debug: bool = False):
        self.start_date = start_date
        self.end_date = end_date

        url = urlparse(settings.SOCKET_SIMULATOR_URL)
        self.port = url.port or 5050
        self.sim_url = settings.SOCKET_SIMULATOR_URL

        self.sio = socketio.Client(logger=False, engineio_logger=False)
        self.tick_queue: queue.Queue = queue.Queue()
        self.subscribed_instruments: set[int] = set()
        self.on_tick_callback: Callable[[dict], None] | None = None
        self.is_running = False
        self.last_tick_time = time.time()
        self._sim_thread: threading.Thread | None = None
        self._processor_thread: threading.Thread | None = None

    # ── Simulator lifecycle ──────────────────────────────────────────

    def _ensure_simulator(self):
        if _is_port_in_use(self.port):
            logger.info(f"Simulator already running on :{self.port}")
            return

        import asyncio
        from aiohttp import web

        sim = SocketDataService()

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            runner = web.AppRunner(sim.app, access_log=None)
            loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, "0.0.0.0", self.port)
            loop.run_until_complete(site.start())
            logger.info(f"Embedded Simulator started on :{self.port}")
            loop.run_forever()

        self._sim_thread = threading.Thread(target=_run, daemon=True)
        self._sim_thread.start()
        while not _is_port_in_use(self.port):
            time.sleep(0.3)

    # ── LiveMarketService-compatible interface ───────────────────────

    def start(self, on_tick: Callable[[dict[str, Any]], None]) -> None:
        self.on_tick_callback = on_tick
        self.is_running = True

        self._ensure_simulator()

        self._processor_thread = threading.Thread(target=self._processor_loop, daemon=True)
        self._processor_thread.start()

        self._connect_and_stream()

    def stop(self) -> None:
        self.is_running = False
        if self.sio.connected:
            self.sio.disconnect()
        logger.info("🏁 Mock Market Service Stopped.")

    def subscribe(self, instrument_ids: list[int]) -> None:
        self.subscribed_instruments.update(instrument_ids)

    def unsubscribe(self, instrument_ids: list[int]) -> None:
        self.subscribed_instruments.difference_update(instrument_ids)

    def ensure_connection(self) -> None:
        pass  # no-op for mock

    # ── Internal ─────────────────────────────────────────────────────

    def _processor_loop(self):
        while self.is_running:
            try:
                data = self.tick_queue.get(timeout=1)
                if data is None:
                    break
                if isinstance(data, dict) and data.get("__simulation_complete__"):
                    if self.on_tick_callback:
                        self.on_tick_callback(data)
                    break
                tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
                if tick and self.on_tick_callback:
                    # Align with backtest SocketFeeder: ensure both 'c' and 'p' exist
                    if "c" not in tick and "p" in tick:
                        tick["c"] = tick["p"]
                    if "p" not in tick and "c" in tick:
                        tick["p"] = tick["c"]
                    self.last_tick_time = time.time()
                    self.on_tick_callback(tick)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Processor error: {e}", exc_info=True)

    def _connect_and_stream(self):
        finished = threading.Event()

        @self.sio.event
        def connect():
            logger.info("✅ Connected to Simulator")
            payload = {
                "instrument_id": None,
                "start": DateUtils._parse_keyword(self.start_date, is_end=False)
                .replace(hour=9, minute=15)
                .isoformat(),
                "end": DateUtils._parse_keyword(self.end_date, is_end=True)
                .replace(hour=15, minute=30)
                .isoformat(),
                "delay": 0.001,
            }
            self.sio.emit("start_simulation", payload)

        @self.sio.on("1501-json-full")
        def on_market_event(data):
            self.tick_queue.put(data)

        @self.sio.on("simulation_complete")
        def on_complete(_data):
            logger.info("🏁 Simulation complete")
            self.tick_queue.put({"__simulation_complete__": True})
            finished.set()

        @self.sio.on("error")
        def on_error(data):
            logger.error(f"Simulator error: {data}")
            finished.set()

        @self.sio.event
        def disconnect():
            finished.set()

        def _run():
            try:
                self.sio.connect(
                    self.sim_url,
                    socketio_path="/apimarketdata/socket.io",
                    transports=["websocket", "polling"],
                )
                finished.wait()
            except Exception as e:
                logger.error(f"Socket error: {e}")
            finally:
                if self.sio.connected:
                    self.sio.disconnect()

        threading.Thread(target=_run, daemon=True).start()

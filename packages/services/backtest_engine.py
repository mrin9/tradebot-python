import asyncio
import queue
import threading
import time
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import socketio

from packages.services.market_history import MarketHistoryService
from packages.services.trade_event import TradeEventService
from packages.settings import settings
from packages.simulator.socket_server import SocketDataService
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import InstrumentCategoryType
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.utils.trade_persistence import TradePersistence
from packages.xts.xts_normalizer import XTSNormalizer

logger = setup_logger("BacktestEngine")


# Python 3.11+ Compatibility Patch for old socketio (4.6.0)
# socketio 4.6.0 calls asyncio.wait([coro]), which is an error in Python 3.11+.
# We wrap them into tasks automatically.
_original_asyncio_wait = asyncio.wait


def _patched_asyncio_wait(fs, *args, **kwargs):
    tasks = [asyncio.create_task(f) if asyncio.iscoroutine(f) else f for f in fs]
    return _original_asyncio_wait(tasks, *args, **kwargs)


asyncio.wait = _patched_asyncio_wait


class BacktestFeeder(ABC):
    """Abstract interface for feeding data into the BacktestEngine."""

    @abstractmethod
    def start(self, engine: "BacktestEngine"):
        pass


class DBFeeder(BacktestFeeder):
    """Feeds historical data from MongoDB."""

    def start(self, engine: "BacktestEngine"):
        fm = engine.fund_manager
        db = MongoRepository.get_db()

        # 1. Get Trading Days
        iso_start = DateUtils._parse_keyword(engine.start_date, is_end=False).strftime("%Y-%m-%d")
        iso_end = DateUtils._parse_keyword(engine.end_date, is_end=True).strftime("%Y-%m-%d")
        available_days = DateUtils.get_available_dates(db, settings.NIFTY_CANDLE_COLLECTION)
        trading_days = sorted([d for d in available_days if iso_start <= d <= iso_end])

        if not trading_days:
            logger.error("No trading days found in range.")
            return

        logger.info(f"🧪 DB Mode Backtest Started: {len(trading_days)} days.")
        
        # We need a shared active_grid to persist between days for FundManager
        engine.fund_manager.active_grid_ids = set()

        for day_str in trading_days:
            logger.info(f"📅 Trading Day: {day_str}")
            dt = DateUtils.parse_iso(day_str)
            day_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())
            eod_ts = int(dt.replace(hour=15, minute=30, second=0).timestamp())

            # 1. Initialize Daily Grid
            fm.active_grid_ids.clear()
            fm.resamplers.clear()
            fm.indicator_calculator.reset()
            fm.latest_tick_prices.clear()
            fm.latest_market_time = None
            fm.monitored_instrument_ids.clear()
            
            instruments_to_monitor = {settings.NIFTY_INSTRUMENT_ID}
            if fm.trade_instrument_type != "CASH":
                grid_ids = engine.fund_manager.discovery_service.get_daily_grid_ids(dt, strike_count=20)
                fm.active_grid_ids.update(grid_ids)
                fm.monitored_instrument_ids.update(grid_ids)
                instruments_to_monitor.update(grid_ids)
            
            # Keep protected positions active
            if fm.position_manager.current_position:
                instruments_to_monitor.add(int(fm.position_manager.current_position.symbol))

            # 2. Daily Warmup for all active instruments
            MarketHistoryService(db).run_warmup(fm, settings.NIFTY_INSTRUMENT_ID, day_ts, "SPOT")
            if fm.trade_instrument_type != "CASH":
                for opt_id in fm.active_grid_ids:
                    opt_cat = fm.discovery_service.get_option_type(opt_id)
                    fm._ensure_resampler(opt_id, InstrumentCategoryType(opt_cat))
                    MarketHistoryService(db).run_warmup(fm, opt_id, day_ts, opt_cat)

            fm.latest_indicators_state = fm._get_mapped_indicators()

            # 3. Fetch Ticks for the day
            nifty_id = settings.NIFTY_INSTRUMENT_ID
            nifty_cursor = db[settings.NIFTY_CANDLE_COLLECTION].find(
                {"i": nifty_id, "t": {"$gte": day_ts, "$lte": eod_ts}}
            )
            ticks = list(nifty_cursor)

            if fm.trade_instrument_type != "CASH":
                # Only load options we care about to save memory
                opt_query = {
                    "t": {"$gte": day_ts, "$lte": eod_ts},
                    "i": {"$in": list(instruments_to_monitor - {nifty_id})}
                }
                opt_cursor = db[settings.OPTIONS_CANDLE_COLLECTION].find(opt_query)
                ticks.extend(list(opt_cursor))

            ticks.sort(key=lambda x: (x["t"], 1 if x["i"] == nifty_id else 0))

            for tick in ticks:
                fm.on_tick_or_base_candle(tick)

            fm.handle_eod_settlement(eod_ts)
            engine.record_daily_pnl(day_str)


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


class SocketFeeder(BacktestFeeder):
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

    def start(self, engine: "BacktestEngine"):
        fm = engine.fund_manager
        db = MongoRepository.get_db()

        # 1. Warmup (Assuming Socket is for a single day usually, we initialize grid once based on start_date)
        dt = DateUtils.parse_iso(engine.start_date)
        day_ts = int(dt.replace(hour=9, minute=15, second=0).timestamp())

        fm.active_grid_ids.clear()
        if fm.trade_instrument_type != "CASH":
            grid_ids = engine.fund_manager.discovery_service.get_daily_grid_ids(dt, strike_count=20)
            fm.active_grid_ids.update(grid_ids)
            fm.monitored_instrument_ids.update(grid_ids)
        
        MarketHistoryService(db).run_warmup(fm, settings.NIFTY_INSTRUMENT_ID, day_ts, "SPOT")
        if fm.trade_instrument_type != "CASH":
            for opt_id in fm.active_grid_ids:
                opt_cat = fm.discovery_service.get_option_type(opt_id)
                fm._ensure_resampler(opt_id, InstrumentCategoryType(opt_cat))
                MarketHistoryService(db).run_warmup(fm, opt_id, day_ts, opt_cat)

        fm.latest_indicators_state = fm._get_mapped_indicators()

        # 2. Lifecycle: Ensure Simulator is up
        self._start_embedded_simulator()

        logger.info("🧪 Socket Mode Backtest Started listening on '1501-json-full'")

        # Start worker thread for sequential processing
        self.worker_thread = threading.Thread(target=self._worker_loop, args=(fm,), daemon=True)
        self.worker_thread.start()

        # 3. Setup Socket.IO Subscriptions
        @self.sio.event
        def connect():
            logger.info("✅ Connected to Socket Simulator")

            # Start Simulation
            # If trading CASH, only stream NIFTY. If Options/Futures, stream ALL instruments (None).
            req_instrument = settings.NIFTY_INSTRUMENT_ID if fm.trade_instrument_type == "CASH" else None

            payload = {
                "instrument_id": req_instrument,
                "start": DateUtils._parse_keyword(engine.start_date, is_end=False).replace(hour=9, minute=15).isoformat(),
                "end": DateUtils._parse_keyword(engine.end_date, is_end=True).replace(hour=15, minute=30).isoformat(),
                "delay": 0.001,  # Extremely fast
            }
            logger.info(f"Triggering Start with {payload}")
            self.sio.emit("start_simulation", payload)

        @self.sio.on("1501-json-full")
        def on_market_event(data):
            try:
                tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
                if not tick:
                    return

                if tick.get("p") is not None or tick.get("c") is not None:
                    # Maintain compatibility with FundManager which might expect 'c' instead of 'p'
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
            self.tick_queue.join()

            # Trigger EOD settlement
            eod_ts = DateUtils.to_timestamp(DateUtils.parse_iso(engine.end_date), end_of_day=True)
            fm.handle_eod_settlement(eod_ts)
            engine.record_daily_pnl(engine.end_date)
            self.is_finished.set()

        @self.sio.on("error")
        def on_error(data):
            logger.error(f"Simulator returned error: {data}")
            self.is_finished.set()

        @self.sio.event
        def disconnect():
            logger.info("Disconnected from Simulator.")
            self.tick_queue.put(None)
            self.is_finished.set()

        # 4. Connect and Block
        try:
            url = settings.SOCKET_SIMULATOR_URL
            self.sio.connect(url, socketio_path="/apimarketdata/socket.io", transports=["websocket", "polling"])

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


class BacktestEngine:
    """
    Orchestrates the backtest session.
    """

    def __init__(
        self,
        strategy_config: dict,
        position_config: dict,
        start_date: str,
        end_date: str | None = None,
        mode: str = "db",
        reduced_log: bool = False,
    ):
        self.strategy_config = strategy_config
        self.position_config = position_config
        self.start_date = start_date
        self.end_date = end_date or start_date
        self.mode = mode

        from packages.services.contract_discovery import ContractDiscoveryService
        # Performance optimization: Load contract cache for the symbol relative to backtest start BEFORE FundManager init
        bt_start_dt = DateUtils.parse_iso(self.start_date)
        discovery = ContractDiscoveryService()
        discovery.load_cache(
            symbol=self.strategy_config.get("symbol", "NIFTY"),
            series=self.strategy_config.get("series", "OPTIDX"),
            effective_date=bt_start_dt,
        )

        self.fund_manager = FundManager(
            strategy_config=strategy_config,
            position_config=position_config,
            is_backtest=True,
            reduced_log=reduced_log,
            discovery_service=discovery,
            active_grid_ids=set()
        )
        
        # Inject backtest dates into config for persistence
        self.fund_manager.config["startDate"] = self.start_date
        self.fund_manager.config["endDate"] = self.end_date

        self.daily_pnl = {}
        self._last_pnl_checkpoint = 0.0
        # 2. Setup Session ID
        # bt_start_dt is already defined above
        prefix = self.strategy_config.get("strategyId", "BT")
        self.session_id = DateUtils.generate_session_id(prefix, custom_time=bt_start_dt)
        self.event_service = TradeEventService(self.session_id)
        # Tag mock orders with session ID
        if hasattr(self.fund_manager.order_manager, 'session_id'):
            self.fund_manager.order_manager.session_id = self.session_id

    def record_daily_pnl(self, day_str: str):
        current_total_pnl = self.fund_manager.position_manager.session_realized_pnl
        daily_increment = current_total_pnl - self._last_pnl_checkpoint
        self.daily_pnl[day_str] = daily_increment
        self._last_pnl_checkpoint = current_total_pnl
        logger.info(f"Day {day_str} PnL: {int(daily_increment):,} | Total: {int(current_total_pnl):,}")

    def run(self):
        """Starts the backtest execution."""
        if self.mode == "db":
            feeder = DBFeeder()
        elif self.mode == "socket":
            feeder = SocketFeeder()
        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented in BacktestEngine yet.")

        feeder.start(self)

        # Record INIT event with enriched config
        self.event_service.record_init(self.fund_manager, mode=self.mode)

        self.generate_report()
        self.save_results()

    def generate_report(self):
        pm = self.fund_manager.position_manager
        trades = pm.trades_history
        total_pnl = pm.session_realized_pnl
        budget_val = self.fund_manager.initial_budget

        # ROI Fix: If budget was defined in 'lots', initial_budget is 0.
        # We estimate nominal budget from the first trade's cost to calculate ROI.
        if budget_val <= 0 and trades:
            first_trade = trades[0]
            lot_size = settings.NIFTY_LOT_SIZE
            # pm.quantity here is the base lots configured for the session
            budget_val = first_trade.entry_price * pm.quantity * lot_size

        roi = (total_pnl / budget_val) * 100 if budget_val > 0 else 0

        unique_cycles = len(set(t.trade_cycle for t in trades if t.trade_cycle != "N/A"))
        total_trades = pm.entry_count + len(trades)
        logger.info("=" * 40)
        logger.info(f"BACKTEST COMPLETE | Total PnL: {total_pnl:,.2f} | ROI: {roi:.2f}%")
        logger.info(f"Total Cycles: {unique_cycles} (Total Trades: {total_trades} | Entries: {pm.entry_count} | Exits: {len(trades)})")
        logger.info("=" * 40)

    def save_results(self):
        try:
            config_summary = TradeEventService.build_config_summary(self.fund_manager, mode=self.mode)

            persistence = TradePersistence()
            persistence.save_session_summary(
                session_id=self.session_id,
                trades=self.fund_manager.position_manager.trades_history,
                config=config_summary,
                daily_pnl=self.daily_pnl,
                is_live=False,
            )
            logger.info(f"✅ Results saved to {self.session_id}")
        except Exception as e:
            logger.error(f"Failed to save results: {e}")

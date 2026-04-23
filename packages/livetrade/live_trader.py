from datetime import datetime, timedelta
import json
import threading
import time
from typing import Any

from packages.services.contract_discovery import ContractDiscoveryService
from packages.services.live_market import LiveMarketService
from packages.services.market_history import MarketHistoryService
from packages.services.trade_config_service import TradeConfigService
from packages.services.trade_event import TradeEventService
from packages.settings import settings
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import InstrumentCategoryType
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.utils.trade_formatter import TradeFormatter
from packages.xts.xts_normalizer import XTSNormalizer
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("LiveTrader")


class LiveTradeEngine:
    """
    Orchestrates live trading by connecting LiveMarketService to TradeFlow FundManager.
    Pass mock="2025-04-10" (or a date range tuple) to use the EmbeddedSimulator instead of real XTS.
    """

    def __init__(self, strategy_config: dict[str, Any], position_config: dict[str, Any], debug: bool = False, mock: str | tuple[str, str] | None = None):
        self.strategy_config = strategy_config
        self.position_config = position_config

        # Session ID
        self.session_id = DateUtils.generate_session_id(strategy_config.get("strategyId", "python"))

        # 1. Initialize Services
        self.config_service = TradeConfigService()
        self.discovery_service = ContractDiscoveryService()
        mock_effective_date = None
        if mock:
            start_d = mock[0] if isinstance(mock, tuple) else mock
            mock_effective_date = DateUtils.parse_iso(start_d)
        self.discovery_service.load_cache(
            symbol=self.strategy_config.get("symbol", "NIFTY"), series=self.strategy_config.get("series", "OPTIDX"),
            effective_date=mock_effective_date,
        )
        self.history_service = MarketHistoryService(fetch_ohlc_api_fn=self._fetch_ohlc_api)

        if mock:
            from packages.services.mock_market import MockMarketService
            start_d, end_d = (mock, mock) if isinstance(mock, str) else mock
            self.market_service = MockMarketService(start_date=start_d, end_date=end_d, debug=debug)
        else:
            self.market_service = LiveMarketService(debug=debug)
        self.mock = mock
        self.event_service = TradeEventService(self.session_id)

        # 2. Setup active grid for FundManager
        self.active_grid_ids: set[int] = set()
        self.eq_instrument_ids: set[int] = set()

        # 3. Initialize FundManager with services
        self.fund_manager = FundManager(
            strategy_config=self.strategy_config,
            position_config=self.position_config,
            reduced_log=False,
            is_backtest=bool(mock),
            config_service=self.config_service,
            discovery_service=self.discovery_service,
            history_service=self.history_service,
            fetch_quote_fn=self._fetch_quote_api,
            active_grid_ids=self.active_grid_ids,
            eq_instrument_ids=self.eq_instrument_ids,
        )

        # Hook FundManager events into TradeEventService
        self.fund_manager.on_signal = self._handle_signal
        self.fund_manager.position_manager.on_trade_event = lambda ev: self.event_service.record_trade_event(
            ev, self.fund_manager
        )
        # Tag mock orders with session ID
        if hasattr(self.fund_manager.order_manager, 'session_id'):
            self.fund_manager.order_manager.session_id = self.session_id

        self.last_tick_time = time.time()
        self.is_running = False
        self.has_warmed_up = False
        self.current_atm_strike = None
        self._warmup_tick_buffer: list[dict] = []

    def start(self):
        logger.info(
            TradeFormatter.format_session_start(
                self.session_id, self.strategy_config.get("name"), self.strategy_config.get("strategyId")
            )
        )

        # Initial subscriptions and grid logic
        self._initialize_daily_grid()

        # Start Services
        self.market_service.start(on_tick=self._process_tick)

        self.is_running = True

        try:
            while self.is_running:
                if not self.mock:
                    now = datetime.now(DateUtils.MARKET_TZ)
                    # EOD Settlement
                    if now.hour == 15 and now.minute >= 31:
                        self.fund_manager.handle_eod_settlement(time.time())
                        self.stop()
                        break

                    # Health Check (Socket & Drift)
                    if time.time() - self.last_tick_time > 30:
                        self.market_service.ensure_connection()
                        self.last_tick_time = time.time()

                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
        finally:
            self.stop()

    def stop(self):
        if not self.is_running:
            return
        self.is_running = False
        self.market_service.stop()
        self.event_service.sync_session_summary(self.fund_manager)
        logger.info("🏁 Live Trade Engine Stopped.")

    def _process_tick(self, tick: dict):
        """Passed as callback to LiveMarketService."""
        self.last_tick_time = time.time()

        # Mock mode: handle simulation complete → EOD settlement
        if tick.get("__simulation_complete__"):
            if self.mock:
                end_d = self.mock[1] if isinstance(self.mock, tuple) else self.mock
                eod_ts = DateUtils.to_timestamp(DateUtils.parse_iso(end_d), end_of_day=True)
                self.fund_manager.handle_eod_settlement(eod_ts)
            self.stop()
            return

        # 1. Warmup Check
        if not self.has_warmed_up:
            # Buffer ticks instead of dropping them
            self._warmup_tick_buffer.append(tick)
            if not self.fund_manager.is_warming_up:
                threading.Thread(target=self._warm_up, args=(tick["t"],), daemon=True).start()
            return

        # 2. FundManager Feed
        self.fund_manager.on_tick_or_base_candle(tick)

    def _handle_signal(self, payload: dict):
        """FundManager signal callback."""
        self.event_service.record_signal(payload)

        # Ensure we are subscribed to the signal instrument
        symbol = int(payload.get("symbol"))
        if symbol not in self.market_service.subscribed_instruments:
            self.market_service.subscribe([symbol])

    def _warm_up(self, anchor_timestamp: int):
        if self.has_warmed_up:
            return
        self.fund_manager.is_warming_up = True

        try:
            logger.info("🔥 Commencing Bulk Warmup for Static Grid...")
            # Warm up SPOT
            self.history_service.run_warmup(
                self.fund_manager,
                settings.NIFTY_INSTRUMENT_ID,
                anchor_timestamp,
                "SPOT",
                timeframeSeconds=self.fund_manager.global_timeframe,
                use_api=True,
            )

            # Warm up Options Grid
            if self.strategy_config.get("instrument_type", "OPTIONS") != "CASH":
                total_opts = len(self.active_grid_ids)
                for idx, opt_id in enumerate(self.active_grid_ids):
                    if idx % 10 == 0 or idx == total_opts - 1:
                        logger.info(f"⏳ Warmup Progress: {idx+1}/{total_opts} options processed...")
                    
                    opt_cat = self.fund_manager.discovery_service.get_option_type(opt_id)
                    # Initialize resamplers
                    self.fund_manager._ensure_resampler(opt_id, InstrumentCategoryType(opt_cat))
                    
                    self.history_service.run_warmup(
                        self.fund_manager,
                        opt_id,
                        anchor_timestamp,
                        opt_cat,
                        timeframeSeconds=self.fund_manager.global_timeframe,
                        use_api=True,
                    )
            
            # Extract indicators to be ready for tick 1
            self.fund_manager.latest_indicators_state = self.fund_manager._get_mapped_indicators()

            self.has_warmed_up = True
            self.fund_manager.is_warming_up = False

            # Replay buffered ticks that arrived during warmup
            buffered = self._warmup_tick_buffer
            self._warmup_tick_buffer = []
            logger.info(f"🔄 Replaying {len(buffered)} buffered ticks from warmup period...")
            for buffered_tick in buffered:
                self.fund_manager.on_tick_or_base_candle(buffered_tick)

            # Record INIT event with enriched config
            self.event_service.record_init(self.fund_manager, mode="live")
            logger.info("✅ Bulk Warmup Complete. Ready for Live Ticks.")
        finally:
            self.fund_manager.is_warming_up = False

    def _initialize_daily_grid(self):
        """Initial ATM resolution and static 80-option grid subscription."""
        try:
            if self.mock:
                start_d = self.mock[0] if isinstance(self.mock, tuple) else self.mock
                now = DateUtils.parse_iso(start_d)
            else:
                now = datetime.now(DateUtils.MARKET_TZ)
            instruments_to_sub = {settings.NIFTY_INSTRUMENT_ID}

            if self.strategy_config.get("instrument_type", "OPTIONS") != "CASH":
                logger.info("📡 Deriving Static Option Grid for the day...")
                # Track 20 strikes up and down
                grid_ids = self.discovery_service.get_daily_grid_ids(now, strike_count=20)
                if grid_ids:
                    self.active_grid_ids.update(grid_ids)
                    self.fund_manager.monitored_instrument_ids.update(grid_ids)
                    instruments_to_sub.update(grid_ids)
                    logger.info(f"✅ Found {len(grid_ids)} options for static grid tracking.")
                else:
                    logger.warning("⚠️ Failed to derive static option grid. Will rely only on protected positions.")

            # Identify protected instruments (currently in position)
            active_pos = self.fund_manager.position_manager.current_position
            if active_pos:
                instruments_to_sub.add(int(active_pos.symbol))

            # FNO Equity Archival Subscription
            if not self.mock and settings.ARCHIVE_FNO_EQUITIES:
                logger.info("📡 Fetching FNO Equity IDs for archival...")
                eq_ids = self.discovery_service.get_fno_equity_ids()
                if eq_ids:
                    self.eq_instrument_ids.update(eq_ids)
                    self.fund_manager.eq_instrument_ids = self.eq_instrument_ids
                    if hasattr(self.market_service, "nsecm_instruments"):
                        self.market_service.nsecm_instruments.update(eq_ids)
                    instruments_to_sub.update(eq_ids)
                    logger.info(f"✅ Added {len(eq_ids)} FNO Equities to subscription list.")

            current_subs = self.market_service.subscribed_instruments
            to_sub = list(instruments_to_sub - current_subs)
            to_unsub = list((current_subs - instruments_to_sub))

            if to_sub:
                self.market_service.subscribe(to_sub)
            if to_unsub:
                self.market_service.unsubscribe(to_unsub)

        except Exception as e:
            logger.error(f"❌ Error in _initialize_daily_grid: {e}")



    def _fetch_ohlc_api(
        self, segment: int, instrument_id: int, start_time: str | None = None, end_time: str | None = None
    ) -> list[dict]:
        """Wrapper for XTS REST API."""
        try:
            if not start_time or not end_time:
                now = datetime.now(DateUtils.MARKET_TZ)
                fmt = "%b %d %Y %H%M%S"
                end_time = now.strftime(fmt)
                start_time = (now - timedelta(hours=1)).strftime(fmt)

            response = XtsSessionManager.call_api(
                "market",
                "get_ohlc",
                exchange_segment=segment,
                exchange_instrument_id=instrument_id,
                start_time=start_time,
                end_time=end_time,
                compression_value=60,
            )
            if response and isinstance(response, dict) and response.get("type") == "success":
                raw = response.get("result", {}).get("dataReponse", "")
                candles = []
                for rec in raw.strip().split(","):
                    parts = rec.strip().split("|")
                    if len(parts) >= 6:
                        try:
                            ts = DateUtils.rest_timestamp_to_utc(parts[0])
                        except Exception:
                            continue
                        candles.append(
                            {
                                "i": instrument_id,
                                "t": ts,
                                "o": float(parts[1]),
                                "h": float(parts[2]),
                                "l": float(parts[3]),
                                "c": float(parts[4]),
                                "v": int(parts[5]),
                            }
                        )
                return candles
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_ohlc_api: {e}")
        return []

    def _fetch_quote_api(self, segment: int, instrument_id: int) -> dict | None:
        """Wrapper for XTS Quote REST API."""
        try:
            response = XtsSessionManager.call_api(
                "market",
                "get_quote",
                instruments=[{"exchangeSegment": segment, "exchangeInstrumentID": instrument_id}],
                xts_message_code=1501,
                publish_format="1",
            )
            if response and isinstance(response, dict) and response.get("type") == "success":
                quotes = response.get("result", {}).get("listQuotes", [])
                if quotes:
                    data = json.loads(quotes[0]) if isinstance(quotes[0], str) else quotes[0]
                    return XTSNormalizer.normalize_xts_event("1501-json-full", data)
        except Exception as e:
            logger.error(f"💥 Exception in _fetch_quote_api: {e}")
        return None

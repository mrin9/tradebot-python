import queue
import threading
import time
from collections.abc import Callable
from typing import Any

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter
from packages.xts.xts_normalizer import XTSNormalizer
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("LiveMarketService")


class LiveMarketService:
    """
    Consolidates market data streaming, socket management, and instrument subscriptions.
    """

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.soc = XtsSessionManager.get_market_data_socket(debug=debug)

        self.tick_queue = queue.Queue()
        self.on_tick_callback: Callable[[dict], None] | None = None

        self.subscribed_instruments: set[int] = set()
        self.nsecm_instruments: set[int] = {settings.NIFTY_INSTRUMENT_ID}
        self.is_running = False
        self.last_tick_time = time.time()
        self._is_connecting = False

        # Socket callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_message1501_json_full = self._on_tick_raw
        self.soc.on_disconnect = self._on_disconnect
        self.soc.on_error = self._on_error

        self._processor_thread: threading.Thread | None = None

    def start(self, on_tick: Callable[[dict[str, Any]], None]) -> None:
        """
        Connects to XTS and starts the tick processing loop.
        """
        if self.is_running:
            logger.warning("Live Market Service is already running.")
            return

        self.on_tick_callback = on_tick
        self.is_running = True

        self._processor_thread = threading.Thread(target=self._tick_processor_loop, daemon=True)
        self._processor_thread.start()

        self._attempt_connection()

    def _attempt_connection(self) -> None:
        """Internal helper to safely trigger connection in a background thread."""
        if self._is_connecting or self.soc.sid.connected:
            return

        self._is_connecting = True
        logger.info(TradeFormatter.format_connection("connecting", "Connecting to Market Data Socket..."))

        def run_connect():
            try:
                # soc.connect now has its own internal retry logic
                self.soc.connect()
            except Exception as e:
                logger.error(f"❌ Socket connection final failure: {e}")
            finally:
                self._is_connecting = False
                logger.debug("Socket connection thread finished.")

        threading.Thread(target=run_connect, daemon=True).start()

    def stop(self) -> None:
        """
        Stops the service and disconnects the socket.
        """
        self.is_running = False
        # No explicit disconnect for simplicity, as it runs in daemon threads
        logger.info("🏁 Live Market Service Stopped.")

    def subscribe(self, instrument_ids: list[int]) -> None:
        """Subscribes to a list of instruments."""
        if not instrument_ids:
            return
        new_ids = [i for i in instrument_ids if i not in self.subscribed_instruments]
        if not new_ids:
            return

        # Always update tracking list
        self.subscribed_instruments.update(new_ids)

        if self.soc.sid.connected:
            if self._send_subscription_batch(new_ids, subscribe=True):
                logger.info(f"+ Subscribed to {len(new_ids)} instruments.")
        else:
            logger.info(f"⏳ Tracked {len(new_ids)} instruments for subscription (will sync on socket connection).")

    def unsubscribe(self, instrument_ids: list[int]) -> None:
        """Unsubscribes from a list of instruments."""
        if not instrument_ids:
            return
        ids_to_unsub = [i for i in instrument_ids if i in self.subscribed_instruments]
        if not ids_to_unsub:
            return

        # Always remove from tracking list
        self.subscribed_instruments.difference_update(ids_to_unsub)

        if self.soc.sid.connected:
            if self._send_subscription_batch(ids_to_unsub, subscribe=False):
                logger.info(f"- Unsubscribed from {len(ids_to_unsub)} instruments.")
        else:
            logger.info(f"⏳ Removed {len(ids_to_unsub)} instruments from tracking.")

    def _send_subscription_batch(self, instrument_ids: list[int], subscribe: bool = True) -> bool:
        """Helper to group instruments by segment and send (un)subscription command."""
        try:
            nse_eq = [i for i in instrument_ids if i in self.nsecm_instruments]
            nse_fo = [i for i in instrument_ids if i not in self.nsecm_instruments]

            func_name = "send_subscription" if subscribe else "send_unsubscription"

            if nse_eq:
                XtsSessionManager.call_api(
                    "market",
                    func_name,
                    instruments=[{"exchangeSegment": 1, "exchangeInstrumentID": i} for i in nse_eq],
                    xts_message_code=1501,
                )
            if nse_fo:
                XtsSessionManager.call_api(
                    "market",
                    func_name,
                    instruments=[{"exchangeSegment": 2, "exchangeInstrumentID": i} for i in nse_fo],
                    xts_message_code=1501,
                )
            return True
        except Exception as e:
            action = "Subscription" if subscribe else "Unsubscription"
            logger.error(f"❌ {action} failed: {e}")
            return False

    def ensure_connection(self) -> None:
        """
        Monitors health and forces reconnection if needed.
        """
        if not self.soc.sid.connected:
            if not self._is_connecting:
                logger.warning("🔌 Socket disconnected. Attempting RE-CONNECT...")
                self._attempt_connection()
        else:
            # Send keep-alive (re-subscribe to Nifty)
            try:
                XtsSessionManager.call_api(
                    "market",
                    "send_subscription",
                    instruments=[{"exchangeSegment": 1, "exchangeInstrumentID": settings.NIFTY_INSTRUMENT_ID}],
                    xts_message_code=1501,
                )
            except Exception as e:
                logger.error(f"❌ Keep-alive failed: {e}")

    def _on_tick_raw(self, data: dict[str, Any]) -> None:
        self.tick_queue.put(data)

    def _tick_processor_loop(self) -> None:
        while self.is_running:
            data = None
            try:
                data = self.tick_queue.get(timeout=1)
                tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
                if tick:
                    self.last_tick_time = time.time()
                    if self.on_tick_callback:
                        self.on_tick_callback(tick)
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"💥 Error in Live Market Processor: {e}", exc_info=True)
            finally:
                if data is not None:
                    self.tick_queue.task_done()

    def _on_connect(self) -> None:
        logger.info(TradeFormatter.format_connection("connected", "XTS Socket Connected!"))
        if self.subscribed_instruments:
            logger.info(f"🔄 Re-subscribing to {len(self.subscribed_instruments)} instruments...")
            
            def do_resubscribe():
                # Re-subscribe all on reconnect safely in background
                nse_eq = [i for i in self.subscribed_instruments if i in self.nsecm_instruments]
                nse_fo = [i for i in self.subscribed_instruments if i not in self.nsecm_instruments]

                if nse_eq:
                    XtsSessionManager.call_api(
                        "market",
                        "send_subscription",
                        instruments=[{"exchangeSegment": 1, "exchangeInstrumentID": i} for i in nse_eq],
                        xts_message_code=1501,
                    )
                if nse_fo:
                    XtsSessionManager.call_api(
                        "market",
                        "send_subscription",
                        instruments=[{"exchangeSegment": 2, "exchangeInstrumentID": i} for i in nse_fo],
                        xts_message_code=1501,
                    )
            
            # Offload blocking HTTP calls from the socket.io event loop
            import threading
            threading.Thread(target=do_resubscribe, daemon=True).start()

    def _on_disconnect(self) -> None:
        logger.warning(TradeFormatter.format_connection("disconnected", "XTS Socket Disconnected!"))

    def _on_error(self, data: Any) -> None:
        logger.error(TradeFormatter.format_connection("error", f"XTS Socket Error: {data}"))

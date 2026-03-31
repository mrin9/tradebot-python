import argparse
import os
import sys
import threading
import time
from datetime import datetime

# Add project root to path
sys.path.append(os.getcwd())

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.xts.xts_normalizer import XTSNormalizer
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("XTS_Socket_Test")


class XTSSocketTester:
    def __init__(self, store_in_db=False):
        self.store_in_db = store_in_db
        self.db = None
        self.collection_name = "xts_socket_data_collection_test"

        if self.store_in_db:
            self.db = MongoRepository.get_db()
            logger.info("MongoDB Connection initialized for storage.")

        # Hardcode broadcast mode
        settings.XTS_BROADCAST_MODE = "Full"
        logger.info(f"Setting XTS Broadcast Mode: {settings.XTS_BROADCAST_MODE}")

        # Reset socket client to pick up new settings if it was already initialized
        XtsSessionManager._socket_client = None

        self.xt_market = XtsSessionManager._get_market_client()
        self.soc = XtsSessionManager.get_market_data_socket(debug=False)

        self.subscribed_instruments = set()
        self.is_running = threading.Event()

    def _on_connect(self):
        logger.info("✅ Connected to XTS Socket!")
        self._subscribe_all()

    def _on_error(self, data):
        logger.error(f"❌ Socket Error: {data}")

    def _on_disconnect(self):
        logger.warning("⚠️ Socket Disconnected!")

    def _on_message(self, data):
        """Catch-all for any message from the socket."""
        logger.info(f"📥 General Message Received: {data}")

    def _handle_market_event(self, event_code, data):
        """Generic handler for all market events."""
        logger.info(f"🎯 Market Event: {event_code} | Data: {data}")

        tick = XTSNormalizer.normalize_xts_event("1501-json-full", data)
        logger.info(f"✅ Parsed Data: {tick}")

        if self.store_in_db:
            doc = {"xtsEvent": event_code, "rawData": data, "parsedData": tick, "timestamp": datetime.now()}
            try:
                self.db[self.collection_name].insert_one(doc)
            except Exception as e:
                logger.error(f"Failed to store in DB: {e}")

    def _subscribe_all(self):
        """Subscribes to NIFTY Index only."""
        logger.info("🔭 Subscribing to NIFTY Index (26000)...")

        nifty_id = settings.NIFTY_INSTRUMENT_ID
        self.subscribed_instruments.add(nifty_id)

        # Send Subscriptions for common event codes
        logger.info("Sending subscriptions for NIFTY (26000)...")
        # 1501: Touchline/LTP
        response = self.xt_market.send_subscription([{"exchangeSegment": 1, "exchangeInstrumentID": nifty_id}], 1501)
        logger.info(f"📡 Subscription response: {response}")

    def run(self):
        # Setup callbacks
        self.soc.on_connect = self._on_connect
        self.soc.on_error = self._on_error
        self.soc.on_disconnect = self._on_disconnect
        # Enable catch-all to debug missing data
        self.soc.on_message = self._on_message

        # Register handlers for 1501 Full ONLY
        self.soc.on_message1501_json_full = lambda d: self._handle_market_event("1501-full", d)

        # Connect
        logger.info("Connecting to XTS Socket...")
        threading.Thread(target=self.soc.connect, daemon=True).start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping...")
        finally:
            self.soc.sid.disconnect()


def main():
    parser = argparse.ArgumentParser(description="XTS Socket Integration Test")
    parser.add_argument("--store-in-db", action="store_true", help="Store data in MongoDB")

    args = parser.parse_args()

    tester = XTSSocketTester(store_in_db=args.store_in_db)
    tester.run()


if __name__ == "__main__":
    main()

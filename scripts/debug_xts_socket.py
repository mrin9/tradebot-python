import argparse
import logging
import os
import sys
from datetime import datetime

# Standard Path Resolution for local imports
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

import requests
from packages.settings import settings
from packages.xts.MarketDataSocketClient import MDSocket_io

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("XTS_Standalone_Debug")

# Constants
NIFTY_ID = 26000
REDUCED_PRINT_COUNT = 100 

class SimpleXTSRestClient:
    """Minimal XTS REST client for standalone use."""

    def __init__(self, api_key, secret_key, root_url, source):
        self.api_key = api_key
        self.secret_key = secret_key
        self.root = root_url
        self.source = source
        self.token = None
        self.user_id = None

    def login(self):
        url = f"{self.root}/apimarketdata/auth/login"
        payload = {"appKey": self.api_key, "secretKey": self.secret_key, "source": self.source}
        logger.info(f"Logging in to {url}...")
        response = requests.post(url, json=payload, verify=False)
        data = response.json()

        if data.get("type") == "success":
            self.token = data["result"]["token"]
            self.user_id = data["result"]["userID"]
            logger.info(f"Login successful! UserID: {self.user_id}")
            return True
        else:
            logger.error(f"Login failed: {data}")
            return False

    def send_subscription(self, instruments):
        url = f"{self.root}/apimarketdata/instruments/subscription"
        headers = {"Authorization": self.token}
        payload = {"instruments": instruments, "xtsMessageCode": 1501}
        response = requests.post(url, json=payload, headers=headers, verify=False)
        return response.json()

class XTSSocketDebugger:
    def __init__(self, print_mode: str = "all", debug_socket: bool = False):
        self.current_nifty_price = 0.0
        self.subscribed_ids: set[int] = set()
        self.print_mode = print_mode
        self.event_counter = 0

        # Initialize XTS Rest Client using settings
        self.xts_rest = SimpleXTSRestClient(
            settings.MARKET_API_KEY, 
            settings.MARKET_API_SECRET, 
            settings.XTS_ROOT_URL, 
            settings.XTS_SOURCE
        )
        if not self.xts_rest.login():
            raise Exception("Failed to authenticate with XTS")

        # Initialize the production socket client
        self.socket_client = MDSocket_io(
            token=self.xts_rest.token,
            user_id=self.xts_rest.user_id,
            logger=debug_socket,
            engineio_logger=debug_socket,
        )

        # Re-bind events to our instance methods
        sid = self.socket_client.sid
        sid.on("connect", self._on_connect)
        sid.on("disconnect", self._on_disconnect)
        sid.on("error", self._on_error)
        sid.on("1501-json-full", self._on_touchline_message)

    def _on_connect(self):
        logger.info("🟢 Socket Connected successfully!")
        import threading
        threading.Thread(target=self._subscribe_all_test, daemon=True).start()

    def _on_disconnect(self):
        logger.warning("🔴 Socket Disconnected!")

    def _on_error(self, data):
        logger.error(f"❌ Socket Error: {data}")

    def _on_touchline_message(self, data):
        """Handle raw messages from 1501-json-full event."""
        self.event_counter += 1

        should_print = False
        if self.print_mode == "all":
            should_print = True
        elif self.print_mode == "reduced":
            if self.event_counter % REDUCED_PRINT_COUNT == 0:
                should_print = True

        if should_print:
            now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            if self.print_mode == "reduced":
                # Single line summary
                print(f"[{now}] Event #{self.event_counter}: Received message for {len(data) if isinstance(data, list) else 1} instruments", flush=True)
            else:
                # Full debug print
                print(
                    f"\n--- [{now}] RAW MESSAGE RECEIVED (Event #{self.event_counter}) ---\n {data}\n--------------------------\n",
                    flush=True,
                )

    def _subscribe_all_test(self):
        """Standalone test subscription."""
        test_ids = {NIFTY_ID, 533, 557, 342, 132}
        instruments = [
            {"exchangeSegment": 1 if i == NIFTY_ID else 51, "exchangeInstrumentID": int(i)} for i in test_ids
        ]

        logger.info(f"📡 Subscribing to standalone test IDs: {test_ids}")
        response = self.xts_rest.send_subscription(instruments)
        logger.info(f"Subscription Response: {response}")

    def run(self):
        """Start the standalone debugger."""
        logger.info("🚀 Starting Standalone XTS Socket Debugger...")
        try:
            self.socket_client.connect()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Debugger error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Standalone XTS Socket Debugger")
    parser.add_argument(
        "--print-mode", choices=["all", "none", "reduced"], default="all", help="Control raw message printing"
    )
    parser.add_argument("--debug-socket", action="store_true", help="Enable protocol-level logging")

    args = parser.parse_args()

    try:
        debugger = XTSSocketDebugger(print_mode=args.print_mode, debug_socket=args.debug_socket)
        debugger.run()
    except Exception as e:
        logger.error(f"Failed to start: {e}")

import os
import sys
import logging
import requests
import json
from datetime import datetime

# Path resolution to find 'packages'
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from packages.settings import settings
from packages.xts.MarketDataSocketClient import MDSocket_io

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("RelianceTouchline")

class RelianceTouchlineOnly:
    def __init__(self):
        self.reliance_id = 2885
        self.segment = 1 # NSE Equity
        self.token = None
        self.user_id = None

    def login(self):
        """Standard XTS login."""
        url = f"{settings.XTS_ROOT_URL}/apimarketdata/auth/login"
        payload = {
            "appKey": settings.MARKET_API_KEY,
            "secretKey": settings.MARKET_API_SECRET,
            "source": settings.XTS_SOURCE
        }
        try:
            response = requests.post(url, json=payload, verify=False)
            data = response.json()
            
            if data.get("type") == "success":
                self.token = data["result"]["token"]
                self.user_id = data["result"]["userID"]
                return True
        except Exception as e:
            print(f"Login error: {e}")
        return False

    def _on_connect(self):
        """Triggered when socket connects."""
        print(f"[{datetime.now()}] [CONNECTED] Sending subscription for RELIANCE...")
        
        url = f"{settings.XTS_ROOT_URL}/apimarketdata/instruments/subscription"
        headers = {"Authorization": self.token}
        payload = {
            "instruments": [{"exchangeSegment": self.segment, "exchangeInstrumentID": self.reliance_id}],
            "xtsMessageCode": 1501
        }
        requests.post(url, json=payload, headers=headers, verify=False)

    def _on_raw_1501(self, data):
        """Prints the raw 1501 message."""
        now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"\n--- [{now}] RAW 1501 DATA ---\n{data}\n" + "-"*40, flush=True)

    def run(self):
        if not self.login():
            print("[ERROR] Login Failed. Check your .env file or API connectivity.")
            return

        # Start socket
        socket = MDSocket_io(token=self.token, user_id=self.user_id)
        
        # Register events
        socket.sid.on("connect", self._on_connect)
        socket.sid.on("1501-json-full", self._on_raw_1501)

        try:
            print(f"[START] Starting RELIANCE Touchline Debugger...")
            socket.connect()
        except KeyboardInterrupt:
            print("\nStopping...")
        except Exception as e:
            print(f"Socket error: {e}")

if __name__ == "__main__":
    RelianceTouchlineOnly().run()

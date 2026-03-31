"""
Tests for LiveMarketService, verifying socket connection and data subscription.
"""

import os
import sys
import time

# Add project root
sys.path.append(os.getcwd())

from packages.services.live_market import LiveMarketService
from packages.settings import settings
from packages.utils.log_utils import setup_logger

logger = setup_logger("TestStream")


def test_listener():
    """Verifies that the LiveMarketService can connect to the XTS socket and receive ticks."""
    logger.info("Starting Stream Listener Test...")

    ticks_received = 0

    def on_tick(tick):
        nonlocal ticks_received
        ticks_received += 1
        if ticks_received % 10 == 0:
            logger.info(f"Received {ticks_received} ticks. Last: {tick['i']} -> {tick['p']}")

    service = LiveMarketService()

    # Subscribe to Nifty
    service.start(on_tick=on_tick)
    time.sleep(2)  # Wait for socket connection
    service.subscribe([settings.NIFTY_INSTRUMENT_ID])

    logger.info("Listening for 15 seconds...")
    time.sleep(15)

    service.stop()

    logger.info(f"Test Complete. Total Ticks: {ticks_received}")

    assert ticks_received > 0, "No ticks received (Market might be closed or connection issue)."
    logger.info("SUCCESS: Stream received data.")


if __name__ == "__main__":
    test_listener()

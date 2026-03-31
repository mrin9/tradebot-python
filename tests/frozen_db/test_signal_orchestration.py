"""
Tests for the FundManager orchestration, verifying the end-to-end signal flow from tick data to position manager.
"""


import pytest

from packages.settings import settings
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import MarketIntentType as MarketIntent


@pytest.fixture(autouse=True)
def setup_frozen_db():
    """Ensures this test uses the deterministic frozen database."""
    settings.DB_NAME = "tradebot_frozen_test"
    # Reset MongoRepository cache to pickup new settings
    from packages.utils.mongo import MongoRepository

    MongoRepository._client = None
    MongoRepository._db = None


def create_mock_ticks(instrument_id, start_price, count):
    ticks = []
    for i in range(count):
        timestamp = 1000000000 + i * 60  # Use a realistic timestamp
        ticks.append(
            {
                "instrument_id": instrument_id,
                "c": float(start_price + i * 10),
                "o": float(start_price + i * 10),
                "h": float(start_price + i * 10),
                "l": float(start_price + i * 10),
                "v": 100,
                "timestamp": timestamp,
            }
        )
    return ticks


def test_orchestration():
    """
    Simulates a sequence of market data ticks and verifies that FundManager
    correctly triggers a LONG signal when RSI exceeds a threshold.
    """
    # 1. Setup a valid strategy config
    strategy_config = {
        "strategyId": "test-rule",
        "name": "Test Rule",
        "indicators": [
            {"indicatorId": "rsi-14", "displayLabel": "RSI", "type": "RSI", "params": {"period": 14}, "timeframe": 60}
        ],
        "entry": {
            "intent": "AUTO",
            "instrument_kind": "CASH",
            "evaluateSpot": True,
            "evaluateInverse": False,
            "operator": "AND",
            "conditions": [{"type": "threshold", "indicatorId": "rsi_14", "op": ">", "value": 60}],
        },
        "exit": {
            "operator": "AND",
            "conditions": [{"type": "threshold", "indicatorId": "rsi_14", "op": "<", "value": 40}],
        },
    }

    # Mocking the Python strategy so we don't depend on TripleLock's strict EMA requirements
    import os
    import tempfile

    dummy_strategy_code = """
from typing import Dict, Any, Tuple, Optional
from packages.tradeflow.types import CandleType, SignalType, MarketIntentType

class DummyRSIStrategy:
    def on_resampled_candle_closed(self, candle: CandleType, indicators: Dict[str, Any], current_position_intent: Optional[MarketIntentType] = None) -> Tuple[SignalType, str, float]:
        rsi = indicators.get("nifty-rsi-14")
        if rsi is not None and rsi > 70:
            return SignalType.LONG, "RSI > 70", 1.0
        return SignalType.NEUTRAL, "Pass-through", 0.0
"""
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w") as f:
        f.write(dummy_strategy_code)

    position_config = {"python_strategy_path": f"{path}:DummyRSIStrategy", "instrument_type": "CASH"}
    fm = FundManager(strategy_config=strategy_config, position_config=position_config, is_backtest=True)

    signals_received = []
    fm.on_signal = signals_received.append

    # 2. Feed enough data to trigger indicators (Spot ID: 26000)
    start_price = 100
    for i in range(100):
        timestamp = 1000000000 + i * 60  # Use a realistic timestamp
        fm.on_tick_or_base_candle(
            {
                "instrument_id": 26000,
                "c": float(start_price + i * 10),
                "o": float(start_price + i * 10),
                "h": float(start_price + i * 10),
                "l": float(start_price + i * 10),
                "v": 100,
                "timestamp": timestamp,
            }
        )

    # At this point, RSI should be 100 (LONG)
    assert len(signals_received) > 0

    # Verify Signal Label
    sig_data = signals_received[-1]
    assert sig_data["signal"] == MarketIntent.LONG
    assert sig_data["symbol"] == "26000"

    # Clean up the dummy file
    os.remove(path)
    print("FundManager Test Verified: Signal Received.")

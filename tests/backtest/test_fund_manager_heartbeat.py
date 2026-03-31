import logging
from unittest.mock import patch

import pytest

from packages.tradeflow.fund_manager import FundManager


@pytest.fixture
def mock_dependencies():
    with (
        patch("packages.utils.mongo.MongoRepository.get_db") as mock_db,
        patch("packages.utils.log_utils.setup_logger", return_value=logging.getLogger("test_logger")),
    ):
        yield mock_db


def test_fund_manager_heartbeat_count(mock_dependencies, caplog):
    """Verifies that FundManager logs exactly one heartbeat per candle period."""
    caplog.set_level(logging.INFO)

    strategy_config = {
        "timeframe": 180,
        "indicators": [
            {"indicatorId": "fast_ema", "type": "EMA", "params": {"period": 5}, "InstrumentType": "SPOT"},
            {"indicatorId": "ce_ema", "type": "EMA", "params": {"period": 5}, "InstrumentType": "CE"},
            {"indicatorId": "pe_ema", "type": "EMA", "params": {"period": 5}, "InstrumentType": "PE"},
        ],
        "rules": {"entry": [], "exit": []},
    }

    position_config = {"python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"}
    fm = FundManager(strategy_config, position_config=position_config, reduced_log=False, is_backtest=True)
    fm.active_instruments = {"SPOT": 26000, "CE": 45500, "PE": 45501}

    # 1. Simulate SPOT candle close at T=1000 (Period ends at 1000 + 180 = 1180)
    # The resampler will close the candle when it sees a tick for the NEXT period or a flush.

    # Feeding candles to resamplers
    ts = 1000.0
    fm.on_tick_or_base_candle({"i": 26000, "o": 24000, "h": 24100, "l": 23900, "c": 24050, "t": ts})
    fm.on_tick_or_base_candle({"i": 45500, "o": 200, "h": 210, "l": 190, "c": 205, "t": ts})
    fm.on_tick_or_base_candle({"i": 45501, "o": 210, "h": 220, "l": 200, "c": 215, "t": ts})

    # 2. Trigger period close by feeding ticks from the NEXT period (T=1180) for ALL instruments
    caplog.clear()
    fm.on_tick_or_base_candle({"i": 26000, "o": 24060, "c": 24060, "t": 1180.0})
    fm.on_tick_or_base_candle({"i": 45500, "o": 206, "c": 206, "t": 1180.0})
    fm.on_tick_or_base_candle({"i": 45501, "o": 216, "c": 216, "t": 1180.0})

    # Count heartbeats
    heartbeats = [rec.message for rec in caplog.records if "HEARTBEAT" in rec.message]

    # Now we expect exactly 1 heartbeat
    print(f"\nHeartbeats found: {len(heartbeats)}")
    for h in heartbeats:
        print(f"  - {h}")

    assert len(heartbeats) == 1

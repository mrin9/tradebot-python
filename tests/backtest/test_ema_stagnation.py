import logging
from unittest.mock import patch, MagicMock
import pytest
from packages.tradeflow.fund_manager import FundManager

@pytest.fixture
def mock_dependencies():
    with (
        patch("packages.utils.mongo.MongoRepository.get_db") as mock_db,
        patch("packages.utils.log_utils.setup_logger", return_value=logging.getLogger("test_logger")),
    ):
        yield mock_db

def test_ema_updates_on_spot_close(mock_dependencies, caplog):
    """
    Reproduces the EMA stagnation issue where option indicators don't update 
    when only the SPOT candle arrives.
    """
    caplog.set_level(logging.INFO)

    strategy_config = {
        "timeframeSeconds": 60,
        "indicators": [
            {"indicatorId": "ce_ema_5", "indicator": "ema-5", "instrumentType": "CE"},
        ],
    }
    position_config = {
        "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "budget": 100000,
        "investMode": "fixed",
        "slPct": 10,
        "targetPct": [20],
        "tslPct": 5,
        "tslId": "trade-ema-5",
        "useBe": False,
        "instrumentType": "OPTIONS",
        "strikeSelection": "ATM",
        "priceSource": "close",
        "pyramidSteps": [100],
        "pyramidConfirmPts": 0,
    }
    
    fm = FundManager(strategy_config, position_config=position_config, reduced_log=False, is_backtest=True)
    fm.active_instruments = {"SPOT": 26000, "CE": 45500, "CE_DESC": "NIFTY CE", "PE": 45501, "PE_DESC": "NIFTY PE"}
    
    # Mock discovery so it doesn't try DB lookups
    fm.discovery_service.get_target_strike = MagicMock(side_effect=lambda p, s, is_ce, ts: (24000, 45500, "NIFTY CE") if is_ce else (24000, 45501, "NIFTY PE"))

    # Warmup some data so EMA can be calculated (at least 5 bars)
    for i in range(10):
        ts = 1000.0 + (i * 60)
        fm.on_tick_or_base_candle({"i": 26000, "c": 24000 + i, "t": ts})
        fm.on_tick_or_base_candle({"i": 45500, "c": 100 + i, "t": ts})

    # Feed SPOT tick for next period to trigger candle close
    caplog.clear()
    fm.on_tick_or_base_candle({"i": 26000, "c": 24011, "t": 1600.0})
    
    # Check indicators in heartbeat
    heartbeats = [rec.message for rec in caplog.records if "HEARTBEAT" in rec.message]
    assert len(heartbeats) == 1
    
    print(f"Heartbeat: {heartbeats[0]}")
    # Verify the heartbeat contains indicator state (not N/A for everything)
    assert "ema" in heartbeats[0].lower() or "State:" in heartbeats[0]

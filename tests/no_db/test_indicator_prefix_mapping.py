import logging
from unittest.mock import patch, MagicMock
import pytest
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import MarketIntentType

@pytest.fixture
def mock_dependencies():
    with (
        patch("packages.utils.mongo.MongoRepository.get_db") as mock_db,
        patch("packages.utils.log_utils.setup_logger", return_value=logging.getLogger("test_logger")),
    ):
        yield mock_db

def test_explicit_mapping_and_heartbeat(mock_dependencies, caplog):
    """Verifies [TRADED] and trade- indicators in Heartbeat."""
    caplog.set_level(logging.INFO)

    strategy_config = {
        "timeframe": 180,
        "indicators": [
            {"indicator": "ema-5", "InstrumentType": "SPOT"},
            {"indicator": "ema-5", "InstrumentType": "OPTIONS_BOTH"},
        ],
    }

    position_config = {"python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"}
    fm = FundManager(strategy_config, position_config=position_config, reduced_log=False, is_backtest=True)
    fm.position_manager.update_tick = MagicMock()
    
    # Mock contract discovery so it doesn't overwrite our test instruments
    fm.discovery_service.get_atm_strike = MagicMock(return_value=24000)
    fm.discovery_service.resolve_option_contract = MagicMock(side_effect=[
        (45500, "NIFTY_ATM_CE"), # CE
        (45501, "NIFTY_ATM_PE"), # PE
        (45500, "NIFTY_ATM_CE"), # CE Match case
        (45501, "NIFTY_ATM_PE")  # PE Match case
    ])
    
    # Set ATM instruments
    fm.active_instruments = {
        "SPOT": 26000, 
        "CE": 45500, "CE_DESC": "NIFTY_ATM_CE",
        "PE": 45501, "PE_DESC": "NIFTY_ATM_PE"
    }

    # 1. Simulate an open position in a DRIFTED instrument (45600)
    mock_pos = MagicMock()
    mock_pos.symbol = "45600"
    mock_pos.display_symbol = "NIFTY_DRIFTED_CE"
    mock_pos.intent = MarketIntentType.LONG
    mock_pos.entry_timestamp = 900.0  # Before current ts
    fm.position_manager.current_position = mock_pos

    # 2. Feed ticks for SPOT, ATM_CE, ATM_PE, and TRADED_CE
    ts = 1000.0
    fm.on_tick_or_base_candle({"i": 26000, "c": 24000, "t": ts})
    fm.on_tick_or_base_candle({"i": 45500, "c": 100, "t": ts})
    fm.on_tick_or_base_candle({"i": 45501, "c": 110, "t": ts})
    fm.on_tick_or_base_candle({"i": 45600, "c": 150, "t": ts})

    # 3. Trigger period close
    caplog.clear()
    fm.on_tick_or_base_candle({"i": 26000, "c": 24010, "t": 1180.0})
    
    # 4. Inspect logs
    heartbeats = [rec.message for rec in caplog.records if "HEARTBEAT" in rec.message]
    assert len(heartbeats) >= 1
    hb = heartbeats[0]
    
    print(f"Log Output: {hb}")
    
    # Verify trade marker and ATM info
    assert "trade: NIFTY_DRIFTED_CE" in hb
    assert "active: NIFTY_ATM_CE" in hb
    assert "inverse: NIFTY_ATM_PE" in hb
    
    # Verify trade- indicators are present
    assert "trade-ema-5" in hb
    # Verify active- indicators are also present (ATM)
    assert "active-ema-5" in hb
    
    # 5. Test [TRADED/ATM] when they match
    mock_pos.symbol = "45500"
    mock_pos.display_symbol = "NIFTY_ATM_CE"
    caplog.clear()
    fm.on_tick_or_base_candle({"i": 26000, "c": 24020, "t": 1360.0}) # Trigger next candle
    
    hb_atm = [rec.message for rec in caplog.records if "HEARTBEAT" in rec.message][0]
    print(f"Log (Match): {hb_atm}")
    assert "trade: NIFTY_ATM_CE" in hb_atm
    assert "active: NIFTY_ATM_CE" in hb_atm

if __name__ == "__main__":
    pytest.main([__file__])

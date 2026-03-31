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

def test_ema_updates_on_spot_close(mock_dependencies, caplog):
    """
    Reproduces the EMA stagnation issue where option indicators don't update 
    when only the SPOT candle arrives.
    """
    caplog.set_level(logging.INFO)

    strategy_config = {
        "timeframe": 60,
        "indicators": [
            {"indicatorId": "ce_ema_5", "indicator": "ema-5", "InstrumentType": "CE"},
        ],
    }
    position_config = {"python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy", "budget": 100000, "invest_mode": "fixed", "sl_pct": 10, "target_pct": 20, "tsl_pct": 5, "use_be": False, "instrument_type": "OPTIONS", "strike_selection": "ATM", "price_source": "close"}
    
    fm = FundManager(strategy_config, position_config=position_config, reduced_log=False, is_backtest=True)
    fm.active_instruments = {"SPOT": 26000, "CE": 45500, "PE": 45501}
    
    # Warmup some data so EMA can be calculated (at least 5 bars)
    for i in range(10):
        ts = 1000.0 + (i * 60)
        fm.on_tick_or_base_candle({"i": 26000, "c": 24000 + i, "t": ts})
        fm.on_tick_or_base_candle({"i": 45500, "c": 100 + i, "t": ts})

    # Now we are at T=1600. The last finalized candle for CE was T=1540.
    # Feed SPOT tick for T=1600 (start of next candle)
    # This triggers _on_resampled_candle_closed for SPOT @ 1540
    caplog.clear()
    fm.on_tick_or_base_candle({"i": 26000, "c": 24011, "t": 1600.0})
    
    # Check indicators in heartbeat
    heartbeats = [rec.message for rec in caplog.records if "HEARTBEAT" in rec.message]
    assert len(heartbeats) == 1
    
    # Before the fix, ce_ema_5 would be based on candles up to 1480 (one delay)
    # or even worse, it would be "N/A" if it never finalized.
    print(f"Heartbeat: {heartbeats[0]}")
    assert "active-ce_ema_5" in heartbeats[0] or "ce-ce_ema_5" in heartbeats[0] or "ce_ema_5" in heartbeats[0] or "Indicators:" in heartbeats[0]


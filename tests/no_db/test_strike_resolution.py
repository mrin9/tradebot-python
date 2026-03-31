import pytest
from unittest.mock import MagicMock
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import InstrumentCategoryType

def test_strike_resolution_on_every_candle():
    """
    Verifies that FundManager updates active_instruments (CE/PE) on every SPOT candle close,
    even when no position is open.
    """
    # 1. Setup Mocks
    mock_discovery = MagicMock()
    # Return different IDs for different strikes to verify update
    def mock_get_target_strike(spot_price, selection, is_ce, ts, symbol="NIFTY", series="OPTIDX"):
        strike = round(spot_price / 50) * 50
        suffix = "CE" if is_ce else "PE"
        return strike, int(strike), f"NIFTY-{strike}-{suffix}"

    mock_discovery.get_target_strike.side_consequential = mock_get_target_strike
    mock_discovery.get_target_strike.side_effect = mock_get_target_strike
    
    # Mock position config
    pos_config = {
        "symbol": "NIFTY",
        "quantity": 1,
        "strike_selection": "ATM",
        "instrument_type": "OPTIONS",
        "budget": "3-lots"
    }
    
    # Create FundManager with mocked services
    fm = FundManager(
        strategy_config={"strategyId": "test"},
        position_config=pos_config,
        discovery_service=mock_discovery,
        is_backtest=True
    )
    # Mock indicator calculator to return a safe dict (all Nones/Zeros)
    fm.indicator_calculator = MagicMock()
    fm.indicator_calculator.get_indicators.return_value = {}
    
    # 2. Feed first SPOT candle (ATM 22000)
    # End of first 3-min candle (09:15-09:18)
    ts1 = 1711251900.0 # 2024-03-24 09:15:00 UTC
    candle1 = {"i": 26000, "t": ts1, "c": 22010} # 22010 rounds to 22000
    
    fm.on_tick_or_base_candle(candle1)
    
    # Force a candle close by sending a later tick
    # (Since global_timeframe is 180s, sending 09:18:01 will flush the 09:15-09:18 candle)
    ts2 = ts1 + 181
    fm.on_tick_or_base_candle({"i": 26000, "t": ts2, "c": 22020})
    
    # Verify strike resolution happened for 22000
    assert fm.active_instruments["CE"] == 22000
    assert fm.active_instruments["PE"] == 22000
    assert fm.position_manager.current_position is None
    

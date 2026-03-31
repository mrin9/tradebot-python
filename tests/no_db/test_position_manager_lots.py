import pytest
from datetime import datetime
from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import InstrumentKindType, MarketIntentType

def test_lot_calculation_minimum_rule():
    # 3 lots, 3 targets -> 4 steps total. 
    # calculated_qty = 3 / 4 = 0.75 -> Rule: min 1 lot.
    pm = PositionManager(
        symbol="NIFTY-TEST",
        quantity=3,
        sl_pct=2.0,
        target_pct="2,3,4",
        instrument_type=InstrumentKindType.OPTIONS
    )
    
    # Open position
    pm._open_position(
        intent=MarketIntentType.LONG,
        price=100.0,
        timestamp=datetime.now(),
        symbol="NIFTY-TEST"
    )
    
    pos = pm.current_position
    assert pos.remaining_quantity == 3
    
    # Hit Target 1 (102.0)
    pm.update_tick({"c": 102.0, "t": datetime.now().timestamp() + 1})
    # Should sell 1 lot (min 1)
    assert len(pm.trades_history) == 1
    assert pm.trades_history[0].initial_quantity == 1
    assert pos.remaining_quantity == 2
    
    # Hit Target 2 (103.0)
    pm.update_tick({"c": 103.0, "t": datetime.now().timestamp() + 2})
    # Should sell 1 lot (min 1)
    assert len(pm.trades_history) == 2
    assert pm.trades_history[1].initial_quantity == 1
    assert pos.remaining_quantity == 1

    # Hit Target 3 (104.0)
    pm.update_tick({"c": 104.0, "t": datetime.now().timestamp() + 3})
    # Should sell 1 lot (min 1). Total exhausted.
    assert len(pm.trades_history) == 3 # Exactly 3 targets
    assert pm.trades_history[2].initial_quantity == 1
    assert pm.current_position is None

def test_lot_calculation_flooring_rule():
    # 7 lots, 2 targets -> 3 steps total.
    # calculated_qty = 7 / 3 = 2.33 -> Rule: floor to 2.
    pm = PositionManager(
        symbol="NIFTY-TEST",
        quantity=7,
        sl_pct=2.0,
        target_pct="2,3",
        instrument_type=InstrumentKindType.OPTIONS
    )
    
    pm._open_position(
        intent=MarketIntentType.LONG,
        price=100.0,
        timestamp=datetime.now(),
        symbol="NIFTY-TEST"
    )
    # Target 1: 102.0, Target 2: 103.0
    
    # Hit Target 1
    pm.update_tick({"c": 102.0, "t": datetime.now().timestamp() + 1})
    assert len(pm.trades_history) == 1
    assert pm.trades_history[0].initial_quantity == 2 # 7/3=2.33 -> 2
    
    # Hit Target 2
    pm.update_tick({"c": 103.0, "t": datetime.now().timestamp() + 2})
    assert len(pm.trades_history) == 2
    assert pm.trades_history[1].initial_quantity == 2
    
    # Final Exit (Manual or SL/Signal)
    pm._close_position(104.0, datetime.now(), "SIGNAL_EXIT")
    assert len(pm.trades_history) == 3
    assert pm.trades_history[2].initial_quantity == 3 # 7 - 2 - 2 = 3

def test_lot_calculation_exhaustion_at_target_1():
    # 1 lot, 3 targets -> 4 steps.
    # calc = 1 / 4 = 0.25 -> 1 lot.
    pm = PositionManager(
        symbol="NIFTY-TEST",
        quantity=1,
        sl_pct=2.0,
        target_pct="2,3,4",
        instrument_type=InstrumentKindType.OPTIONS
    )
    
    pm._open_position(
        intent=MarketIntentType.LONG,
        price=100.0,
        timestamp=datetime.now(),
        symbol="NIFTY-TEST"
    )
    
    # Hit Target 1
    pm.update_tick({"c": 102.0, "t": datetime.now().timestamp() + 1})
    # Should sell 1 lot and then exhaust.
    assert len(pm.trades_history) == 1
    assert pm.trades_history[0].initial_quantity == 1
    assert pm.current_position is None

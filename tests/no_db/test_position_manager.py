"""
Tests for the PositionManager, verifying trade lifecycle, pnl, and risk controls.
"""

from datetime import datetime, timedelta

import pytest

from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import InstrumentKindType as InstrumentType
from packages.tradeflow.types import MarketIntentType as MarketIntent


class MockOrderManager:
    def __init__(self):
        self.orders = []

    def place_order(self, symbol, side, qty, order_type="MARKET", price=0.0, timestamp=None):
        self.last_order = {"symbol": symbol, "side": side, "qty": qty, "timestamp": timestamp}
        self.orders.append(self.last_order)
        return {"status": "FILLED", "order_id": "MOCK-1"}


@pytest.fixture
def pm_setup():
    om = MockOrderManager()
    pm = PositionManager(
        symbol="NIFTY", quantity=50, sl_pct=20.0, target_pct=[40.0, 80.0], instrument_type=InstrumentType.OPTIONS
    )
    pm.set_order_manager(om)
    return pm, om


def test_options_long_intent_cycle(pm_setup):
    """Tests LONG intent (Buy Call) cycle for Options using state-based assertions."""
    pm, om = pm_setup

    # 1. Entry
    now = datetime(2026, 2, 11, 9, 30)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    assert pm.current_position is not None
    assert pm.current_position.intent == MarketIntent.LONG
    assert pm.current_position.entry_price == 100.0
    assert om.orders[0]["side"] == "BUY"

    # 2. Break-Even & Target 1
    # Quantity is 50. Target 1 hit -> some quantity sold.
    pm.update_tick({"ltp": 141.0, "timestamp": now.timestamp() + 180})  # +3 mins
    assert pm.current_position.stop_loss == 100.0
    assert pm.current_position.achieved_targets == 1
    assert len(pm.trades_history) == 1

    # 3. Exit via Signal Flip
    from datetime import timedelta

    exit_time = now + timedelta(minutes=15)
    pm.on_signal(
        {
            "signal": MarketIntent.SHORT,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 120.0,
            "timestamp": exit_time,
        }
    )

    assert pm.current_position is None
    assert len(pm.trades_history) == 2
    assert pm.trades_history[1].status == "SIGNAL_EXIT"
    assert pm.session_realized_pnl > 0


def test_options_short_intent_entry(pm_setup):
    """Tests SHORT intent (Buy Put) for Options."""
    pm, om = pm_setup
    pm.on_signal(
        {
            "signal": MarketIntent.SHORT,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime(2026, 2, 11, 9, 30),
        }
    )
    assert om.orders[0]["side"] == "BUY"  # Long the Put contract
    assert pm.current_position.intent == MarketIntent.SHORT


def test_cash_long_cycle(pm_setup):
    """Tests LONG cycle for Cash."""
    pm, om = pm_setup
    pm.instrument_type = InstrumentType.CASH
    pm.on_signal(
        {
            "signal": MarketIntent.LONG,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 1000.0,
            "timestamp": datetime(2026, 2, 11, 9, 30),
        }
    )
    assert om.orders[0]["side"] == "BUY"


def test_fractional_exit(pm_setup):
    """Verifies that 1/(N+1) remains open after N targets are hit using state assertions."""
    pm, _om = pm_setup
    # Setup: 3 targets, initial qty 100. Chunk size = 100 // 4 = 25.
    pm.quantity = 100
    pm.target_pct_steps = [10.0, 20.0, 30.0]
    now = datetime(2026, 2, 11, 9, 30)

    # 1. Entry at 100. Targets: 110, 120, 130
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    # 2. Hit Target 1 (110)
    pm.update_tick({"ltp": 110.0, "timestamp": now.timestamp() + 60})
    assert pm.current_position.remaining_quantity == 75

    # 3. Hit Target 2 (120)
    pm.update_tick({"ltp": 120.0, "timestamp": now.timestamp() + 120})
    assert pm.current_position.remaining_quantity == 50

    # 4. Hit Target 3 (130)
    pm.update_tick({"ltp": 130.0, "timestamp": now.timestamp() + 180})

    # Position should still be OPEN with 25 quantity (1/4th)
    assert pm.current_position is not None
    assert pm.current_position.remaining_quantity == 25
    assert pm.current_position.achieved_targets == 3
    assert len(pm.trades_history) == 3


def test_cash_short_blocking(pm_setup):
    """Verifies that SHORT intent is blocked for CASH/FUTURES."""
    pm, om = pm_setup
    pm.instrument_type = InstrumentType.CASH
    pm.on_signal(
        {
            "signal": MarketIntent.SHORT,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 1000.0,
            "timestamp": datetime(2026, 2, 11, 9, 30),
        }
    )

    assert pm.current_position is None
    assert len(om.orders) == 0


def test_pyramid_default_100_behaves_like_all_in(pm_setup):
    """pyramid_steps=[100] should enter full quantity on first signal."""
    pm, om = pm_setup
    pm.quantity = 100
    pm.pyramid_steps = [100]

    now = datetime(2026, 2, 11, 9, 30)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    assert pm.current_position is not None
    assert pm.current_position.remaining_quantity == 100
    assert om.orders[0]["qty"] == 100


def test_pyramid_staged_entry(pm_setup):
    """pyramid_steps=[25,50,25] should enter 25% first, then add 50% and 25% on confirmation."""
    pm, om = pm_setup
    pm.quantity = 100
    pm.pyramid_steps = [25, 50, 25]
    pm.pyramid_confirm_pts = 10.0

    now = datetime(2026, 2, 11, 9, 30)

    # Step 1: Initial entry → 25% of 100 = 25 lots
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )
    assert pm.current_position.remaining_quantity == 25
    assert pm.current_position.pyramid_step == 0
    assert om.orders[0]["qty"] == 25

    # Same-direction signal but price NOT confirmed (only +5, need +10)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 105.0, "timestamp": now}
    )
    assert pm.current_position.remaining_quantity == 25  # No change

    # Step 2: Same-direction signal WITH confirmation (+15 pts) → 50% of 100 = 50 lots
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 115.0, "timestamp": now}
    )
    assert pm.current_position.remaining_quantity == 75  # 25 + 50
    assert pm.current_position.pyramid_step == 1
    assert om.orders[-1]["qty"] == 50

    # Step 3: Final step → 25% of 100 = 25 lots
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 130.0, "timestamp": now}
    )
    assert pm.current_position.remaining_quantity == 100
    assert pm.current_position.pyramid_step == 2


def test_indicator_based_tsl(pm_setup):
    """Verifies that indicator-based TSL triggers only after profit."""
    pm, _om = pm_setup
    pm.tsl_id = "active-ema-5"
    pm.tsl_pct = 0.0  # ONLY Indicator-based
    now = datetime(2026, 2, 11, 9, 30)

    # 1. Entry at 100. Target 1 is at 140.0
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    # 2. Price in loss (95), EMA-5 is 90. No trigger (pnl <= 0 and T1 not hit)
    pm.update_tick({"ltp": 95.0, "timestamp": now.timestamp() + 60}, indicators={"active-ema-5": 90.0})
    assert pm.current_position is not None

    # 3. Price in profit (115), but T1 (140) not hit. EMA-5 is 110. No trigger!
    pm.update_tick({"ltp": 115.0, "timestamp": now.timestamp() + 120}, indicators={"active-ema-5": 110.0})
    assert pm.current_position is not None

    # 4. Price hits Target 1 at 140. TSL now active.
    pm.update_tick({"ltp": 140.0, "timestamp": now.timestamp() + 150}, indicators={"active-ema-5": 130.0})
    assert pm.current_position is not None
    assert pm.current_position.achieved_targets == 1

    # 5. Price falls below EMA-5 (138) while EMA-5 is 142. TRIGGER EXIT!
    pm.update_tick({"ltp": 138.0, "timestamp": now.timestamp() + 180}, indicators={"active-ema-5": 142.0})
    assert pm.current_position is None
    assert pm.trades_history[-1].status == "TSL_ID"
    assert "active-ema-5: 142.00" in pm.trades_history[-1].exit_reason_description

def test_trade_start_time_guard(pm_setup):
    """Verifies that signals before TRADE_START_TIME are ignored."""
    pm, om = pm_setup
    
    # 1. Signal at 09:15 (should be IGNORED if guard is 09:20)
    early_time = datetime(2026, 2, 11, 9, 15)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": early_time}
    )
    assert pm.current_position is None
    assert len(om.orders) == 0

    # 2. Signal at 09:25 (should be ACCEPTED)
    valid_time = datetime(2026, 2, 11, 9, 25)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": valid_time}
    )
    assert pm.current_position is not None
    assert om.orders[0]["timestamp"] == valid_time

def test_exact_price_execution(pm_setup):
    """Verifies that SL exits at actual breach price and targets exit at actual hit price."""
    pm, _om = pm_setup
    now = datetime(2026, 2, 11, 9, 30)

    # 1. Entry at 100. Stop Loss at 80 (20% SL)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    # 2. Tick arrives with Low 75.0 (breaches SL 80.0). 
    # Exits at actual breach price 75.0 (market-order reality)
    pm.update_tick({"l": 75.0, "c": 76.0, "timestamp": now.timestamp() + 60})
    assert pm.current_position is None
    assert pm.trades_history[-1].exit_price == 75.0
    assert pm.trades_history[-1].status == "STOP_LOSS"
    # 3. New Trade for Target verification
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now + timedelta(minutes=5)}
    )
    # Target 1 is at 140.0. Tick arrives with High 150.0.
    # Should exit at 150.0, not 140.0
    pm.update_tick({"h": 150.0, "c": 145.0, "timestamp": now.timestamp() + 600})
    assert pm.trades_history[-1].exit_price == 150.0
    assert "TARGET_1" in pm.trades_history[-1].status or pm.trades_history[-1].status == "EXIT"

def test_ignore_zero_tick(pm_setup):
    """Verifies that ticks with 0.0 High/Low are ignored to prevent bad-data triggers."""
    pm, _om = pm_setup
    now = datetime(2026, 2, 11, 9, 30)

    # 1. Entry at 100. SL at 80.
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 100.0, "timestamp": now}
    )

    # 2. MALFORMED TICK arrives with Low 0.0. 
    # Should NOT trigger STOP_LOSS because 0.0 is an anomaly.
    pm.update_tick({"l": 0.0, "c": 95.0, "timestamp": now.timestamp() + 60})
    assert pm.current_position is not None  # Position remains open
    assert pm.current_position.status == "OPEN"

    # 3. Valid tick at 75.0 (legit move). Should trigger SL.
    pm.update_tick({"l": 75.0, "c": 76.0, "timestamp": now.timestamp() + 120})
    assert pm.current_position is None
    assert pm.trades_history[-1].exit_price == 75.0

def test_ignore_zero_entry(pm_setup):
    """Verifies that entry signals with 0.0 price are ignored."""
    pm, om = pm_setup
    now = datetime(2026, 2, 11, 9, 30)
    pm.on_signal(
        {"signal": MarketIntent.LONG, "symbol": "NIFTY", "display_symbol": "NIFTY", "price": 0.0, "timestamp": now}
    )
    assert pm.current_position is None
    assert len(om.orders) == 0

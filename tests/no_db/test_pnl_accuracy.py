from datetime import datetime

import pytest

from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import InstrumentKindType as InstrumentType
from packages.tradeflow.types import MarketIntentType as MarketIntent


def test_pnl_currency_accuracy():
    """
    Specifically verifies that PnL is calculated as (price_diff * quantity * lot_size).
    For NIFTY, lot_size is 65.
    """
    pm = PositionManager(
        symbol="NIFTY",
        quantity=10,  # 10 lots
        sl_pct=20,
        target_pct=[50],
        instrument_type=InstrumentType.OPTIONS,
    )

    # 1. Entry at 100 (LONG/CE)
    pm.on_signal(
        {
            "signal": MarketIntent.LONG,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime.now(),
        }
    )

    # 2. Update price to 110 (+10 points)
    # Expected PnL: 10 points * 10 lots * 65 = 6500
    pm.update_tick({"ltp": 110.0, "timestamp": datetime.now().timestamp()})

    assert pm.current_position.pnl == 10 * 10 * 65
    assert pm.current_position.pnl == 6500.0

    # 3. Partially exit on target hit
    # Target 1: 100 + 50 = 150
    pm.update_tick({"ltp": 150.0, "timestamp": datetime.now().timestamp()})

    # Fractional exit: 10 // 2 = 5 lots
    # Target 1 realized PnL: 50 * 5 * 65 = 16250
    assert pm.current_position.total_realized_pnl == 16250.0
    assert pm.session_realized_pnl == 16250.0
    assert pm.current_position.remaining_quantity == 5

    # 4. Final exit at 160
    # Additional realized PnL: (160 - 100) * 5 * 65 = 19500
    # Total Cycle PnL: 16250 + 19500 = 35750
    pm._close_position(160.0, datetime.now(), "FINAL_EXIT")

    assert sum(t.pnl for t in pm.trades_history) == 35750.0
    assert pm.session_realized_pnl == 35750.0


def test_pnl_session_carryover():
    """Verifies that PnL carries over across multiple independent trades."""
    pm = PositionManager(
        symbol="NIFTY", quantity=10, sl_pct=20, target_pct=[50], instrument_type=InstrumentType.OPTIONS
    )

    # Trade 1: Profit 1000
    pm.on_signal(
        {
            "signal": MarketIntent.LONG,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime.now(),
        }
    )
    # (101.53846 - 100) * 10 * 65 = 1000
    pm._close_position(101.53846, datetime.now(), "TAKE_PROFIT")
    assert pm.session_realized_pnl == pytest.approx(1000.0, abs=0.1)

    # Trade 2: Loss 500
    pm.on_signal(
        {
            "signal": MarketIntent.SHORT,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime.now(),
        }
    )
    # (99.23077 - 100) * 10 * 65 = -500
    pm._close_position(99.23077, datetime.now(), "STOP_LOSS")

    # Session PnL should be 1000 - 500 = 500
    assert pm.session_realized_pnl == pytest.approx(500.0, abs=0.1)


def test_short_pnl_accuracy():
    """Verifies PnL math for SHORT/PE positions (Buy Put - Long Option Dir)."""
    pm = PositionManager(
        symbol="NIFTY", quantity=10, sl_pct=20, target_pct=[50], instrument_type=InstrumentType.OPTIONS
    )

    # LONG Option position (expect price to rise for Put contract)
    pm.on_signal(
        {
            "signal": MarketIntent.SHORT,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime.now(),
        }
    )

    # Price rises to 110 (+10 pts profit)
    pm.update_tick({"ltp": 110.0, "timestamp": datetime.now().timestamp()})
    assert pm.current_position.pnl == 10 * 10 * 65  # 6500 profit

    # Price drops to 90 (-10 pts loss)
    pm.update_tick({"ltp": 90.0, "timestamp": datetime.now().timestamp()})
    assert pm.current_position.pnl == -10 * 10 * 65  # -6500 loss


def test_intra_candle_sl_hit():
    """
    Verifies that update_tick catches SL/TSL hits based on High/Low even if the
    Close is safe. This is critical for DB-mode backtest fidelity.
    """
    pm = PositionManager(
        symbol="NIFTY", quantity=1, sl_pct=15, target_pct=[], instrument_type=InstrumentType.OPTIONS
    )

    # Entry at 100. SL is 85.
    pm.on_signal(
        {
            "signal": MarketIntent.LONG,
            "symbol": "NIFTY",
            "display_symbol": "NIFTY",
            "price": 100.0,
            "timestamp": datetime.now(),
        }
    )

    # Simulate a 1-minute candle:
    # Open: 100, High: 105, Low: 80 (Hits SL!), Close: 95 (Safe)
    pm.update_tick({"o": 100.0, "h": 105.0, "l": 80.0, "c": 95.0, "timestamp": datetime.now().timestamp()})

    # Should be closed
    assert pm.current_position is None
    assert pm.trades_history[-1].status == "STOP_LOSS"
    assert pm.trades_history[-1].exit_price == 85.0  # SL hit at 85

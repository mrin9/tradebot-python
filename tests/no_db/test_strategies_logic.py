from datetime import datetime
import pytz
from packages.tradeflow.python_strategies import EmaCrossWithRsiStrategy, TripleLockStrategy
from packages.tradeflow.types import MarketIntentType, SignalType


def test_triple_lock_call_entry():
    """Verifies LONG signal when CE crosses over and confirmations align."""
    strategy = TripleLockStrategy()

    # Mock candle (minimal required fields)
    candle = {"c": 22500, "t": 1710820800}

    # 1. Setup indicators for a crossover
    # CE: 99 -> 101 vs Slow: 100
    indicators = {
        "ce-ema-5-prev": 99,
        "ce-ema-21-prev": 100,
        "ce-ema-5": 101,
        "ce-ema-21": 100,
        # Confirmations
        "pe-ema-5": 90,
        "pe-ema-21": 110,
        "pe-ema-5-prev": 95,
        "pe-ema-21-prev": 110,
        "nifty-ema-5": 22505,
        "nifty-ema-21": 22500,
    }

    signal, reason, conf = strategy.on_resampled_candle_closed(candle, indicators)

    assert signal == SignalType.LONG
    assert "Triple Lock CALL Entry" in reason
    assert conf == 1.0


def test_triple_lock_call_exit():
    """Verifies EXIT signal when CE crosses under."""
    strategy = TripleLockStrategy()
    candle = {"c": 22500, "t": 1710820800}

    # Setup indicators for a crossunder
    # CE: 101 -> 99 vs Slow: 100
    indicators = {
        "ce-ema-5-prev": 101,
        "ce-ema-21-prev": 100,
        "ce-ema-5": 99,
        "ce-ema-21": 100,
        # Other indicators non-None for warmup check
        "pe-ema-5": 110,
        "pe-ema-21": 100,
        "pe-ema-5-prev": 110,
        "pe-ema-21-prev": 100,
        "nifty-ema-5": 22500,
        "nifty-ema- slow": 22500,
        "nifty-ema-21": 22500,
    }

    # Current position is LONG
    signal, reason, _conf = strategy.on_resampled_candle_closed(
        candle, indicators, current_position_intent=MarketIntentType.LONG
    )

    assert signal == SignalType.EXIT
    assert "CALL Crossunder Exit" in reason


def test_ema_cross_entry():
    """Verifies EmaCrossWithRsiStrategy entry signals."""
    strategy = EmaCrossWithRsiStrategy()
    # 09:30 AM IST
    candle = {"c": 100, "t": 1710820800}

    # CE crossover
    indicators = {
        "active-ema-5-prev": 10,
        "active-ema-21-prev": 11,
        "active-ema-5": 12,
        "active-ema-21": 11,
        "active-rsi-14": 55,
        # Other side warmup
        "pe-ema-3": 5,
        "pe-ema-21": 6,
        "pe-ema-3-prev": 5,
        "pe-ema-21-prev": 6,
    }


    signal, _, _ = strategy.on_resampled_candle_closed(candle, indicators)
    assert signal == SignalType.LONG


def test_triple_lock_start_time_guard():
    """Verifies NEUTRAL signal before TRADE_START_TIME even if indicators align."""
    from packages.settings import settings
    strategy = TripleLockStrategy()
    
    # 09:18 AM IST on 19-Mar-2026
    # Marketplace timezone is Asia/Kolkata
    tz = pytz.timezone(settings.MARKET_TIMEZONE)
    dt = datetime(2026, 3, 19, 9, 18, 0)
    dt = tz.localize(dt)
    ts = dt.timestamp()
    
    candle = {"c": 22500, "t": ts}
    
    # Indicators aligned for LONG (CE crossover)
    indicators = {
        "ce-ema-5-prev": 99,
        "ce-ema-21-prev": 100,
        "ce-ema-5": 101,
        "ce-ema-21": 100,
        "pe-ema-5": 90,
        "pe-ema-21": 110,
        "pe-ema-5-prev": 95,
        "pe-ema-21-prev": 110,
        "nifty-ema-5": 22505,
        "nifty-ema-21": 22500,
        "meta-is-warming-up": False
    }

    # settings.TRADE_START_TIME is "09:20:00"
    signal, reason, _ = strategy.on_resampled_candle_closed(candle, indicators)
    
    assert signal == SignalType.NEUTRAL
    assert "BEFORE START TIME" in reason
    assert "09:20:00" in reason


def test_triple_lock_continuity_start_time_guard():
    """Verifies NEUTRAL signal for Continuity entry BEFORE TRADE_START_TIME."""
    from packages.settings import settings
    strategy = TripleLockStrategy()
    
    # 1. State: Previously warming up
    strategy.was_warming_up = True
    
    # 2. Time: 09:18 AM IST (Before 09:20)
    tz = pytz.timezone(settings.MARKET_TIMEZONE)
    dt = tz.localize(datetime(2026, 3, 19, 9, 18, 0))
    candle = {"c": 22500, "t": dt.timestamp()}
    
    # 3. Indicators: Aligned for Continuity (Already above EMA, but just finished warmup)
    indicators = {
        "ce-ema-5-prev": 105, # ALREADY ABOVE
        "ce-ema-21-prev": 100,
        "ce-ema-5": 106,
        "ce-ema-21": 100,
        "pe-ema-5": 90,
        "pe-ema-21": 110,
        "pe-ema-5-prev": 90,
        "pe-ema-21-prev": 110,
        "nifty-ema-5": 22505,
        "nifty-ema-21": 22500,
        "meta-is-warming-up": False # Transitions was_warming_up to False
    }

    signal, reason, _ = strategy.on_resampled_candle_closed(candle, indicators)
    
    # Should be NEUTRAL because of Start Time, even if it's a first live candle with meeting conditions!
    assert signal == SignalType.NEUTRAL
    assert "BEFORE START TIME" in reason
    assert strategy.was_warming_up is False # Transition still happens

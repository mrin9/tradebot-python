import time
from datetime import datetime, timedelta
import pytest
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.python_strategies import TripleLockStrategy
from packages.tradeflow.types import InstrumentCategoryType, SignalType

def test_gap_induced_crossover_ignored():
    """
    Verifies that a crossover induced by a market gap (previous candle from yesterday)
    is ignored by both IndicatorCalculator and TripleLockStrategy.
    """
    # Set start time early for the test
    from packages.settings import settings
    original_start = settings.TRADE_START_TIME
    settings.TRADE_START_TIME = "09:00:00"

    try:
        # NOTE: InstrumentType must be uppercase to match IndicatorCalculator logic
        config = [
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "CE"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "CE"},
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "PE"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "PE"},
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "SPOT"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "SPOT"},
        ]
        calc = IndicatorCalculator(indicators_config=config, max_window_size=100)
        strategy = TripleLockStrategy()

        # Yesterday's Timestamps (15:00)
        yesterday_dt = datetime(2025, 5, 20, 15, 0, 0)
        yesterday_base = int(yesterday_dt.timestamp())
        
        # 1. Feed 100 candles for yesterday to stabilize EMAs in a BEARISH state for CE
        for i in range(100):
            ts = yesterday_base + i * 60
            calc.add_candle({"c": 100, "t": ts}, instrument_category=InstrumentCategoryType.CE, instrument_id=101)
            calc.add_candle({"c": 110, "t": ts}, instrument_category=InstrumentCategoryType.PE, instrument_id=102)
            calc.add_candle({"c": 24000, "t": ts}, instrument_category=InstrumentCategoryType.SPOT, instrument_id=26000)

        # 2. Today's Gap Up (09:15)
        today_dt = yesterday_dt + timedelta(days=1)
        today_dt = today_dt.replace(hour=9, minute=15)
        today_base = int(today_dt.timestamp())
        
        # Add candles for all categories
        calc.add_candle({"c": 150, "t": today_base}, instrument_category=InstrumentCategoryType.CE, instrument_id=101)
        calc.add_candle({"c": 80, "t": today_base}, instrument_category=InstrumentCategoryType.PE, instrument_id=102)
        calc.add_candle({"c": 24200, "t": today_base}, instrument_category=InstrumentCategoryType.SPOT, instrument_id=26000)
        
        all_indicators = {}
        all_indicators.update(calc.extract_indicators(101, InstrumentCategoryType.CE))
        all_indicators.update(calc.extract_indicators(102, InstrumentCategoryType.PE))
        all_indicators.update(calc.extract_indicators(26000, InstrumentCategoryType.SPOT))

        # Verification 1: IndicatorCalculator should have nullified the -prev values
        assert all_indicators.get("ce-ema-5-prev") is None
        assert all_indicators.get("nifty-ema-5-prev") is None

        # Verification 2: TripleLockStrategy should return NEUTRAL because of missing 'prev'
        candle = {"t": today_base, "c": 150}
        signal, reason, weight = strategy.on_resampled_candle_closed(candle, all_indicators)
        assert signal == SignalType.NEUTRAL
        assert "WAITING FOR INDICATOR WARMUP" in reason

        # 3. Second Candle of Today (09:20)
        today_0920 = today_base + 300
        calc.add_candle({"c": 155, "t": today_0920}, instrument_category=InstrumentCategoryType.CE, instrument_id=101)
        calc.add_candle({"c": 45, "t": today_0920}, instrument_category=InstrumentCategoryType.PE, instrument_id=102)
        calc.add_candle({"c": 24210, "t": today_0920}, instrument_category=InstrumentCategoryType.SPOT, instrument_id=26000)
        
        all_indicators = {}
        all_indicators.update(calc.extract_indicators(101, InstrumentCategoryType.CE))
        all_indicators.update(calc.extract_indicators(102, InstrumentCategoryType.PE))
        all_indicators.update(calc.extract_indicators(26000, InstrumentCategoryType.SPOT))

        # Verification 3: Indicators exist but no crossover because it already happened at 09:15
        assert all_indicators.get("ce-ema-5-prev") is not None
        
        candle = {"t": today_0920, "c": 155}
        signal, reason, weight = strategy.on_resampled_candle_closed(candle, all_indicators)
        assert signal == SignalType.NEUTRAL
        assert reason == "No signal"
    finally:
        settings.TRADE_START_TIME = original_start

def test_valid_intraday_crossover_allowed():
    """
    Verifies that a legitimate crossover happening WITHIN the same session is still detected.
    """
    # Set start time early for the test
    from packages.settings import settings
    original_start = settings.TRADE_START_TIME
    settings.TRADE_START_TIME = "09:00:00"

    try:
        config = [
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "CE"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "CE"},
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "PE"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "PE"},
            {"indicatorId": "ema-5", "indicator": "ema-5", "InstrumentType": "SPOT"},
            {"indicatorId": "ema-21", "indicator": "ema-21", "InstrumentType": "SPOT"},
        ]
        calc = IndicatorCalculator(indicators_config=config, max_window_size=100)
        strategy = TripleLockStrategy()

        today_dt = datetime(2025, 5, 21, 9, 15)
        today_base = int(today_dt.timestamp())
        
        # 1. Warm up with 50 candles TODAY in a BEARISH state for CE
        for i in range(50):
            ts = today_base + i * 300
            calc.add_candle({"c": 100, "t": ts}, instrument_category=InstrumentCategoryType.CE, instrument_id=101)
            calc.add_candle({"c": 110, "t": ts}, instrument_category=InstrumentCategoryType.PE, instrument_id=102)
            calc.add_candle({"c": 24200, "t": ts}, instrument_category=InstrumentCategoryType.SPOT, instrument_id=26000)

        # 2. Trigger Intraday Crossover
        now_ts = today_base + 51 * 300
        calc.add_candle({"c": 300, "t": now_ts}, instrument_category=InstrumentCategoryType.CE, instrument_id=101)
        calc.add_candle({"c": 50, "t": now_ts}, instrument_category=InstrumentCategoryType.PE, instrument_id=102)
        calc.add_candle({"c": 24210, "t": now_ts}, instrument_category=InstrumentCategoryType.SPOT, instrument_id=26000)
        
        all_indicators = {}
        all_indicators.update(calc.extract_indicators(101, InstrumentCategoryType.CE))
        all_indicators.update(calc.extract_indicators(102, InstrumentCategoryType.PE))
        all_indicators.update(calc.extract_indicators(26000, InstrumentCategoryType.SPOT))

        candle = {"t": now_ts, "c": 300}
        signal, reason, weight = strategy.on_resampled_candle_closed(candle, all_indicators)
        
        # Verification: Intraday crossover should WORK
        assert signal == SignalType.LONG
        assert reason == "PYTHON: Triple Lock CALL Entry"
    finally:
        settings.TRADE_START_TIME = original_start

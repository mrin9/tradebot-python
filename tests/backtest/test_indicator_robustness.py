
import pytest
import polars as pl
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.candle_resampler import CandleResampler
from packages.tradeflow.types import InstrumentCategoryType

def test_indicator_robustness_with_nulls():
    """
    Verifies that IndicatorCalculator is robust against null (None) prices
    by forward-filling values.
    """
    config = [
        {"indicatorId": "ema_5", "indicator": "ema-5", "InstrumentType": "SPOT"}
    ]
    calc = IndicatorCalculator(config)
    
    # 1. Add some valid candles
    for i in range(1, 4):
        calc.add_candle({"t": i, "o": 100, "h": 105, "l": 95, "c": 100 + i})
        
    # 2. Add a candle with None close
    # IndicatorCalculator should now forward-fill 'close' from the previous '103'
    res = calc.add_candle({"t": 4, "o": None, "h": None, "l": None, "c": None})
    
    assert res["nifty-ema_5"] is not None
    assert isinstance(res["nifty-ema_5"], float)
    # The close for t=4 should have been forward-filled to 103
    # Check that it didn't return None
    print(f"EMA with null close: {res['nifty-ema_5']}")

def test_resampler_robustness_with_nulls():
    """
    Verifies that CandleResampler does not overwrite its valid state with None.
    """
    resampler = CandleResampler(instrument_id=26000, interval_seconds=60)
    
    # Start a candle
    resampler.add_candle({"t": 60, "o": 100, "h": 105, "l": 95, "c": 101})
    
    # Add a tick with None price
    resampler.add_candle({"t": 65, "o": None, "h": None, "l": None, "c": None})
    
    assert resampler.current_candle["close"] == 101.0
    assert resampler.current_candle["high"] == 105.0
    assert resampler.current_candle["low"] == 95.0

def test_resampler_flushing_preserves_last_price():
    """
    Verifies that when a resampler is flushed (e.g. during sync), it preserves the last known price.
    """
    resampler = CandleResampler(instrument_id=26000, interval_seconds=60)
    
    # Previous period
    resampler.add_candle({"t": 0, "o": 100, "h": 105, "l": 95, "c": 101})
    # Flush triggered for new period
    closed = resampler.add_candle({"t": 60, "is_flush": True})
    
    assert closed is not None
    assert closed["close"] == 101.0

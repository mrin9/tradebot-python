"""
Tests for the CandleResampler class, verifying OHLCV aggregation across different timeframes.
"""

from packages.tradeflow.candle_resampler import CandleResampler


def test_resampling_basic():
    """
    Tests basic resampling logic: aggregating 1-minute candles into a 5-minute candle.
    Verifies OHLCV values and the closing of the period.
    """
    # 5-minute resampler (timeframe_mins=5, interval=300s)
    resampler = CandleResampler(instrument_id=1, symbol="TEST", timeframe_mins=5)
    resampler.suppress_logs = True

    # Use timestamps within the same 300s period (300-599)
    c1 = {"t": 300, "o": 100, "h": 105, "l": 95, "c": 102, "v": 10}
    out1 = resampler.add_candle(c1)
    assert out1 is None

    c2 = {"t": 360, "o": 102, "h": 110, "l": 101, "c": 108, "v": 20}
    out2 = resampler.add_candle(c2)
    assert out2 is None

    assert resampler.current_candle["high"] == 110
    assert resampler.current_candle["low"] == 95
    assert resampler.current_candle["volume"] == 30

    # Tick at t=600 (next period) closes the previous candle
    c3 = {"t": 600, "o": 108, "h": 109, "l": 107, "c": 107, "v": 5}
    out3 = resampler.add_candle(c3)

    assert out3 is not None
    assert out3["timestamp"] == 300  # Period start
    assert out3["open"] == 100
    assert out3["high"] == 110
    assert out3["low"] == 95
    assert out3["close"] == 108
    assert out3["volume"] == 30
    assert out3["is_final"]

    # New candle state
    assert resampler.current_candle["timestamp"] == 600
    assert resampler.current_candle["open"] == 108


def test_reset():
    """Reset clears all state."""
    resampler = CandleResampler(instrument_id=1, symbol="TEST", timeframe_mins=3)
    resampler.add_candle({"t": 300, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    resampler.reset()
    assert resampler.current_candle is None
    assert resampler.last_period_start is None
    assert resampler.source_candle_count == 0


def test_no_timestamp_returns_none():
    """Tick with no valid timestamp returns None."""
    resampler = CandleResampler(instrument_id=1, symbol="TEST", timeframe_mins=5)
    result = resampler.add_candle({"o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    assert result is None


def test_zero_timestamp_returns_none():
    """Tick with t=0 is treated as invalid."""
    resampler = CandleResampler(instrument_id=1, symbol="TEST", timeframe_mins=5)
    result = resampler.add_candle({"t": 0, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1})
    assert result is None

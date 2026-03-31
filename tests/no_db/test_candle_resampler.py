"""
Tests for the CandleResampler class, verifying OHLCV aggregation across different timeframes.
"""

from packages.tradeflow.candle_resampler import CandleResampler


def test_resampling_basic():
    """
    Tests basic resampling logic: aggregating 1-minute candles into a 5-minute candle.
    Verifies OHLCV values and the closing of the period.
    """
    # 5-minute resampler (300 seconds)
    resampler = CandleResampler(instrument_id=1, interval_seconds=300)

    # 1-min candle at t=0
    c1 = {"t": 0, "o": 100, "h": 105, "l": 95, "c": 102, "v": 10}
    out1 = resampler.add_candle(c1)
    assert out1 is None

    # 1-min candle at t=60
    c2 = {"t": 60, "o": 102, "h": 110, "l": 101, "c": 108, "v": 20}
    out2 = resampler.add_candle(c2)
    assert out2 is None

    assert resampler.current_candle["high"] == 110  # 105 -> 110
    assert resampler.current_candle["low"] == 95  # 95 -> 101 (min is 95)
    assert resampler.current_candle["volume"] == 30

    # 1-min candle at t=300 (Next period starts!)
    # This should close the previous one (0-300)
    c3 = {"t": 300, "o": 108, "h": 109, "l": 107, "c": 107, "v": 5}
    out3 = resampler.add_candle(c3)

    assert out3 is not None
    assert out3["timestamp"] == 0  # Period start
    assert out3["open"] == 100
    assert out3["high"] == 110
    assert out3["low"] == 95
    assert out3["close"] == 108  # Close of c2
    assert out3["volume"] == 30
    assert out3["is_final"]

    # New candle state
    assert resampler.current_candle["timestamp"] == 300
    assert resampler.current_candle["open"] == 108

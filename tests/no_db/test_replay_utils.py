"""Unit tests for packages.utils.replay_utils.ReplayUtils — pure logic, no DB."""

from packages.utils.replay_utils import ReplayUtils


class TestExplodeBarToTicks:
    def test_basic_ohlcv(self):
        """Standard OHLCV bar produces 4 ticks in O-H-L-C order."""
        candle = {"o": 100.0, "h": 110.0, "l": 90.0, "c": 105.0, "v": 400}
        ticks = ReplayUtils.explode_bar_to_ticks(instrument_id=1, candle=candle, base_timestamp=1000)
        assert len(ticks) == 4
        assert ticks[0]["p"] == 100.0
        assert ticks[1]["p"] == 110.0
        assert ticks[2]["p"] == 90.0
        assert ticks[3]["p"] == 105.0

    def test_timestamps(self):
        """Ticks at 0s, 15s, 30s, 59s offsets from (base - 59)."""
        ticks = ReplayUtils.explode_bar_to_ticks(1, {"o": 1, "h": 2, "l": 0, "c": 1, "v": 0}, base_timestamp=1000)
        start = 1000 - 59
        assert ticks[0]["t"] == start
        assert ticks[1]["t"] == start + 15
        assert ticks[2]["t"] == start + 30
        assert ticks[3]["t"] == 1000

    def test_volume_chunking(self):
        """Volume split evenly across 4 ticks."""
        ticks = ReplayUtils.explode_bar_to_ticks(1, {"o": 1, "h": 1, "l": 1, "c": 1, "v": 100}, base_timestamp=0)
        for t in ticks:
            assert t["v"] == 25

    def test_alternate_key_names(self):
        """Supports open/high/low/close/volume keys."""
        candle = {"open": 50, "high": 60, "low": 40, "close": 55, "volume": 200}
        ticks = ReplayUtils.explode_bar_to_ticks(99, candle, base_timestamp=500)
        assert ticks[0]["p"] == 50
        assert ticks[1]["p"] == 60

    def test_p_key_fallback(self):
        """Falls back to 'p' key for open price."""
        ticks = ReplayUtils.explode_bar_to_ticks(1, {"p": 42, "h": 50, "l": 30, "c": 45, "v": 0}, base_timestamp=100)
        assert ticks[0]["p"] == 42

    def test_instrument_id_propagated(self):
        """All ticks carry the instrument_id."""
        ticks = ReplayUtils.explode_bar_to_ticks(12345, {"o": 1, "h": 1, "l": 1, "c": 1, "v": 0}, base_timestamp=0)
        for t in ticks:
            assert t["i"] == 12345

    def test_is_snapshot_flags(self):
        """Only the low tick (index 2) has is_snapshot=True."""
        ticks = ReplayUtils.explode_bar_to_ticks(1, {"o": 1, "h": 1, "l": 1, "c": 1, "v": 0}, base_timestamp=0)
        assert ticks[2]["is_snapshot"] is True
        assert all(ticks[i]["is_snapshot"] is False for i in [0, 1, 3])

    def test_default_price(self):
        """Missing keys fall back to default_price."""
        ticks = ReplayUtils.explode_bar_to_ticks(1, {}, base_timestamp=0, default_price=99.0)
        assert all(t["p"] == 99.0 for t in ticks)

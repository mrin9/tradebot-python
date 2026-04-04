"""Unit tests for packages.tradeflow.types — enums, TypedDicts, Pydantic models."""

from packages.tradeflow.types import (
    SignalType,
    MarketIntentType,
    InstrumentKindType,
    InstrumentCategoryType,
    SignalPayload,
)


class TestSignalType:
    def test_values(self):
        """SignalType enum has correct integer values."""
        assert SignalType.LONG.value == 1
        assert SignalType.SHORT.value == -1
        assert SignalType.NEUTRAL.value == 0
        assert SignalType.EXIT.value == 2


class TestInstrumentCategoryType:
    def test_string_values(self):
        """InstrumentCategoryType uses string values."""
        assert InstrumentCategoryType.SPOT.value == "SPOT"
        assert InstrumentCategoryType.CE.value == "CE"
        assert InstrumentCategoryType.PE.value == "PE"
        assert InstrumentCategoryType.OPTIONS_BOTH.value == "OPTIONS_BOTH"


class TestSignalPayload:
    def test_required_fields(self):
        """SignalPayload requires signal, price, timestamp, symbol, display_symbol."""
        payload = SignalPayload(
            signal=MarketIntentType.LONG,
            price=100.0,
            timestamp=1700000000.0,
            symbol=26000,
            display_symbol="NIFTY",
        )
        assert payload.signal == MarketIntentType.LONG
        assert payload.price == 100.0

    def test_defaults(self):
        """Optional fields have correct defaults."""
        payload = SignalPayload(
            signal=MarketIntentType.SHORT,
            price=50.0,
            timestamp=0.0,
            symbol="SYM",
            display_symbol="SYM",
        )
        assert payload.confidence == 0.0
        assert payload.reason == "N/A"
        assert payload.reason_desc == ""
        assert payload.nifty_price == 0.0
        assert payload.is_continuity is False

    def test_datetime_timestamp(self):
        """Timestamp can be a datetime object."""
        from datetime import datetime
        payload = SignalPayload(
            signal=MarketIntentType.LONG,
            price=1.0,
            timestamp=datetime(2026, 1, 1),
            symbol=1,
            display_symbol="X",
        )
        assert isinstance(payload.timestamp, datetime)

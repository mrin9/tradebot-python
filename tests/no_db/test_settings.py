"""Unit tests for Settings collection suffix logic — pure logic, no DB."""

from packages.settings import Settings


class TestCollectionSuffix:
    def test_default_no_suffix(self):
        """Default DB name 'tradebot' has no suffix."""
        s = Settings(DB_NAME="tradebot")
        assert s.COLLECTION_SUFFIX == ""
        assert s.NIFTY_CANDLE_COLLECTION == "nifty_candle"

    def test_test_suffix(self):
        """tradebot_test gets '_test' suffix."""
        s = Settings(DB_NAME="tradebot_test")
        assert s.COLLECTION_SUFFIX == "_test"
        assert s.NIFTY_CANDLE_COLLECTION == "nifty_candle_test"
        assert s.OPTIONS_CANDLE_COLLECTION == "options_candle_test"
        assert s.PAPERTRADE_COLLECTION == "papertrade_test"

    def test_frozen_suffix(self):
        """tradebot_frozen gets '_frozen' suffix."""
        s = Settings(DB_NAME="tradebot_frozen")
        assert s.COLLECTION_SUFFIX == "_frozen"
        assert s.ACTIVE_CONTRACT_COLLECTION == "active_contract_frozen"

    def test_all_collections_use_suffix(self):
        """All collection properties respect the suffix."""
        s = Settings(DB_NAME="tradebot_test")
        collections = [
            s.NIFTY_CANDLE_COLLECTION,
            s.OPTIONS_CANDLE_COLLECTION,
            s.STOCK_TICKS_PER_SECOND_COLLECTION,
            s.ACTIVE_CONTRACT_COLLECTION,
            s.INSTRUMENT_MASTER_COLLECTION,
            s.STOCK_INDICATOR_COLLECTION,
            s.BACKTEST_RESULT_COLLECTION,
            s.STRATEGY_INDICATORS_COLLECTION,
            s.LIVE_TRADES_COLLECTION,
            s.PAPERTRADE_COLLECTION,
        ]
        assert all(c.endswith("_test") for c in collections)


class TestUnescapeDollarSigns:
    def test_double_dollar_unescaped(self):
        """$$ in string fields is converted to single $."""
        s = Settings(DB_NAME="tradebot", MARKET_TIMEZONE="$$HOME/test")
        assert s.MARKET_TIMEZONE == "$HOME/test"

    def test_non_string_untouched(self):
        """Non-string fields are not affected."""
        s = Settings(DB_NAME="tradebot", NIFTY_LOT_SIZE=75)
        assert s.NIFTY_LOT_SIZE == 75

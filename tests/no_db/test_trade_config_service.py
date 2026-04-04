"""Unit tests for TradeConfigService — pure logic, no DB (mocked where needed)."""

import pytest

from packages.services.trade_config_service import TradeConfigService


class TestNormalizeStrategyConfig:
    def test_indicators_key_casing(self):
        """'Indicators' (capital I) is normalized to 'indicators'."""
        raw = {"Indicators": [{"type": "ema", "params": {"period": 5}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert "indicators" in result
        assert "Indicators" not in result

    def test_missing_indicators_defaults_empty(self):
        """Missing indicators key defaults to empty list."""
        result = TradeConfigService.normalize_strategy_config({})
        assert result["indicators"] == []

    def test_timeframe_normalization(self):
        """'timeframe' and 'timeframe_seconds' both map to 'timeframeSeconds'."""
        r1 = TradeConfigService.normalize_strategy_config({"timeframe": 300})
        assert r1["timeframeSeconds"] == 300

        r2 = TradeConfigService.normalize_strategy_config({"timeframe_seconds": 180})
        assert r2["timeframeSeconds"] == 180

    def test_snake_to_camel_mappings(self):
        """Snake_case keys are converted to camelCase."""
        raw = {
            "sl_pct": 3.0,
            "target_pct": "2,3,4",
            "tsl_pct": 1.0,
            "use_be": True,
            "instrument_type": "OPTIONS",
            "strike_selection": "ATM",
            "invest_mode": "fixed",
        }
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["slPct"] == 3.0
        assert result["targetPct"] == "2,3,4"
        assert result["tslPct"] == 1.0
        assert result["useBe"] is True
        assert result["instrumentType"] == "OPTIONS"
        assert result["strikeSelection"] == "ATM"
        assert result["investMode"] == "fixed"

    def test_defaults_applied(self):
        """strategyId, name, timeframeSeconds get defaults."""
        result = TradeConfigService.normalize_strategy_config({})
        assert result["strategyId"] == "default"
        assert result["name"] == "Unnamed Strategy"
        assert "timeframeSeconds" in result

    def test_indicator_shorthand_ema(self):
        """EMA indicator gets shorthand like 'ema-20'."""
        raw = {"indicators": [{"type": "ema", "params": {"period": 20}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "ema-20"

    def test_indicator_shorthand_rsi(self):
        raw = {"indicators": [{"type": "rsi", "params": {"period": 14}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "rsi-14"

    def test_indicator_shorthand_supertrend(self):
        raw = {"indicators": [{"type": "supertrend", "params": {"period": 10, "multiplier": 3.0}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "supertrend-10-3.0"

    def test_indicator_shorthand_macd(self):
        raw = {"indicators": [{"type": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "macd-12-26-9"

    def test_indicator_shorthand_bbands(self):
        raw = {"indicators": [{"type": "bbands", "params": {"period": 20, "stdDev": 2.0}}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "bbands-20-2.0"

    def test_existing_indicator_key_not_overwritten(self):
        """If 'indicator' key already exists, it's preserved."""
        raw = {"indicators": [{"type": "ema", "params": {"period": 5}, "indicator": "custom-ema"}]}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["indicators"][0]["indicator"] == "custom-ema"

    def test_camel_not_overwritten_by_snake(self):
        """If camelCase key already exists, snake_case doesn't overwrite it."""
        raw = {"sl_pct": 3.0, "slPct": 5.0}
        result = TradeConfigService.normalize_strategy_config(raw)
        assert result["slPct"] == 5.0


class TestBuildPositionConfig:
    def test_basic_defaults(self):
        """Default build produces valid config."""
        config = TradeConfigService.build_position_config()
        assert config["instrumentType"] == "OPTIONS"
        assert config["strikeSelection"] == "ATM"
        assert config["investMode"] == "fixed"
        assert config["useBe"] is True
        assert isinstance(config["targetPct"], list)
        assert isinstance(config["pyramidSteps"], list)

    def test_target_pct_string_parsed(self):
        """Comma-separated target_pct string is parsed to list of floats."""
        config = TradeConfigService.build_position_config(target_pct="10,20,30")
        assert config["targetPct"] == [10.0, 20.0, 30.0]

    def test_target_pct_list_passthrough(self):
        """List target_pct is passed through."""
        config = TradeConfigService.build_position_config(target_pct=[5.0, 10.0])
        assert config["targetPct"] == [5.0, 10.0]

    def test_pyramid_steps_string_parsed(self):
        """Comma-separated pyramid_steps string is parsed to list of ints."""
        config = TradeConfigService.build_position_config(pyramid_steps="50,30,20")
        assert config["pyramidSteps"] == [50, 30, 20]

    def test_invalid_invest_mode_raises(self):
        """Invalid investMode raises ValueError."""
        with pytest.raises(ValueError, match="investMode"):
            TradeConfigService.build_position_config(invest_mode="invalid")

    def test_invalid_instrument_type_raises(self):
        """Invalid instrumentType raises ValueError."""
        with pytest.raises(ValueError, match="instrumentType"):
            TradeConfigService.build_position_config(instrument_type="CRYPTO")

    def test_case_normalization(self):
        """instrumentType uppercased, investMode lowercased, priceSource lowercased."""
        config = TradeConfigService.build_position_config(
            instrument_type="options", invest_mode="Fixed", price_source="OPEN"
        )
        assert config["instrumentType"] == "OPTIONS"
        assert config["investMode"] == "fixed"
        assert config["priceSource"] == "open"

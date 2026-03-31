"""
Unified Domain Tests for Indicators.
Covers naming conventions, technical analysis calculation, and FundManager mapping/caching.
"""

from unittest.mock import MagicMock

import pytest

from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.types import InstrumentCategoryType

# --- Fixtures ---


@pytest.fixture
def calc_instance():
    """Mock indicator config from strategy_indicator DB format."""
    config = [
        {"indicatorId": "fast-ema", "indicator": "ema-5", "InstrumentType": "SPOT"},
        {"indicatorId": "rsi", "indicator": "rsi-14", "InstrumentType": "CE"},
    ]
    return IndicatorCalculator(indicators_config=config, max_window_size=50)


@pytest.fixture
def mock_strategy_path(tmp_path):
    p = tmp_path / "dummy_strategy.py"
    p.write_text("""
from packages.tradeflow.types import MarketIntentType
class Strategy:
    def on_resampled_candle_closed(self, *args, **kwargs):
        class Signal: name = "WAIT"
        return Signal(), "No Signal", 0
""")
    return str(p)


# --- Sub-Domain: Calculation Logic ---


def test_calculator_initialization(calc_instance):
    """Verifies IndicatorCalculator creates slots for active instruments."""
    assert InstrumentCategoryType.SPOT in calc_instance.active_instrument_ids
    assert InstrumentCategoryType.CE in calc_instance.active_instrument_ids


def test_calculator_standalone_logic(calc_instance):
    """Verifies technical analysis values are correctly calculated and lagged."""
    res = {}
    for i in range(1, 21):
        res = calc_instance.add_candle(
            {"c": i * 10, "o": 0, "h": 0, "l": 0, "v": 0, "t": 1000 + i * 60},
            instrument_category=InstrumentCategoryType.SPOT,
        )

    assert "nifty-fast-ema" in res
    assert res["nifty-fast-ema"] > 0
    assert "nifty-fast-ema-prev" in res
    # EMA of 10,20...200 (span 5) should be ~180
    assert 170 < res["nifty-fast-ema"] < 190


def test_calculator_dynamic_category_init(calc_instance):
    """Ensures dynamic initialization when an unexpected instrument category appears."""
    res = calc_instance.add_candle({"c": 100, "t": 1000}, instrument_category=InstrumentCategoryType.PE)
    assert res == {}
    assert InstrumentCategoryType.PE in calc_instance.active_instrument_ids


# --- Sub-Domain: Naming Conventions ---


def test_canonical_indicator_names():
    """Verifies the exact keys generated for a broad set of technical indicators."""
    config = [
        {"indicator": "ema-5", "InstrumentType": "SPOT"},
        {"indicator": "sma-50", "InstrumentType": "SPOT"},
        {"indicator": "rsi-14", "InstrumentType": "SPOT"},
        {"indicator": "atr-14", "InstrumentType": "SPOT"},
        {"indicator": "macd-12-26-9", "InstrumentType": "SPOT"},
        {"indicator": "supertrend-10-3", "InstrumentType": "SPOT"},
        {"indicator": "bbands-20-2", "InstrumentType": "SPOT"},
        {"indicator": "vwap", "InstrumentType": "SPOT"},
        {"indicator": "obv", "InstrumentType": "SPOT"},
        {"indicator": "price", "InstrumentType": "SPOT"},
    ]
    calc = IndicatorCalculator(indicators_config=config, max_window_size=100)
    for i in range(100):
        calc.add_candle(
            {"t": 1000 + i * 60, "o": 100 + i, "h": 105 + i, "l": 95 + i, "c": 100 + i, "v": 1000},
            instrument_category=InstrumentCategoryType.SPOT,
            instrument_id=26000,
        )
    res = calc.latest_results[26000]

    assert "nifty-ema-5" in res
    assert "nifty-ema-5-prev" in res
    assert "nifty-sma-50" in res
    assert "nifty-rsi-14" in res
    assert "nifty-atr-14" in res
    assert "nifty-macd-12-26-9-signal" in res
    assert "nifty-supertrend-10-3-dir" in res
    assert "nifty-bbands-20-2-upper" in res
    assert "nifty-vwap" in res
    assert "nifty-obv" in res
    assert "nifty-price" in res


def test_explicit_indicator_id_overrides():
    """Verifies that indicatorId overrides the shorthand auto-generated name."""
    config = [{"indicatorId": "ema5", "indicator": "ema-5", "InstrumentType": "SPOT"}]
    calc = IndicatorCalculator(indicators_config=config, max_window_size=10)
    res = calc.add_candle({"t": 1000, "o": 100, "h": 100, "l": 100, "c": 100, "v": 100}, instrument_id=26000)
    assert "nifty-ema5" in res
    assert "nifty-ema-5" not in res


# --- Sub-Domain: FundManager Mapping & Caching ---


def test_fund_manager_indicator_mapping_cache(mock_strategy_path):
    """Verifies FundManager correctly maps signals and caches results to optimize performance."""
    config = {
        "symbol": "NIFTY",
        "timeframe_seconds": 60,
        "indicators": [{"id": "SMA_20", "type": "SMA", "params": {"period": 20}}],
        "pythonStrategyPath": mock_strategy_path,
        "position_config": {
            "budget": 100000,
            "invest_mode": "FIXED_BUDGET",
            "sl_pct": 20,
            "target_pct": [40],
            "tsl_pct": 0,
            "use_be": True,
            "instrument_type": "OPTIONS",
            "strike_selection": "ATM",
            "price_source": "close",
            "symbol": "NIFTY",
            "pyramid_steps": [100],
            "pyramid_confirm_pts": 10,
        },
    }
    fm = FundManager(config)
    fm.active_instruments = {"CE": 101, "PE": 102}
    fm.indicator_calculator.extract_indicators = MagicMock(return_value={"val": 1.0})

    # 1. Initial Call - should rebuild
    inds1 = fm._get_mapped_indicators()
    assert fm._needs_mapping_update is False
    assert inds1 is fm._cached_mapped_indicators

    # 2. Sequential Call - should return cached identity
    inds2 = fm._get_mapped_indicators()
    assert inds2 is inds1

    # 3. Simulate Event Invalidation
    fm.indicator_calculator.extract_indicators.return_value = {"val": 2.0}
    fm._on_resampled_candle_closed({"t": 123, "instrument_id": 26000}, InstrumentCategoryType.SPOT)
    assert fm._cached_mapped_indicators["val"] == 2.0
    assert fm._cached_mapped_indicators is not inds1

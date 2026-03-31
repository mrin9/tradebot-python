"""
Unified Domain Tests for Contract Discovery.
Covers strike rounding logic, target contract derivation, and caching/resolution.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from packages.services.contract_discovery import ContractDiscoveryService
from packages.settings import settings

# --- Fixtures ---


@pytest.fixture
def mock_db():
    db = MagicMock()
    # Mock collection mapping for common usage
    mock_master_col = MagicMock()
    db.__getitem__.side_effect = lambda key: {settings.INSTRUMENT_MASTER_COLLECTION: mock_master_col}.get(
        key, MagicMock()
    )
    return db


# --- Sub-Domain: Strike & Expiry Logic ---


def test_get_atm_strike_rounding():
    """Tests the static mathematical rounding helper for NIFTY-style 50-point increments."""
    assert ContractDiscoveryService.get_atm_strike(22424) == 22400
    assert ContractDiscoveryService.get_atm_strike(22426) == 22450
    assert ContractDiscoveryService.get_atm_strike(22474) == 22450
    assert ContractDiscoveryService.get_atm_strike(22476) == 22500


def test_derive_target_contracts_logic(mock_db):
    """Verifies that derive_target_contracts calculates strikes and fetches correctly from DB."""
    mock_master_col = mock_db[settings.INSTRUMENT_MASTER_COLLECTION]

    # 1. Mock expiry and contract responses
    mock_master_col.distinct.return_value = ["2026-03-12T00:00:00"]
    mock_master_col.find_one.return_value = {"contractExpiration": "2026-03-12T00:00:00"}
    mock_master_col.find.return_value = [
        {"exchangeInstrumentID": 1001, "strikePrice": 22450, "optionType": 3, "contractExpiration": "2026-03-12T00:00:00"},
        {"exchangeInstrumentID": 1002, "strikePrice": 22450, "optionType": 4, "contractExpiration": "2026-03-12T00:00:00"},
    ]

    service = ContractDiscoveryService(db=mock_db)
    dt = datetime(2026, 3, 10)

    with patch("packages.services.contract_discovery.MarketHistoryService") as mock_history_cls:
        mock_history = mock_history_cls.return_value
        mock_history.get_last_nifty_price.return_value = 22426  # Rounding should lead to 22450

        contracts = service.derive_target_contracts(dt, strike_count=0)  # Only ATM

    assert len(contracts) == 2
    args, _ = mock_master_col.find.call_args
    assert 22450 in args[0]["strikePrice"]["$in"]


def test_derive_target_contracts_no_spot(mock_db):
    """Verifies that it returns empty list if no spot price is available."""
    service = ContractDiscoveryService(db=mock_db)
    with patch("packages.services.contract_discovery.MarketHistoryService") as mock_history_cls:
        mock_history = mock_history_cls.return_value
        mock_history.get_last_nifty_price.return_value = None
        contracts = service.derive_target_contracts(datetime.now())
    assert contracts == []


# --- Sub-Domain: Caching & Individual Resolution ---


def test_contract_discovery_cache_logic(mock_db):
    """Verifies internal caching mechanism for instrument lookups."""
    mock_master_col = mock_db[settings.INSTRUMENT_MASTER_COLLECTION]
    mock_instruments = [
        {
            "exchangeInstrumentID": 101,
            "strikePrice": 25000,
            "optionType": 3,
            "contractExpiration": "2026-03-20T14:30:00",
            "description": "NIFTY 25000 CE",
        },
        {
            "exchangeInstrumentID": 102,
            "strikePrice": 25000,
            "optionType": 4,
            "contractExpiration": "2026-03-20T14:30:00",
            "description": "NIFTY 25000 PE",
        },
    ]
    mock_master_col.find.return_value = mock_instruments

    discovery = ContractDiscoveryService(db=mock_db)
    discovery.load_cache("NIFTY", "OPTIDX")
    assert discovery._is_cache_loaded is True

    # Resolve should hit cache (find_one should not be called)
    mock_master_col.find_one.reset_mock()
    inst_id, _ = discovery.resolve_option_contract(25000, True, 1773292800)
    assert inst_id == 101
    mock_master_col.find_one.assert_not_called()


def test_contract_discovery_cache_fallback(mock_db):
    """Ensures discovery falls back to direct DB queries if cache is not loaded."""
    discovery = ContractDiscoveryService(db=mock_db)
    assert discovery._is_cache_loaded is False

    discovery.resolve_option_contract(25000, True, 1773292800)
    mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.assert_called_once()


def test_backtest_relative_discovery(mock_db):
    """
    Critical Test: Ensures that backdated contract resolution works
    even if the contracts are 'expired' relative to system time.
    """
    mock_master_col = mock_db[settings.INSTRUMENT_MASTER_COLLECTION]

    # 1. Mock instruments that expired in 2024
    past_expiry = "2024-03-20T14:30:00"
    mock_instruments = [
        {
            "exchangeInstrumentID": 999,
            "strikePrice": 22000,
            "optionType": 3,
            "contractExpiration": past_expiry,
            "description": "NIFTY 22000 CE (OLD)",
        },
    ]
    mock_master_col.find.return_value = mock_instruments
    mock_master_col.find_one.return_value = mock_instruments[0]

    discovery = ContractDiscoveryService(db=mock_db)

    # 2. Backtest starts in early 2024
    backtest_start = datetime(2024, 3, 1)
    backtest_tick_ts = backtest_start.timestamp()

    # 3. Load cache with effective date
    discovery.load_cache("NIFTY", "OPTIDX", effective_date=backtest_start)
    assert len(discovery._cache[("NIFTY", "OPTIDX")]) == 1

    # 4. Resolve relative to backtest tick
    # Should work because 2024-03-20 >= 2024-03-01
    inst_id, _ = discovery.resolve_option_contract(22000, True, backtest_tick_ts)
    assert inst_id == 999

    # 5. Resolve window relative to backtest tick
    window_ids = discovery.get_strike_window_ids(22000, window_size=0, current_ts=backtest_tick_ts)
    assert 999 in window_ids

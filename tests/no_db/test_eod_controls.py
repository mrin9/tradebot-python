import pytest
from datetime import datetime, time
from unittest.mock import MagicMock, patch
from packages.services.contract_discovery import ContractDiscoveryService
from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import MarketIntentType, SignalPayload, InstrumentKindType
from packages.settings import settings

# --- MOCKS ---

class DummyOrderManager:
    def place_order(self, symbol, side, qty, price=0.0, timestamp=None):
        return {"status": "SUCCESS", "order_id": "MOCK-100"}
    
    def get_order_status(self, order_id):
        return {"status": "FILLED", "price": 100.0}

@pytest.fixture
def mock_db():
    return MagicMock()

@pytest.fixture
def discovery_service(mock_db):
    return ContractDiscoveryService(db=mock_db)

@pytest.fixture
def pm():
    # Helper to setup PositionManager with a mock order manager
    pm = PositionManager(
        symbol="NIFTY", quantity=50, sl_pct=10.0, target_pct=[20.0], instrument_type=InstrumentKindType.OPTIONS
    )
    pm.set_order_manager(DummyOrderManager())
    return pm

# --- CONTRACT DISCOVERY TESTS (EXPIRY JUMP) ---

def test_expiry_jump_logic(discovery_service, mock_db, monkeypatch):
    """Verifies that we jump to Next Week on Expiry Day after 14:30."""
    monkeypatch.setattr(settings, "TRADE_EXPIRY_JUMP_CUTOFF", "14:30:00")
    
    expiries = ["2026-04-13T14:30:00+05:30", "2026-04-21T14:30:00+05:30"]
    mock_db[settings.INSTRUMENT_MASTER_COLLECTION].distinct.return_value = expiries
    
    mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.return_value = {
        "exchangeInstrumentID": "63412",
        "description": "NIFTY 21APR2026 CE 24000"
    }

    # Use a fixed morning time to get today's date context
    dt_base = datetime(2026, 4, 13, 10, 0, 0)
    
    # CASE A: 14:29:59 (Stay on Today)
    dt_before = dt_base.replace(hour=14, minute=29, second=59)
    discovery_service.resolve_option_contract(24000, True, dt_before.timestamp())
    args, _ = mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.call_args
    assert args[0]["contractExpiration"] == expiries[0]

    # CASE B: 14:30:00 (Jump to Next Week)
    dt_after = dt_base.replace(hour=14, minute=30, second=0)
    discovery_service.resolve_option_contract(24000, True, dt_after.timestamp())
    args, _ = mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.call_args
    assert args[0]["contractExpiration"] == expiries[1]

def test_no_next_week_fallback(discovery_service, mock_db, monkeypatch):
    """Verifies it stays on Today if no Next Week expiry is available."""
    monkeypatch.setattr(settings, "TRADE_EXPIRY_JUMP_CUTOFF", "14:30:00")
    
    expiries = ["2026-04-13T14:30:00+05:30"]
    mock_db[settings.INSTRUMENT_MASTER_COLLECTION].distinct.return_value = expiries
    mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.return_value = {"exchangeInstrumentID": "123"}

    dt_after = datetime(2026, 4, 13, 14, 30, 0)
    discovery_service.resolve_option_contract(24000, True, dt_after.timestamp())
    args, _ = mock_db[settings.INSTRUMENT_MASTER_COLLECTION].find_one.call_args
    assert args[0]["contractExpiration"] == expiries[0]

# --- POSITION MANAGER TESTS (EOD CONTROLS) ---

def test_entry_cutoff_guard(pm, monkeypatch):
    """Verifies no new entries after 15:00."""
    monkeypatch.setattr(settings, "TRADE_LAST_ENTRY_TIME", "15:00:00")
    monkeypatch.setattr(settings, "TRADE_START_TIME", "09:20:00")

    # 1. OK Entry
    dt_ok = datetime(2026, 4, 13, 14, 59, 59)
    pm.on_signal(SignalPayload(
        signal=MarketIntentType.LONG, price=100.0, timestamp=dt_ok, symbol="123", display_symbol="TEST"
    ))
    assert pm.current_position is not None
    pm.current_position = None # manual reset
    
    # 2. Blocked Entry
    dt_blocked = datetime(2026, 4, 13, 15, 0, 0)
    pm.on_signal(SignalPayload(
        signal=MarketIntentType.LONG, price=100.0, timestamp=dt_blocked, symbol="123", display_symbol="TEST"
    ))
    assert pm.current_position is None

def test_signal_exit_still_works_after_cutoff(pm, monkeypatch):
    """Verifies that exits via signal flips are NOT blocked by entry cutoff."""
    monkeypatch.setattr(settings, "TRADE_LAST_ENTRY_TIME", "15:00:00")
    
    pm.on_signal(SignalPayload(
        signal=MarketIntentType.LONG, price=100.0, timestamp=datetime(2026, 4, 13, 14, 30), symbol="123", display_symbol="TEST"
    ))
    assert pm.current_position is not None
    
    pm.on_signal(SignalPayload(
        signal=MarketIntentType.SHORT, price=110.0, timestamp=datetime(2026, 4, 13, 15, 5), symbol="123", display_symbol="TEST"
    ))
    assert pm.current_position is None

def test_auto_square_off(pm, monkeypatch):
    """Verifies auto square-off at 15:15."""
    monkeypatch.setattr(settings, "TRADE_SQUARE_OFF_TIME", "15:15:00")
    
    pm.on_signal(SignalPayload(
        signal=MarketIntentType.LONG, price=100.0, timestamp=datetime(2026, 4, 13, 14, 30), symbol="123", display_symbol="TEST"
    ))
    assert pm.current_position is not None
    
    # Tick before
    ts_before = datetime(2026, 4, 13, 15, 14, 59).timestamp()
    pm.update_tick({"ltp": 105.0, "timestamp": ts_before})
    assert pm.current_position is not None
    
    # Tick after
    ts_after = datetime(2026, 4, 13, 15, 15, 0).timestamp()
    pm.update_tick({"ltp": 105.0, "timestamp": ts_after})
    assert pm.current_position is None
    assert pm.trades_history[-1].status == "EOD_SQUARE_OFF"

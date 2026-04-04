import datetime
from unittest.mock import MagicMock

from packages.services.trade_event import TradeEventService
from packages.settings import settings
from packages.utils.date_utils import DateUtils


def test_build_config_summary_enrichment():
    """build_config_summary extracts indicators, budget, targets from FundManager."""
    fm = MagicMock()
    fm.config = {"strategyId": "triple-confirmation", "name": "Triple Confirmation Momentum Strategy"}
    fm.position_config = {
        "budget": 100000,
        "python_strategy_path": "path/to/strat",
        "pyramidSteps": [100],
        "pyramidConfirmPts": 10.0,
    }
    fm.global_timeframe = 180
    fm.indicator_calculator.config = [
        {"indicator": "ema-5", "instrumentType": "SPOT"},
        {"indicator": "ema-21", "instrumentType": "OPTIONS_BOTH"},
    ]
    fm.tsl_id = "SPOT-EMA-5"
    fm.invest_mode = "fixed"
    fm.initial_budget = 100000
    fm.sl_pct = 15.0
    fm.target_pct = [15.0, 25.0, 50.0]
    fm.tsl_pct = 15.0
    fm.use_be = True
    fm.strike_selection = "ATM"
    fm.price_source = "close"

    summary = TradeEventService.build_config_summary(fm, mode="live")

    assert summary["strategyId"] == "triple-confirmation"
    assert summary["indicators"] == ["SPOT-EMA-5", "OPTIONS-BOTH-EMA-21"]
    assert summary["budget"] == 100000
    assert summary["targets"] == [15.0, 25.0, 50.0]


def test_session_id_generation():
    """Session ID has 5 dash-separated segments ending with 'python'."""
    session_id = DateUtils.generate_session_id("triple-confirmation")
    parts = session_id.split("-")
    assert len(parts) == 5
    assert parts[2] == "triple"
    assert len(parts[3]) == 3
    assert parts[4] == "python"


def test_trade_event_service_granular_pnl_passing():
    """record_trade_event passes actionPnL to persistence.record_granular_event."""
    persistence_mock = MagicMock()
    service = TradeEventService.__new__(TradeEventService)
    service.session_id = "test-session"
    service.record_papertrade = True
    service.persistence = persistence_mock
    service.db = MagicMock()
    service.active_signals = []

    fund_manager = MagicMock()
    pos = MagicMock()
    pos.symbol = "NIFTY"
    pos.display_symbol = "NIFTY"
    pos.current_price = 100.0
    pos.remaining_quantity = 50
    pos.total_realized_pnl = 500.0
    fund_manager.position_manager.current_position = pos
    fund_manager.position_manager.session_realized_pnl = 1000.0
    fund_manager.latest_tick_prices = {26000: 25000.0}

    event_data = {"type": "target", "transaction": "Target 1 Hit", "actionPnL": 250.0}

    service.record_trade_event(event_data, fund_manager)

    _args, kwargs = persistence_mock.record_granular_event.call_args
    assert kwargs["action_pnl"] == 250.0
    assert kwargs["msg"] == "Target 1 Hit"


def test_persist_non_position_event_structure():
    """Non-position events get sessionId, createdAt, and timestamp removed."""
    service = TradeEventService.__new__(TradeEventService)
    service.session_id = "test-session"
    service.record_papertrade = True
    service.db = MagicMock()

    event_data = {
        "type": "INIT",
        "msg": "Initialization",
        "timestamp": datetime.datetime(2026, 3, 12, 9, 30, 0),
    }

    service._persist_non_position_event(event_data)

    inserted_doc = service.db[settings.PAPERTRADE_COLLECTION].insert_one.call_args[0][0]
    assert "timestamp" not in inserted_doc
    assert "createdAt" in inserted_doc
    assert inserted_doc["sessionId"] == "test-session"


def test_record_trade_event_normal_persistence():
    """Basic smoke test for record_trade_event path."""
    pass


def test_record_init_standardization():
    """record_init persists an INIT event with config summary."""
    service = TradeEventService.__new__(TradeEventService)
    service.session_id = "test-session"
    service.record_papertrade = True
    service.db = MagicMock()
    service.persistence = MagicMock()
    service.active_signals = []

    fm = MagicMock()
    fm.config = {"strategyId": "test", "name": "Test Strategy"}
    fm.position_config = {"budget": 100, "python_strategy_path": "p", "pyramidSteps": [], "pyramidConfirmPts": 0}
    fm.indicator_calculator.config = []
    fm.global_timeframe = 180
    fm.tsl_id = None
    fm.invest_mode = "fixed"
    fm.initial_budget = 100
    fm.sl_pct = 3.0
    fm.target_pct = [2, 3, 4]
    fm.tsl_pct = 0.0
    fm.use_be = True
    fm.strike_selection = "ATM"
    fm.price_source = "close"

    service.record_init(fm, mode="backtest")

    inserted_doc = service.db[settings.PAPERTRADE_COLLECTION].insert_one.call_args[0][0]
    assert inserted_doc["type"] == "INIT"
    assert inserted_doc["config"]["mode"] == "backtest"
    assert inserted_doc["config"]["strategyId"] == "test"

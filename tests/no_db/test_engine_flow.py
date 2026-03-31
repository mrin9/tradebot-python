"""
Tests for LiveTradeEngine logic and MarketUtils tick normalization.
"""

from unittest.mock import patch

from packages.livetrade.live_trader import LiveTradeEngine


def test_engine_initialization():
    print("Testing LiveTradeEngine Initialization...")

    mock_strategy = {"ruleId": "TEST_01", "name": "Test Strategy", "indicators": []}
    pos_cfg = {
        "budget": 100000,
        "symbol": "NIFTY",
        "quantity": 50,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "stop_loss_points": 10,
        "target_pct": 20,
    }

    with (
        patch("packages.xts.xts_session_manager.XtsSessionManager._get_market_client"),
        patch("packages.xts.xts_session_manager.XtsSessionManager.get_market_data_socket"),
    ):
        engine = LiveTradeEngine(mock_strategy, pos_cfg)
        # Session ID format: mar12-0923-triple-xyz (Month/Day-Time-Prefix-Rand)
        assert len(engine.session_id.split("-")) == 4
        assert engine.fund_manager.initial_budget == 100000

    print("✅ Engine Initialization Passed.")

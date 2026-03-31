from unittest.mock import MagicMock, patch

from packages.tradeflow.fund_manager import FundManager


def test_fund_manager_dynamic_atm_resolution():
    """
    Verifies that FundManager dynamically updates the active CE/PE 
    instrument IDs simply by tracking the Spot price tick.
    """

    # 1. Setup Mock Strategy and Config
    strategy_config = {
        "strategyId": "test-atm",
        "name": "ATM Test",
        "indicators": [],
        "timeframe_seconds": 60,
        "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
    }
    position_config = {
        "symbol": "NIFTY",
        "budget": 10000,
        "invest_mode": "fixed",
        "instrument_type": "OPTIONS",
        "strike_selection": "ATM",
        "price_source": "close",
        "sl_pct": 15.0,
        "target_pct": [15, 25, 45],
        "tsl_pct": 15.0,
        "use_be": True,
        "use_break_even": False,
        "pyramid_steps": 0,
        "pyramid_confirm_pts": 0,
    }

    # 2. Mock Services
    mock_config_service = MagicMock()
    mock_config_service.normalize_strategy_config.return_value = strategy_config
    mock_config_service.build_position_config.return_value = position_config

    mock_discovery = MagicMock()
    mock_history = MagicMock()

    # Dynamic ATM resolution logic
    mock_discovery.get_atm_strike.side_effect = lambda p: round(p / 50) * 50
    
    def mock_resolve(atm_strike, is_ce, current_ts):
        if atm_strike == 22000:
            return (1001, "NIFTY CE 22000") if is_ce else (1002, "NIFTY PE 22000")
        elif atm_strike == 22100:
            return (2001, "NIFTY CE 22100") if is_ce else (2002, "NIFTY PE 22100")
        return (3000, f"NIFTY { 'CE' if is_ce else 'PE'} {atm_strike}")
        
    mock_discovery.resolve_option_contract.side_effect = mock_resolve

    from packages.tradeflow.types import SignalType

    with patch("packages.tradeflow.fund_manager.PythonStrategy") as mock_strat_cls:
        mock_strat_inst = mock_strat_cls.return_value
        mock_strat_inst.on_resampled_candle_closed.return_value = (SignalType.NEUTRAL, "Neutral", 0.0)

        fm = FundManager(
            strategy_config=strategy_config,
            position_config=position_config,
            config_service=mock_config_service,
            discovery_service=mock_discovery,
            history_service=mock_history,
            is_backtest=False,
        )

    # 3. First Tick: Set initial spot price anchor (Price = 22010 -> ATM 22000)
    fm.on_tick_or_base_candle({"i": 26000, "p": 22010.0, "c": 22010.0, "t": 1770000000})
    # Flush tick
    fm.on_tick_or_base_candle({"i": 26000, "p": 22010.0, "c": 22010.0, "t": 1770000060})

    assert fm.active_instruments.get("CE") == 1001
    assert fm.active_instruments.get("PE") == 1002

    # 4. Large move: (Price = 22110 -> ATM 22100)
    fm.on_tick_or_base_candle({"i": 26000, "p": 22110.0, "c": 22110.0, "t": 1770000120})
    # Flush tick
    fm.on_tick_or_base_candle({"i": 26000, "p": 22110.0, "c": 22110.0, "t": 1770000180})

    # Verify new instruments selected immediately from discovery service
    assert fm.active_instruments.get("CE") == 2001
    assert fm.active_instruments.get("PE") == 2002

    print("✅ Dynamic ATM Resolution test PASSED.")


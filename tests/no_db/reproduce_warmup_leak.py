from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.tradeflow.fund_manager import FundManager
from packages.tradeflow.types import SignalType, MarketIntentType, InstrumentKindType

def reproduce_warmup_leak():
    """
    Reproduces the issue where historical warmup data leaks into PositionManager
    and triggers erroneous trade events.
    """
    print("\n🚀 Starting Reproduction: Warmup Leak Test")

    # 1. Setup Mock Strategy and Config
    strategy_config = {
        "strategyId": "repro-leak",
        "name": "Leak Repro",
        "indicators": [],
        "timeframe_seconds": 60,
        "pythonStrategyPath": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
    }
    position_config = {
        "symbol": "62582", # NIFTY2632423250CE
        "budget": 200000,
        "invest_mode": "fixed",
        "instrument_type": "OPTIONS",
        "strike_selection": "ATM",
        "price_source": "close",
        "sl_pct": 20.0,
        "target_pct": [15, 25, 45],
        "tsl_pct": 0.0,
        "use_be": True,
        "pyramid_steps": [100],
        "pyramid_confirm_pts": 0,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
    }

    # 2. Mock Services
    mock_config_service = MagicMock()
    mock_config_service.normalize_strategy_config.return_value = strategy_config
    mock_config_service.build_position_config.return_value = position_config

    mock_discovery = MagicMock()
    mock_discovery.get_atm_strike.return_value = 23250
    mock_discovery.resolve_option_contract.return_value = (62582, "NIFTY2632423250CE")

    mock_history = MagicMock()

    # 3. Initialize FundManager
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

    # 4. Manually Open a Position (Simulating 12:18 entry)
    # Entry Price: 236.50
    # Stop Loss: 216.50
    # Targets: [251.50, 261.50, 281.50]
    entry_ts = 1773902880 # Mar-19 12:18:00
    fm.position_manager.on_signal({
        "signal": MarketIntentType.LONG,
        "price": 236.50,
        "timestamp": entry_ts,
        "symbol": "62582",
        "display_symbol": "NIFTY2632423250CE",
        "reason": "Entry",
        "nifty_price": 23250,
        "is_continuity": False
    })

    assert fm.position_manager.current_position is not None
    assert fm.position_manager.current_position.entry_price == 236.50
    print("✅ Initial position opened at 236.50")

    # 5. Simulate a Warmup that contains a high price (Target 1 Hit) from the past
    # Warmup Candle from Mar-12 (as seen in user logs)
    # Price: 251.50 (Target 1 is 236.5 + 15 = 251.5)
    historical_ts = 1773297720 # Mar-12 14:52:00
    leaked_candle = {
        "i": 62582,
        "t": historical_ts,
        "o": 251.50,
        "h": 251.50,
        "l": 251.50,
        "c": 251.50
    }

    # Set is_warming_up to True (as history_service.run_warmup would do)
    fm.is_warming_up = True
    print("🕒 System is now 'warming up'...")

    # Feed the leaked candle
    fm.on_tick_or_base_candle(leaked_candle)

    # 6. Verify the Leak
    pos = fm.position_manager.current_position
    if pos.achieved_targets > 0:
        print(f"❌ BUG REPRODUCED: Position achieved {pos.achieved_targets} targets from WARMUP data!")
        print(f"   Current SL: {pos.stop_loss} (Expected 216.50 if no leak, or 236.50 if leak triggered BE)")
    else:
        print("✅ Fixed: Position was NOT affected by warmup data.")

    # Cleanup
    fm.is_warming_up = False

if __name__ == "__main__":
    reproduce_warmup_leak()

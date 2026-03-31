from unittest.mock import MagicMock, patch

from packages.livetrade.live_trader import LiveTradeEngine
from packages.settings import settings


def test_live_trader_warmup_normalization():
    """
    Verifies that LiveTradeEngine._fetch_ohlc_api correctly subtracts the IST offset (19800s).
    """
    strategy_config = {"name": "Test", "ruleId": "TEST_001"}
    position_config = {
        "budget": 10000,
        "symbol": "NIFTY",
        "quantity": 50,
        "python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        "stop_loss_points": 10,
        "target_pct": 20,
    }

    # Mock dependencies to avoid real connections
    with (
        patch("packages.xts.xts_session_manager.XtsSessionManager._get_market_client") as mock_xts,
        patch("packages.xts.xts_session_manager.XtsSessionManager.get_market_data_socket"),
        patch("packages.utils.mongo.MongoRepository.get_db"),
    ):
        engine = LiveTradeEngine(strategy_config, position_config)

        # Mock XTS response
        # 1772711099 is Mar 05 2026 11:49:57 IST (or UTC if we treat it as Unix)
        # In XTS history, it would be returned as 1772711099.
        # We expect parsed 't' to be 1772711099 - 19800 = 1772691299
        mock_ohlc_str = "1772711099|100|110|90|105|1000|0|"

        mock_client = MagicMock()
        mock_client.get_ohlc.return_value = {"type": "success", "result": {"dataReponse": mock_ohlc_str}}
        mock_xts.return_value = mock_client

        candles = engine._fetch_ohlc_api(1, 26000, "Mar 05 2026 091500", "Mar 05 2026 114957")

        assert len(candles) == 1
        expected_ts = 1772711099 - settings.XTS_TIME_OFFSET
        assert candles[0]["t"] == expected_ts
        print(f"Verified Normalize TS: {candles[0]['t']} (Expected: {expected_ts})")


if __name__ == "__main__":
    test_live_trader_warmup_normalization()

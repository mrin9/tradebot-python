from unittest.mock import MagicMock, patch

import pytest

from packages.services.live_market import LiveMarketService


@pytest.fixture
def mock_xts():
    with (
        patch("packages.xts.xts_session_manager.XtsSessionManager.call_api") as m_api,
        patch("packages.xts.xts_session_manager.XtsSessionManager.get_market_data_socket") as ms,
    ):
        m_api.return_value = {"type": "success"}  # Standard success response
        socket = MagicMock()
        ms.return_value = socket
        yield m_api, socket


def test_live_market_subscription(mock_xts):
    m_api, _socket = mock_xts
    service = LiveMarketService()

    # Test Subscribe
    service.subscribe([26000, 50001])
    assert 26000 in service.subscribed_instruments
    assert 50001 in service.subscribed_instruments

    # Verify call_api was used for subscription
    assert m_api.call_count >= 1
    # Check that it was called with "send_subscription"
    args, _ = m_api.call_args_list[0]
    assert args[0] == "market"
    assert args[1] == "send_subscription"

    # Test Unsubscribe
    service.unsubscribe([50001])
    assert 50001 not in service.subscribed_instruments
    assert 26000 in service.subscribed_instruments
    # Check that last call was "send_unsubscription"
    args, _kwargs = m_api.call_args_list[-1]
    assert args[1] == "send_unsubscription"


def test_live_market_ensure_connection(mock_xts):
    m_api, socket = mock_xts
    socket.sid.connected = False
    service = LiveMarketService()

    service.ensure_connection()
    # Should call connect
    assert socket.connect.call_count >= 1

    socket.sid.connected = True
    service.ensure_connection()
    # Should call send_subscription via call_api for Nifty
    args, _kwargs = m_api.call_args_list[-1]
    assert args[1] == "send_subscription"

"""
Unified Domain Tests for XtsSessionManager.
Covers singleton client management, rate-limit retries, and session recovery logic.
"""

from unittest.mock import MagicMock, patch

import pytest

from packages.xts.xts_session_manager import XtsSessionManager


@pytest.fixture(autouse=True)
def reset_xts_manager():
    """Ensure a clean state for XtsSessionManager singletons across tests."""
    XtsSessionManager._market_client = None
    XtsSessionManager._interactive_client = None
    XtsSessionManager._socket_client = None
    yield
    XtsSessionManager._market_client = None
    XtsSessionManager._interactive_client = None
    XtsSessionManager._socket_client = None


# --- Sub-Domain: Singleton Management ---


def test_xts_manager_singleton_market():
    """Verifies that XtsSessionManager maintains a singleton for the Market Data client."""
    XtsSessionManager._market_client = "mock_client"
    client1 = XtsSessionManager._get_market_client()
    client2 = XtsSessionManager._get_market_client()
    assert client1 == client2
    assert client1 == "mock_client"


def test_xts_manager_singleton_interactive():
    """Verifies that XtsSessionManager maintains a singleton for the Interactive client."""
    XtsSessionManager._interactive_client = "mock_client_i"
    client1 = XtsSessionManager._get_interactive_client()
    client2 = XtsSessionManager._get_interactive_client()
    assert client1 == client2
    assert client1 == "mock_client_i"


# --- Sub-Domain: API Resilience (Retries & Recovery) ---


def test_call_api_rate_limit_retry():
    """Verifies that call_api waits and retries when hitting rate limits."""
    mock_func = MagicMock()
    mock_func.side_effect = [
        {"type": "error", "code": "e-apirl-0004", "description": "Rate Limit reached"},
        {"type": "success", "result": "done"},
    ]

    with patch.object(XtsSessionManager, "_get_market_client") as m_get, patch("time.sleep") as m_sleep:
        mock_client = MagicMock()
        mock_client.some_method = mock_func
        m_get.return_value = mock_client

        resp = XtsSessionManager.call_api("market", "some_method", max_retries=3)
        assert resp == {"type": "success", "result": "done"}
        assert mock_func.call_count == 2
        assert m_sleep.call_count == 1
        m_sleep.assert_called_with(1)


def test_call_api_session_expired_recovery():
    """Verifies that call_api re-logs when the session is invalid."""
    mock_func = MagicMock()
    mock_func.side_effect = [
        {"type": "error", "description": "Invalid Token"},
        {"type": "success", "result": "recovered"},
    ]

    with patch.object(XtsSessionManager, "_get_market_client") as m_get:
        mock_client = MagicMock()
        mock_client.some_method = mock_func
        m_get.side_effect = [mock_client, mock_client]

        resp = XtsSessionManager.call_api("market", "some_method")
        assert resp == {"type": "success", "result": "recovered"}
        assert m_get.call_count >= 2
        m_get.assert_called_with(force_login=True)


def test_call_api_max_retries():
    """Verifies that call_api stops after max_retries."""
    mock_func = MagicMock()
    mock_func.return_value = {"type": "error", "code": "e-apirl-0004"}

    with patch.object(XtsSessionManager, "_get_market_client") as m_get, patch("time.sleep"):
        m_get.return_value = MagicMock()
        m_get.return_value.fail_method = mock_func
        resp = XtsSessionManager.call_api("market", "fail_method", max_retries=2)
        assert mock_func.call_count == 2
        assert resp["code"] == "e-apirl-0004"

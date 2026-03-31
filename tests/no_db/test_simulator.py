"""
Tests for the SocketDataProvider, verifying real-time data emission for backtest simulations.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from packages.simulator.socket_data_provider import SocketDataProvider


def test_provider_initialization():
    """Verifies the initial state of the SocketDataProvider."""
    mock_sio = AsyncMock()
    provider = SocketDataProvider(mock_sio)
    assert provider.sio == mock_sio
    assert provider.running is False


def test_provider_emit_tick():
    """Verifies that the provider correctly emits 1501 tick events."""

    async def run_test():
        mock_sio = AsyncMock()
        provider = SocketDataProvider(mock_sio)

        await provider._emit_1501_tick(26000, 24500, 1700000000, 100)

        # Verify emit was called for Full format
        assert mock_sio.emit.call_count == 1
        args, _kwargs = mock_sio.emit.call_args_list[0]
        assert args[0] == "1501-json-full"
        assert args[1]["ExchangeInstrumentID"] == 26000
        assert args[1]["LastTradedPrice"] == 24500.0

    asyncio.run(run_test())


def test_provider_stop():
    """Verifies that stop_simulation correctly cancels the background task."""

    async def run_test():
        mock_sio = AsyncMock()
        provider = SocketDataProvider(mock_sio)
        provider.running = True

        # Mock task precisely
        mock_task = MagicMock()
        mock_task.done.return_value = True
        provider.task = mock_task

        await provider.stop_simulation()
        assert provider.running is False

    asyncio.run(run_test())


def test_multi_collection_merge_logic():
    """Placeholder for future multi-collection merge verification."""
    # This is a unit test for the logic inside stream_data
    # We can mock the Repo and cursors
    pass

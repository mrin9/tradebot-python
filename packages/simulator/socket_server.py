from datetime import datetime
from urllib.parse import urlparse

import socketio
from aiohttp import web

from packages.settings import settings
from packages.simulator.socket_data_provider import SocketDataProvider
from packages.utils.log_utils import setup_logger

logger = setup_logger("SocketService")


class SocketDataService:
    def __init__(self):
        # ... (rest of __init__)
        self.sio = socketio.AsyncServer(async_mode="aiohttp", cors_allowed_origins="*")
        self.app = web.Application()
        self.sio.attach(self.app, socketio_path="/apimarketdata/socket.io")

        # Initialize the data provider with the socket server
        self.data_provider = SocketDataProvider(self.sio)
        self.clients = set()

        self._setup_events()

    def _setup_events(self):
        # ... (rest of _setup_events)
        @self.sio.event
        async def connect(sid, environ):
            logger.info(f"Client connected: {sid}")
            self.clients.add(sid)

        @self.sio.event
        async def disconnect(sid):
            logger.info(f"Client disconnected: {sid}")
            if sid in self.clients:
                self.clients.remove(sid)

        @self.sio.on("subscribe")
        async def on_subscribe(sid, data):
            # Future: Handle specific subscriptions
            pass

        @self.sio.on("start_simulation")
        async def on_start_simulation(sid, data):
            """
            Triggered by test client to start replay.
            Data: {'instrument_id': ..., 'start': 'iso', 'end': 'iso', 'delay': float, 'mode': 'tick'|'candle'}
            """
            logger.info(f"Starting Simulation via Provider for {data}")

            try:
                raw_id = data.get("instrument_id")
                instrument_id = int(raw_id) if raw_id is not None else None

                start_dt = datetime.fromisoformat(data["start"])
                end_dt = datetime.fromisoformat(data["end"])
                delay = data.get("delay", 0.01)

                # Use the provider to start the stream
                await self.data_provider.start_simulation(
                    instrument_id=instrument_id, start_dt=start_dt, end_dt=end_dt, delay=delay
                )
            except Exception as e:
                logger.error(f"Failed to start simulation: {e}")
                await self.sio.emit("error", {"message": str(e)}, to=sid)

        @self.sio.on("stop_simulation")
        async def on_stop_simulation(sid, data):
            logger.info("Stopping Simulation via Provider")
            await self.data_provider.stop_simulation()

    def start_server(self, port=None):
        """Starts the AIOHTTP server."""
        if port is None:
            # Extract port from config
            url = urlparse(settings.SOCKET_SIMULATOR_URL)
            port = url.port or 5050

        logger.info(f"Starting Socket Data Service on port {port}...")
        web.run_app(self.app, port=port)


if __name__ == "__main__":
    service = SocketDataService()
    service.start_server()

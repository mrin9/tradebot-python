import json
import time

import socketio

from packages.settings import settings
from packages.utils.log_utils import setup_logger

logger = setup_logger(__name__)


class MDSocket_io:
    """A Socket.IO client for XTS Market Data."""

    def __init__(self, token, user_id, logger=False, engineio_logger=False, get_raw_data=True):
        if not logger:
            import logging

            # Set to a disabled logger if False
            logger_obj = logging.getLogger("null")
            logger_obj.addHandler(logging.NullHandler())
            logger_obj.propagate = False
        else:
            logger_obj = logger

        if not engineio_logger:
            import logging

            eio_logger_obj = logging.getLogger("null_eio")
            eio_logger_obj.addHandler(logging.NullHandler())
            eio_logger_obj.propagate = False
        else:
            eio_logger_obj = engineio_logger

        self.sid = socketio.Client(
            logger=logger_obj,
            engineio_logger=eio_logger_obj,
            reconnection_delay=1,
            reconnection_delay_max=5,
            randomization_factor=0.5,
        )
        # Manually increase ping timeout for high-volume handling
        self.sid.eio.ping_timeout = 120
        self.get_raw_data = get_raw_data

        self.user_id = user_id
        self.token = token
        self.port = settings.XTS_ROOT_URL
        self.broadcast_mode = settings.XTS_BROADCAST_MODE

        # Connection URL
        publish_format = "JSON"
        port_part = f"{self.port}/?token="
        self.connection_url = (
            port_part
            + token
            + "&userID="
            + self.user_id
            + "&publishFormat="
            + publish_format
            + "&broadcastMode="
            + self.broadcast_mode
        )

        self.on_connect = None
        self.on_message = None
        self.on_disconnect = None
        self.on_error = None

        # Message code specific callbacks
        """
        Message Event code description
        1105: Instrument Change
        1501: Touchline
        1502: Market Data
        1505: Candle Data
        1507: Market Status
        1510: OpenInterest
        1512: LTP
        """
        self.on_message1105_json_full = None
        self.on_message1105_json_partial = None
        self.on_message1501_json_full = None
        self.on_message1501_json_partial = None
        self.on_message1502_json_full = None
        self.on_message1502_json_partial = None
        self.on_message1505_json_full = None
        self.on_message1505_json_partial = None
        self.on_message1507_json_full = None
        self.on_message1507_json_partial = None
        self.on_message1510_json_full = None
        self.on_message1510_json_partial = None
        self.on_message1512_json_full = None
        self.on_message1512_json_partial = None

        # Register internal handlers
        self.sid.on("connect", self._internal_on_connect)
        self.sid.on("message", self._internal_on_message)
        self.sid.on("disconnect", self._internal_on_disconnect)
        self.sid.on("error", self._internal_on_error)

        codes = ["1105", "1501", "1502", "1504", "1505", "1507", "1510", "1512"]
        for code in codes:
            self.sid.on(f"{code}-json-full", self._make_internal_handler(code, "full"))
            self.sid.on(f"{code}-json-partial", self._make_internal_handler(code, "partial"))

        # Catch-all for debugging unexpected events
        self.sid.on("*", self._internal_catch_all)

    def _internal_catch_all(self, event, data):
        logger.debug(f"DEBUG: Socket received event '{event}' with data type {type(data)}")

    def _make_internal_handler(self, code, suffix):
        def handler(data):
            try:
                # Only normalize if user explicitly requested 'json'
                if self.get_raw_data:
                    processed_data = data
                else:
                    processed_data = self._normalize_data(data)

                callback_attr = f"on_message{code}_json_{suffix}"
                callback = getattr(self, callback_attr, None)
                if callable(callback):
                    callback(processed_data)
            except Exception as e:
                logger.error(f"Error in SDK internal handler for {code}_{suffix}: {e}", exc_info=True)

        return handler

    def _normalize_data(self, data):
        if data is None:
            return None
        if not isinstance(data, str):
            return data

        # Fast path for JSON
        if data.startswith("{") or data.startswith("["):
            try:
                return json.loads(data)
            except Exception:
                pass
        return self._parse_custom_string(data)

    def _parse_custom_string(self, data):
        if not isinstance(data, str) or data.startswith("{") or data.startswith("["):
            return data
        try:
            parsed_dict = {}
            parts = data.split(",")
            for part in parts:
                if ":" in part:
                    k, v = part.split(":", 1)
                    try:
                        if "." in v:
                            parsed_dict[k] = float(v)
                        elif "_" in v:
                            # Instrument IDs like 2_69948 should remain as strings
                            parsed_dict[k] = v
                        else:
                            parsed_dict[k] = int(v)
                    except ValueError:
                        parsed_dict[k] = v
                else:
                    parsed_dict[part] = True
            return parsed_dict
        except Exception:
            return data

    def _internal_on_connect(self):
        logger.info("Market Data Socket connected successfully!")
        if callable(self.on_connect):
            self.on_connect()

    def _internal_on_message(self, data):
        if callable(self.on_message):
            self.on_message(data)

    def _internal_on_disconnect(self):
        # Only log info if NOT silent
        if self.sid.logger and self.sid.logger.getEffectiveLevel() <= 20:  # 20 = INFO
            logger.info("Market Data Socket disconnected!")
        if callable(self.on_disconnect):
            self.on_disconnect()

    def _internal_on_error(self, data):
        logger.error(f"Market Data Error: {data}")
        if callable(self.on_error):
            self.on_error(data)

    def connect(
        self,
        headers=None,
        transports=None,
        namespaces=None,
        socketio_path="/apimarketdata/socket.io",
        verify=False,
    ):
        """Connect to a Socket.IO server.
        :param headers      : A dictionary with custom headers to send with the connection request.
        :param transports   : Allowed transport list. Valid transports are 'polling' and 'websocket'. If not given, the polling transport is connected first, then an upgrade to websocket is attempted.
        :param namespaces   : custom namespaces list to connect in addition to default. If not given, the namespace list is obtained from the registered event handlers.
        :param socketio_path: The endpoint where the Socket.IO server is installed. The default value is appropriate for most cases.
        :param verify       : Verify SSL.
        """
        # Connect to the socket with retry logic
        if transports is None:
            transports = ["websocket"]
        if headers is None:
            headers = {}
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                self.sid.connect(
                    url=self.connection_url,
                    headers=headers,
                    transports=transports,
                    namespaces=namespaces,
                    socketio_path=socketio_path,
                )
                self.sid.wait()
                break  # Success
            except socketio.exceptions.ConnectionError as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Socket connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    logger.error(f"Socket connection failed after {max_retries} attempts: {e}")
                    raise e

    def get_event_listener(self):
        return self.sid

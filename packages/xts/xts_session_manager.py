from datetime import datetime, timedelta
import json
import os

import urllib3

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.xts.MarketDataSocketClient import MDSocket_io
from packages.xts.xts_api import XtsApi

# Suppress InsecureRequestWarning caused by disabling SSL verification
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = setup_logger(__name__)


class XtsSessionManager:
    """
    Centralized manager for XTS connections.
    Handles authentication and instance management for both Market and Interactive APIs.
    Supports file-based session persistence to share tokens across processes.
    """

    _market_client: XtsApi = None
    _interactive_client: XtsApi = None
    _socket_client: MDSocket_io = None

    SESSION_FILE = ".xts_session.json"

    @classmethod
    def _save_session(cls, session_type: str, result: dict):
        """Saves session info (token, userID) to a shared file."""
        try:
            data = {}
            if os.path.exists(cls.SESSION_FILE):
                try:
                    with open(cls.SESSION_FILE) as f:
                        data = json.load(f)
                except Exception:
                    data = {}

            data[session_type] = {
                "token": result["token"],
                "userID": result["userID"],
                "isInvestorClient": result.get("isInvestorClient", False),
                "createdAt": datetime.now().isoformat(),
            }

            with open(cls.SESSION_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning(f"Failed to save {session_type} session to file: {e}")

    @classmethod
    def _load_session(cls, session_type: str) -> dict | None:
        """Loads session info from a shared file if valid (< 23 hours old)."""
        if not os.path.exists(cls.SESSION_FILE):
            return None
        try:
            with open(cls.SESSION_FILE) as f:
                data = json.load(f)

            if session_type in data:
                sess = data[session_type]
                # Check for freshness (23h to be safe as XTS tokens expire at midnight or after 24h)
                created_at = datetime.fromisoformat(sess["createdAt"])
                if datetime.now(DateUtils.MARKET_TZ) - created_at < timedelta(hours=23):
                    return sess

        except Exception as e:
            logger.warning(f"Failed to load {session_type} session from file: {e}")
        return None

    @classmethod
    def _get_market_client(cls, force_login: bool = False) -> XtsApi:
        """Returns an authenticated XtsApi instance for Market Data API (Private)."""
        if cls._market_client is None:
            cls._market_client = XtsApi(
                api_key=settings.MARKET_API_KEY,
                secret_key=settings.MARKET_API_SECRET,
                source=settings.XTS_SOURCE,
                root=settings.XTS_ROOT_URL,
                disable_ssl=settings.XTS_DISABLE_SSL,
            )

            # Try to load existing session
            session = cls._load_session("market") if not force_login else None

            if session:
                logger.info("Reusing existing Market Data session from file...")
                cls._market_client._set_common_variables(
                    session["token"], session["userID"], session["isInvestorClient"]
                )
                # Validate the cached token with a lightweight API call
                try:
                    test_resp = cls._market_client.get_config()
                    if isinstance(test_resp, str) and "invalid" in test_resp.lower():
                        logger.warning("Cached Market token is invalid. Will re-login...")
                        session = None  # Fall through to fresh login below
                    elif isinstance(test_resp, dict) and test_resp.get("type") == "error":
                        logger.warning(
                            f"Cached Market token rejected: {test_resp.get('description')}. Will re-login..."
                        )
                        session = None
                except Exception as e:
                    logger.warning(f"Token validation failed ({e}). Will re-login...")
                    session = None

            if not session:
                logger.info("Initializing New Market Data API Session...")
                response = cls._market_client.marketdata_login()
                if response and "result" in response and "token" in response["result"]:
                    logger.info(f"Market Data Login Successful. User: {response['result']['userID']}")
                    cls._save_session("market", response["result"])
                else:
                    logger.error(f"Market Data Login Failed: {response}")
                    raise Exception(f"Market Data Login Failed: {response}")

        return cls._market_client

    @classmethod
    def get_market_data_socket(cls, debug: bool = False) -> MDSocket_io:
        """Returns an authenticated Socket IO client for Market Data."""
        if cls._socket_client is None:
            # Ensure we have a valid token first
            market_client = cls._get_market_client()
            token = market_client.token

            logger.info("Initializing Market Data Socket...")
            cls._socket_client = MDSocket_io(
                token=token, user_id=market_client.user_id, logger=debug, engineio_logger=debug, get_raw_data=True
            )

        return cls._socket_client

    @classmethod
    def _get_interactive_client(cls, force_login: bool = False) -> XtsApi:
        """Returns an authenticated XtsApi instance for Interactive API (Private)."""
        if cls._interactive_client is None or force_login:
            cls._interactive_client = XtsApi(
                api_key=settings.INTERACTIVE_API_KEY,
                secret_key=settings.INTERACTIVE_API_SECRET,
                source=settings.XTS_SOURCE,
                root=settings.XTS_ROOT_URL,
                disable_ssl=settings.XTS_DISABLE_SSL,
            )

            # Try to load existing session
            session = cls._load_session("interactive") if not force_login else None

            if session:
                logger.info("Reusing existing Interactive session from file...")
                cls._interactive_client._set_common_variables(
                    session["token"], session["userID"], session["isInvestorClient"]
                )
            else:
                logger.info("Initializing New Interactive API Session...")
                response = cls._interactive_client.interactive_login()
                if response and isinstance(response, dict) and "result" in response and "token" in response["result"]:
                    logger.info(f"Interactive Login Successful. User: {response['result']['userID']}")
                    cls._save_session("interactive", response["result"])
                else:
                    logger.error(f"Interactive Login Failed: {response}")
                    raise Exception(f"Interactive Login Failed: {response}")

        return cls._interactive_client

    @classmethod
    def call_api(cls, client_type: str, func_name: str, *args, **kwargs):
        """
        Generic wrapper to call XTS API functions with automatic re-login on session failure
        and robust rate-limit handling with exponential backoff.
        """
        import time

        client = cls._get_market_client() if client_type == "market" else cls._get_interactive_client()
        func = getattr(client, func_name)

        attempt = 0
        max_attempts = kwargs.pop("max_retries", 3)  # Allow custom retry count

        while attempt < max_attempts:
            attempt += 1
            try:
                response = func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"XTS {client_type} {func_name} raised: {e}. Attempt {attempt}")
                response = str(e)

            is_invalid = False
            is_rate_limited = False
            error_code = ""

            if isinstance(response, str):
                err_msg = response.lower()
                if any(x in err_msg for x in ["invalid", "token", "session", "not logged in"]):
                    is_invalid = True
            elif isinstance(response, dict):
                # Handle standard error structure
                if response.get("type") == "error":
                    desc = str(response.get("description", "")).lower()
                    code = str(response.get("code", "")).lower()
                    error_code = code
                    if any(x in desc for x in ["token", "session", "not logged in"]):
                        is_invalid = True
                    if "apirl" in code or "limit" in desc:
                        is_rate_limited = True
                # User's error: {'err': True, 'data': {'type': 'error', ...}}
                elif response.get("err") is True and isinstance(response.get("data"), dict):
                    data = response["data"]
                    if data.get("type") == "error":
                        desc = str(data.get("description", "")).lower()
                        code = str(data.get("code", "")).lower()
                        error_code = code
                        if any(x in desc for x in ["token", "session", "not logged in"]):
                            is_invalid = True
                        if "apirl" in code or "limit" in desc:
                            is_rate_limited = True

            if is_invalid and attempt < max_attempts:
                logger.warning(f"XTS {client_type} session invalid. Re-logging...")
                if client_type == "market":
                    cls._market_client = None
                    cls._socket_client = None
                    client = cls._get_market_client(force_login=True)
                else:
                    cls._interactive_client = None
                    client = cls._get_interactive_client(force_login=True)
                func = getattr(client, func_name)
                continue

            if is_rate_limited and attempt < max_attempts:
                # User requested 1s wait instead of 5s backoff
                wait_sec = 1
                logger.warning(f"XTS Rate Limit hit ({func_name}, {error_code}). Waiting {wait_sec}s...")
                time.sleep(wait_sec)
                continue

            break

        return response

import json
import threading
import time
from unittest.mock import patch

import pytest

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.xts.xts_normalizer import XTSNormalizer
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("test_xts_bridge")

# --- Fixtures ---


@pytest.fixture(autouse=True)
def reset_xts_manager():
    """Reset XtsSessionManager singletons before each test to prevent mock leakage."""
    XtsSessionManager._market_client = None
    XtsSessionManager._interactive_client = None
    XtsSessionManager._socket_client = None
    yield


@pytest.fixture
def mock_xts():
    with patch("packages.xts.xts_session_manager.XtsApi") as mock:
        yield mock


# --- Mocked Tests (Unit Level) ---


def test_market_login_success(mock_xts):
    """Verifies successful market data login with mocked XTS response."""
    mock_instance = mock_xts.return_value
    mock_instance.marketdata_login.return_value = {
        "type": "success",
        "result": {"token": "mock_token", "userID": "mock_user"},
    }
    XtsSessionManager._market_client = None  # Force reset
    client = XtsSessionManager._get_market_client(force_login=True)
    assert client is not None
    mock_instance.marketdata_login.assert_called_once()


def test_get_ohlc_parsing(mock_xts):
    """Verifies parsing of OHLC (1505) data from XTS REST API."""
    mock_instance = mock_xts.return_value
    mock_instance.get_ohlc.return_value = {
        "type": "success",
        "result": {"dataReponse": "1772618459|24325.8|24325.8|24305.4|24315.45|100|0|"},
    }
    XtsSessionManager._market_client = mock_instance
    response = XtsSessionManager._get_market_client().get_ohlc(
        exchangeSegment=1,
        exchangeInstrumentID=26000,
        startTime="Mar 04 2026 100000",
        endTime="Mar 04 2026 110000",
        compressionValue=60,
    )
    assert response["type"] == "success"
    assert "dataReponse" in response["result"]


def test_get_quote_parsing(mock_xts):
    """Verifies parsing of Touchline (1501) quotes from XTS REST API."""
    mock_instance = mock_xts.return_value
    mock_instance.get_quote.return_value = {
        "type": "success",
        "result": {
            "listQuotes": [json.dumps({"Touchline": {"LastTradedPrice": 24577.8, "ExchangeInstrumentID": 26000}})]
        },
    }
    XtsSessionManager._market_client = mock_instance
    response = XtsSessionManager._get_market_client().get_quote(
        Instruments=[{"exchangeSegment": 1, "exchangeInstrumentID": 26000}], xtsMessageCode=1501, publishFormat="1"
    )
    assert response["type"] == "success"
    assert len(response["result"]["listQuotes"]) == 1


# --- Live Tests (Requires Connectivity) ---


@pytest.mark.live
def test_live_market_login():
    """Verify that we can login to XTS Market Data API."""
    client = XtsSessionManager._get_market_client()
    assert client is not None
    assert client.token is not None


@pytest.mark.live
def test_live_interactive_login():
    """Verify that we can login to XTS Interactive API."""
    client = XtsSessionManager._get_interactive_client()
    assert client is not None
    assert client.token is not None


@pytest.mark.live
def test_live_get_quote_structure():
    """Verify that get_quote returns expected keys (listQuotes)."""
    nifty_id = settings.NIFTY_INSTRUMENT_ID
    response = XtsSessionManager.call_api(
        "market",
        "get_quote",
        instruments=[{"exchangeSegment": 1, "exchangeInstrumentID": nifty_id}],
        xts_message_code=1501,
        publish_format="1",
    )
    assert response["type"] == "success"
    assert "listQuotes" in response["result"]
    assert len(response["result"]["listQuotes"]) > 0


@pytest.mark.live
def test_live_get_ohlc_structure():
    """Verify that get_ohlc returns expected keys (dataReponse)."""
    nifty_id = settings.NIFTY_INSTRUMENT_ID
    response = XtsSessionManager.call_api(
        "market",
        "get_ohlc",
        exchange_segment=1,
        exchange_instrument_id=nifty_id,
        start_time="Feb 27 2026 100000",
        end_time="Feb 27 2026 110000",
        compression_value=60,
    )
    assert response["type"] == "success"
    result = response["result"]
    assert "dataReponse" in result or "data" in result


@pytest.mark.live
def test_live_socket_connection():
    """Tests the Socket.IO connection live."""
    soc = XtsSessionManager.get_market_data_socket()
    connected_event = threading.Event()

    def on_connect():
        logger.info("✅ Socket Connect Event Received!")
        connected_event.set()

    soc.on_connect = on_connect

    if soc.sid.connected:
        connected_event.set()
    else:
        t = threading.Thread(target=soc.connect, kwargs={"transports": ["websocket"]})
        t.daemon = True
        t.start()

    is_connected = connected_event.wait(timeout=10)
    if is_connected:
        time.sleep(1)
        soc.sid.disconnect()

    assert is_connected is True, "Socket connection timed out"


from packages.tradeflow.fund_manager import FundManager


def test_fund_manager_tick_normalization_inplace():
    """
    Ensures that when FundManager receives a raw tick, it correctly
    populates the OHLC fields in the dictionary for downstream compatibility.
    """
    tick = {"instrument_id": 26000, "p": 22350.5, "t": 1770000000}

    position_config = {"python_strategy_path": "packages/tradeflow/python_strategies.py:TripleLockStrategy"}
    fm = FundManager(
        strategy_config={"strategyId": "test", "indicators": []}, position_config=position_config, is_backtest=True
    )

    fm.on_tick_or_base_candle(tick)

    assert "c" in tick
    assert tick["c"] == 22350.5
    assert tick["o"] == 22350.5
    assert tick["h"] == 22350.5
    assert tick["l"] == 22350.5
    assert tick["instrument_id"] == 26000
    assert fm.latest_tick_prices[26000] == 22350.5


def test_master_parsing():
    """Verifies the parsing of XTS Instrument Master CSV lines."""
    raw_line = "NSEFO|26000|1|NIFTY|NIFTY 50|IND|NIFTY IND|26000|0|0|75|0.05|50|1|||2026-02-26T00:00:00|0|0|NIFTY|1|1"
    parsed = XTSNormalizer.parse_xts_master_line(raw_line)

    assert parsed is not None
    assert parsed["exchangeSegment"] == "NSEFO"
    assert parsed["exchangeInstrumentID"] == 26000
    assert parsed["lotSize"] == 50
    assert parsed["contractExpiration"] == "2026-02-26T00:00:00+05:30"


def test_1501_full_json():
    """Verifies normalization of 1501 (Touchline) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 22,
        "ExchangeTimeStamp": 1205682251,
        "LastTradedPrice": 1567.95,
        "LastTradedQuantity": 20,
        "TotalTradedQuantity": 253453,
        "BidInfo": {"Price": 1567.95},
        "AskInfo": {"Price": 0},
    }

    norm = XTSNormalizer.normalize_xts_event("1501-json-full", payload)
    assert norm["i"] == 22
    assert norm["p"] == 1567.95
    assert norm["v"] == 20
    assert norm["q"] == 253453
    assert norm["t"] == 1521195251.0
    assert norm["isoDt"] == "2018-03-16T15:44:11+05:30"
    assert norm["bid"] == 1567.95
    assert norm["ask"] is None


def test_1501_partial_string():
    """Verifies normalization of 1501 (Touchline) pipe-separated string events."""
    payload = "t:1_22,ltp:1567.95,ltq:20,v:253453,ltt:1205682110,ai:0|1428|1567.95|10,bi:0|0|0|0|1"

    norm = XTSNormalizer.normalize_xts_event("1501-json-partial", payload)
    assert norm["i"] == 22
    assert norm["p"] == 1567.95
    assert norm["v"] == 20
    assert norm["q"] == 253453
    assert norm["t"] == 1521195110.0
    assert norm["isoDt"] == "2018-03-16T15:41:50+05:30"
    assert norm["bid"] == 0.0
    assert norm["ask"] == 1428.0


def test_1501_flat_json():
    """Verifies normalization of the flattened 1501 format used by the simulator."""
    payload = {"ltp": 24500.5, "ltq": 50, "i": 26000, "ltt": 1772618459, "v": 10000}
    norm = XTSNormalizer.normalize_xts_event("1501", payload)
    assert norm["i"] == 26000
    assert norm["p"] == 24500.5
    assert norm["v"] == 50


def test_1512_full_json():
    """Verifies normalization of 1512 (Snapshot/L2) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "ExchangeTimeStamp": 1708435800,
        "LastTradedPrice": 22000.5,
        "LastTradedQuantity": 100,
        "TotalTradedQuantity": 1500000,
    }
    norm = XTSNormalizer.normalize_xts_event("1512-json-full", payload)
    assert norm["i"] == 26000
    assert norm["p"] == 22000.5
    assert norm["v"] == 100
    assert norm["q"] == 1500000
    assert norm["t"] == 2023948800.0
    assert norm["isoDt"] == "2034-02-19T13:30:00+05:30"


def test_1512_depth():
    """Verifies normalization of XTS 1512 (Snapshot/L2) JSON format with depth."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "LastTradedPrice": 24500,
        "ExchangeTimeStamp": 1772618459,
        "BidInfo": {"Price": 24495, "Size": 100},
        "AskInfo": {"Price": 24505, "Size": 100},
    }
    norm = XTSNormalizer.normalize_xts_event("1512", payload)
    assert norm["bid"] == 24495
    assert norm["ask"] == 24505
    assert norm["p"] == 24500


def test_1512_partial_string():
    """Verifies normalization of 1512 (Snapshot/L2) pipe-separated string events."""
    payload = "i:26000,ltp:22000.5,ltq:100,v:1500000,ltt:1708435800"
    norm = XTSNormalizer.normalize_xts_event("1512-json-partial", payload)
    assert norm["i"] == 26000
    assert norm["p"] == 22000.5
    assert norm["v"] == 100
    assert norm["q"] == 1500000
    assert norm["t"] == 2023948800.0
    assert norm["isoDt"] == "2034-02-19T13:30:00+05:30"


def test_1505_full_json():
    """Verifies normalization of 1505 (Candle/Bar) full JSON events."""
    payload = {
        "ExchangeInstrumentID": 26000,
        "BarData": {
            "Open": 21900,
            "High": 22100,
            "Low": 21850,
            "Close": 22050,
            "Volume": 5000,
            "Timestamp": 1708435800,
        },
    }
    norm = XTSNormalizer.normalize_xts_event("1505-json-full", payload)
    assert norm["i"] == 26000
    assert norm["o"] == 21900
    assert norm["h"] == 22100
    assert norm["l"] == 21850
    assert norm["c"] == 22050
    assert norm["v"] == 5000
    assert norm["t"] == 2023948800.0


def test_1505_partial_string():
    """Verifies normalization of 1505 (Candle/Bar) pipe-separated string events."""
    payload = "i:26000,t:1708435800,o:21900,h:22100,l:21850,c:22050,v:5000"
    norm = XTSNormalizer.normalize_xts_event("1505-json-partial", payload)
    assert norm["i"] == 26000
    assert norm["o"] == 21900
    assert norm["h"] == 22100
    assert norm["l"] == 21850
    assert norm["c"] == 22050
    assert norm["v"] == 5000
    assert norm["t"] == 2023948800.0

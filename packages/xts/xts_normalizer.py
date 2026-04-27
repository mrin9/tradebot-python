import json

from packages.settings import settings
from packages.utils.date_utils import DateUtils

# Constants for Master Data Parsing
XTS_EQUITY_HEADERS = [
    "exchangeSegment",
    "exchangeInstrumentID",
    "instrumentTypeNum",
    "name",
    "description",
    "series",
    "nameWithSeries",
    "instrumentID",
    "priceBandHigh",
    "priceBandLow",
    "freezeQty",
    "tickSize",
    "lotSize",
    "multiplier",
    "displayName",
    "ISIN",
    "priceNumerator",
    "priceDenominator",
]

XTS_FO_HEADERS = [
    "exchangeSegment",
    "exchangeInstrumentID",
    "instrumentTypeNum",
    "name",
    "description",
    "series",
    "nameWithSeries",
    "instrumentID",
    "priceBandHigh",
    "priceBandLow",
    "freezeQty",
    "tickSize",
    "lotSize",
    "multiplier",
    "underlyingInstrumentId",
    "underlyingIndexName",
    "contractExpiration",
    "strikePrice",
    "optionType",
    "displayName",
    "priceNumerator",
    "priceDenominator",
]


class XTSNormalizer:
    """
    XTS-specific data normalization and parsing utilities.
    Relocated from market_utils.py to the connector layer.
    """

    @staticmethod
    def get_instrument_id(db, identifier: str) -> int:
        """
        Lookup Instrument ID from Master based on Symbol (description),
        ExchangeInstrumentID (if numeric), or Name.
        """
        try:
            return int(identifier)
        except ValueError:
            pass

        if identifier.upper() in ["NIFTY", "NIFTY 50", "NIFTY50", "NIFTY_50"]:
            return settings.NIFTY_INSTRUMENT_ID

        query = {"$or": [{"description": identifier}, {"name": identifier}, {"nameWithSeries": identifier}]}

        doc = db[settings.INSTRUMENT_MASTER_COLLECTION].find_one(query)
        if doc:
            return int(doc["exchangeInstrumentID"])

        raise ValueError(f"Instrument not found for identifier: {identifier}")

    @staticmethod
    def parse_xts_master_line(line: str) -> dict | None:
        """Parses a single line from the XTS master data pipe-separated response."""
        if not line or not line.strip():
            return None

        parts = line.strip().split("|")
        if len(parts) < 2:
            return None

        segment = parts[0]

        if segment == "NSECM":
            headers = XTS_EQUITY_HEADERS
        elif segment == "NSEFO":
            headers = XTS_FO_HEADERS
        else:
            headers = [f"field_{i}" for i in range(len(parts))]

        doc = {}
        for i, header in enumerate(headers):
            if i < len(parts):
                val = parts[i].strip()
                if val in {"", "NA"}:
                    doc[header] = None
                else:
                    try:
                        if "." in val or "e" in val.lower():
                            doc[header] = float(val)
                        else:
                            doc[header] = int(val)
                    except ValueError:
                        if header == "contractExpiration":
                            try:
                                dt = DateUtils.parse_iso(val)
                                doc[header] = DateUtils.to_iso(dt)
                            except Exception:
                                doc[header] = val
                        else:
                            doc[header] = val
            else:
                doc[header] = None

        return doc

    @staticmethod
    def parse_xts_master_data(content: str) -> list[dict]:
        """Parses the entire response body string from get_master() API."""
        if not content:
            return []
        return [
            item
            for item in (XTSNormalizer.parse_xts_master_line(line) for line in content.strip().split("\n"))

            if item is not None
        ]

    @staticmethod
    def parse_custom_xts_string(data: str) -> dict:
        """Parses XTS custom comma-separated format (e.g. t:1_9309,51:6023)."""
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
                            parsed_dict[k] = v
                        else:
                            parsed_dict[k] = int(v)
                    except ValueError:
                        parsed_dict[k] = v
                else:
                    parsed_dict[part] = True
            return parsed_dict
        except Exception:
            return {"raw": data}

    @staticmethod
    def normalize_raw_socket_data(rawSocketData: str | None) -> dict | None:
        """Converts raw socket payload string into a normalized Dict."""
        if rawSocketData is None:
            return None
        if not isinstance(rawSocketData, str):
            return rawSocketData

        if rawSocketData.startswith("{") or rawSocketData.startswith("["):
            try:
                return json.loads(rawSocketData)
            except Exception:
                pass
        return XTSNormalizer.parse_custom_xts_string(rawSocketData)

    @staticmethod
    def normalize_xts_event(event_type: str | None, rawSocketData: str | None) -> dict | None:
        """Main dispatcher to normalize different XTS socket events."""
        norm_data = XTSNormalizer.normalize_raw_socket_data(rawSocketData)
        if not norm_data:
            return None

        if not event_type:
            return XTSNormalizer.normalize_1501_tick_event(norm_data)

        if any(x in event_type for x in ["1501", "1512", "1502"]):
            return XTSNormalizer.normalize_1501_tick_event(norm_data)
        elif "1505" in event_type:
            return XTSNormalizer.normalize_1505_candle_event(norm_data)
        elif "1105" in event_type:
            return None

        return XTSNormalizer.normalize_1501_tick_event(norm_data)

    @staticmethod
    def _get_val(data: dict, long_key: str, short_key: str, default=None):
        """Helper to extract value from nested 'Touchline/BarData' vs Flat structure."""
        for wrapper in ["Touchline", "BarData"]:
            if wrapper in data and isinstance(data[wrapper], dict):
                val = data[wrapper].get(long_key, data[wrapper].get(short_key))
                if val is not None:
                    return val
        return data.get(long_key, data.get(short_key, default))

    @staticmethod
    def normalize_1501_tick_event(data: dict) -> dict:
        """Normalizes 1501 (Tick) and 1512 (Market Depth) events."""
        inst_id = XTSNormalizer._get_val(data, "ExchangeInstrumentID", "i", default=data.get("t", 0))
        ltp = XTSNormalizer._get_val(data, "LastTradedPrice", "ltp")
        last_qty = XTSNormalizer._get_val(data, "LastTradedQuantity", "ltq")
        if last_qty is None:
            last_qty = XTSNormalizer._get_val(data, "LastTradedQunatity", "ltq", default=0)
        total_qty = XTSNormalizer._get_val(data, "TotalTradedQuantity", "v", default=0)

        raw_ts = XTSNormalizer._get_val(data, "ExchangeTimeStamp", "ltt")
        if raw_ts is None:
            raw_ts = XTSNormalizer._get_val(data, "LastTradedTime", "lut")
        if raw_ts is None:
            raw_ts = XTSNormalizer._get_val(data, "LastUpdateTime", "lut")
        utc_ts = DateUtils.socket_timestamp_to_utc(raw_ts)

        bid_info = XTSNormalizer._get_val(data, "BidInfo", "bi")
        bid = (
            bid_info.get("Price")
            if isinstance(bid_info, dict)
            else (str(bid_info).split("|")[1] if bid_info and "|" in str(bid_info) else None)
        )
        ask_info = XTSNormalizer._get_val(data, "AskInfo", "ai")
        ask = (
            ask_info.get("Price")
            if isinstance(ask_info, dict)
            else (str(ask_info).split("|")[1] if ask_info and "|" in str(ask_info) else None)
        )

        try:
            bid = float(bid) if bid else None
            ask = float(ask) if ask else None
        except (ValueError, TypeError):
            bid = None
            ask = None

        return {
            "i": int(str(inst_id).split("_")[-1]) if inst_id else 0,
            "t": utc_ts,
            "isoDt": DateUtils.market_timestamp_to_iso(utc_ts),
            "p": ltp,
            "v": total_qty,
            "bid": bid,
            "ask": ask,
        }


    @staticmethod
    def normalize_1505_candle_event(data: dict) -> dict:
        """Normalizes 1505 (Bar/Candle) events."""
        inst_id = XTSNormalizer._get_val(data, "ExchangeInstrumentID", "i")
        raw_ts = XTSNormalizer._get_val(data, "Timestamp", "t")
        utc_ts = DateUtils.socket_timestamp_to_utc(raw_ts)

        return {
            "i": int(inst_id) if inst_id else 0,
            "t": utc_ts,
            "isoDt": DateUtils.market_timestamp_to_iso(utc_ts),
            "o": XTSNormalizer._get_val(data, "Open", "o"),
            "h": XTSNormalizer._get_val(data, "High", "h"),
            "l": XTSNormalizer._get_val(data, "Low", "l"),
            "c": XTSNormalizer._get_val(data, "Close", "c"),
            "v": XTSNormalizer._get_val(data, "Volume", "v"),
        }

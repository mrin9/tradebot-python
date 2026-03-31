import os
import sys

# Ensure the project root is in sys.path so 'packages' can be imported
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from datetime import datetime, timedelta

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("get_ohlc_data")


def get_instrument_details(query_val: str):
    """
    Search for instrument details in the master collection.
    Supports either exchangeInstrumentID (if numeric) or description.
    """
    db = MongoRepository.get_db()
    coll = db[settings.INSTRUMENT_MASTER_COLLECTION]

    if query_val.isdigit():
        query = {"exchangeInstrumentID": int(query_val)}
    else:
        query = {"description": query_val}

    doc = coll.find_one(query)
    if not doc:
        # Fallback to displayName if description doesn't match
        doc = coll.find_one({"displayName": query_val})

    return doc


def fetch_ohlc(instrument_doc, end_dt=None):
    """
    Fetches OHLC data for the last 15 days (if end_dt is None)
    or for 1 day ending at end_dt (if provided).
    """
    # Map segment name to ID
    segment_map = {"NSECM": 1, "NSEFO": 2, "NSECD": 3, "MCXFO": 4, "BSECM": 11, "BSEFO": 12}
    segment_name = instrument_doc.get("exchangeSegment")
    segment_id = segment_map.get(segment_name)

    if not segment_id:
        logger.error(f"Unsupported segment: {segment_name}")
        return None

    inst_id = instrument_doc["exchangeInstrumentID"]

    # Calculate range
    if end_dt:
        # If specific date provided, get 1 day
        start_dt = end_dt - timedelta(days=1)
    else:
        # Default behavior: last 15 days
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=15)

    # Format for XTS API: "MMM DD YYYY HHMMSS"
    start_str = start_dt.strftime("%b %d %Y %H%M%S")
    end_str = end_dt.strftime("%b %d %Y %H%M%S")

    logger.info(f"Fetching OHLC for {instrument_doc.get('description')} ({inst_id}) in {segment_name}")
    logger.info(f"Range: {start_str} to {end_str}")

    try:
        response = XtsSessionManager.call_api(
            "market",
            "get_ohlc",
            exchange_segment=segment_id,
            exchange_instrument_id=inst_id,
            start_time=start_str,
            end_time=end_str,
            compression_value=60,  # 1 minute candles
        )

        if isinstance(response, dict) and response.get("type") == "success" and "result" in response:
            data_response = response["result"].get("dataReponse", "")
            return parse_ohlc_string(data_response)
        else:
            logger.error(f"Failed to fetch OHLC: {response}")
            return None
    except Exception as e:
        logger.error(f"Error calling XTS API: {e}")
        return None


def parse_ohlc_string(ohlc_str: str):
    """
    Parses XTS OHLC string into list of rows for tabulate.
    Format: Timestamp|Open|High|Low|Close|Volume|OI|,...
    """
    if not ohlc_str:
        return []

    rows = []
    candles = ohlc_str.split(",")

    for candle in candles:
        if not candle:
            continue
        parts = candle.split("|")
        if len(parts) >= 5:
            # Parts: 0:ts, 1:o, 2:h, 3:l, 4:c, 5:v, 6:oi
            ts = DateUtils.rest_timestamp_to_utc(parts[0])
            iso_dt = DateUtils.market_timestamp_to_iso(ts)
            rows.append([iso_dt, parts[1], parts[2], parts[3], parts[4], parts[5]])

    return rows


def print_table(data, headers):
    """
    Simple grid formatter to avoid 'tabulate' dependency.
    """
    if not data:
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in data:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # Print header
    header_row = " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers)))
    print("-" * len(header_row))
    print(header_row)
    print("-" * len(header_row))

    # Print rows
    for row in data:
        print(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(row))))
    print("-" * len(header_row))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/get_ohlc_data.py <exchangeInstrumentID|description> [ISO_DATE_OR_DATETIME]")
        sys.exit(1)

    query_val = sys.argv[1].strip()
    date_val = sys.argv[2].strip() if len(sys.argv) > 2 else None

    # 1. Parse optional date
    target_end_dt = None
    if date_val:
        try:
            # DateUtils.parse_iso handles YYYY-MM-DD and YYYY-MM-DDTHH:MM:SS+Offset
            target_end_dt = DateUtils.parse_iso(date_val)
            print(f"Target End Date: {target_end_dt}")
        except Exception as e:
            print(f"Error parsing date '{date_val}': {e}")
            sys.exit(1)

    # 2. Get Details
    instrument = get_instrument_details(query_val)
    if not instrument:
        print(f"Error: Instrument '{query_val}' not found in {settings.INSTRUMENT_MASTER_COLLECTION}")
        sys.exit(1)

    print(f"Found Instrument: {instrument.get('description')} ({instrument.get('exchangeInstrumentID')})")

    # 3. Fetch Data
    ohlc_data = fetch_ohlc(instrument, end_dt=target_end_dt)

    if not ohlc_data:
        print("No OHLC data returned.")
        sys.exit(1)

    # 4. Print
    headers = ["Timestamp (IST)", "Open", "High", "Low", "Close", "Volume"]
    print_table(ohlc_data, headers)
    print(f"Total Candles: {len(ohlc_data)}")


if __name__ == "__main__":
    main()

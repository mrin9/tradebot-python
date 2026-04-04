"""
Fetch historic NIFTY options data (last 1 year, including expired)
from NSE F&O bhavcopies and insert into MongoDB options_historic_candle.

Uses two sources:
  - jugaad-data (old bhavcopy format) for dates before 2024-07-12
  - Direct NSE download (new bhavcopy format) for dates from 2024-07-12 onwards
"""
import os
import sys
import csv
import io
import time
import zipfile
from datetime import date, timedelta

import requests

# Project root on sys.path
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.insert(0, base_dir)

from packages.settings import settings
from packages.utils.mongo import MongoRepository
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger

logger = setup_logger("fetch_nifty_options")

COLLECTION = "options_historic_candle"
TEMP_DIR = "/tmp/fo_bhavcopy"
NEW_FORMAT_CUTOFF = date(2024, 7, 12)

end_date = date(2026, 4, 4)
start_date = end_date - timedelta(days=365)

os.makedirs(TEMP_DIR, exist_ok=True)

db = MongoRepository.get_db()
col = db[COLLECTION]

col.create_index(
    ["DATE", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP"],
    unique=True,
    name="dedup_idx",
    background=True,
)


def parse_float(v):
    try:
        return float(v.strip()) if v.strip() not in ("", "-") else None
    except Exception:
        return None


def date_to_epoch(d: date) -> float:
    """Convert trade date to UTC epoch at 09:15 IST (market open)."""
    from datetime import datetime
    from pytz import timezone
    ist = timezone("Asia/Kolkata")
    dt = ist.localize(datetime(d.year, d.month, d.day, 9, 15, 0))
    return int(dt.timestamp())


def fetch_new_bhavcopy_csv(d: date) -> str | None:
    """Download new-format bhavcopy from NSE, return CSV text or None."""
    ds = d.strftime("%Y%m%d")
    url = f"https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ds}_F_0000.csv.zip"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    if r.status_code != 200 or r.content[:4] != b"PK\x03\x04":
        return None
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0]).decode("utf-8")


def parse_new_format(csv_text: str) -> list[dict]:
    """Parse new NSE bhavcopy CSV into docs matching old field names."""
    docs = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        if row.get("TckrSymb", "").strip() != "NIFTY":
            continue
        opt = row.get("OptnTp", "").strip()
        if opt not in ("CE", "PE"):
            continue
        trade_dt_str = row.get("TradDt", "").strip()  # YYYY-MM-DD
        trade_d = date.fromisoformat(trade_dt_str)
        t = date_to_epoch(trade_d)
        docs.append({
            "INSTRUMENT": "OPTIDX",
            "SYMBOL": "NIFTY",
            "EXPIRY_DT": row.get("XpryDt", "").strip(),
            "STRIKE_PR": parse_float(row.get("StrkPric", "")),
            "OPTION_TYP": opt,
            "OPEN": parse_float(row.get("OpnPric", "")),
            "HIGH": parse_float(row.get("HghPric", "")),
            "LOW": parse_float(row.get("LwPric", "")),
            "CLOSE": parse_float(row.get("ClsPric", "")),
            "SETTLE_PR": parse_float(row.get("SttlmPric", "")),
            "CONTRACTS": parse_float(row.get("TtlTradgVol", "")),
            "VAL_INLAKH": parse_float(row.get("TtlTrfVal", "")),
            "OPEN_INT": parse_float(row.get("OpnIntrst", "")),
            "CHG_IN_OI": parse_float(row.get("ChngInOpnIntrst", "")),
            "DATE": trade_dt_str,
            "t": t,
            "isoDt": DateUtils.market_timestamp_to_iso(t),
        })
    return docs


def fetch_old_bhavcopy_docs(d: date) -> list[dict]:
    """Use jugaad-data for old-format bhavcopies."""
    from jugaad_data.nse import bhavcopy_fo_save
    from datetime import datetime

    csv_path = bhavcopy_fo_save(d, TEMP_DIR)
    t = date_to_epoch(d)
    iso_dt = DateUtils.market_timestamp_to_iso(t)
    docs = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("INSTRUMENT", "").strip() != "OPTIDX" or row.get("SYMBOL", "").strip() != "NIFTY":
                continue
            docs.append({
                "INSTRUMENT": "OPTIDX",
                "SYMBOL": "NIFTY",
                "EXPIRY_DT": row.get("EXPIRY_DT", "").strip(),
                "STRIKE_PR": parse_float(row.get("STRIKE_PR", "")),
                "OPTION_TYP": row.get("OPTION_TYP", "").strip(),
                "OPEN": parse_float(row.get("OPEN", "")),
                "HIGH": parse_float(row.get("HIGH", "")),
                "LOW": parse_float(row.get("LOW", "")),
                "CLOSE": parse_float(row.get("CLOSE", "")),
                "SETTLE_PR": parse_float(row.get("SETTLE_PR", "")),
                "CONTRACTS": parse_float(row.get("CONTRACTS", "")),
                "VAL_INLAKH": parse_float(row.get("VAL_INLAKH", "")),
                "OPEN_INT": parse_float(row.get("OPEN_INT", "")),
                "CHG_IN_OI": parse_float(row.get("CHG_IN_OI", "")),
                "DATE": row.get("TIMESTAMP", "").strip(),
                "t": t,
                "isoDt": iso_dt,
            })
    os.remove(csv_path)
    return docs


current = start_date
total_inserted = 0
errors = []

print(f"Fetching NIFTY options data from {start_date} to {end_date}")
print(f"Inserting into MongoDB: {settings.DB_NAME}.{COLLECTION}")
print("-" * 60)

while current <= end_date:
    if current.weekday() >= 5:
        current += timedelta(days=1)
        continue

    try:
        if current >= NEW_FORMAT_CUTOFF:
            csv_text = fetch_new_bhavcopy_csv(current)
            if csv_text is None:
                raise Exception("No data / holiday")
            docs = parse_new_format(csv_text)
        else:
            docs = fetch_old_bhavcopy_docs(current)

        if docs:
            try:
                result = col.insert_many(docs, ordered=False)
                count = len(result.inserted_ids)
            except Exception as e:
                count = getattr(e, "details", {}).get("nInserted", 0)
            total_inserted += count
            print(f"{current} -> {count} NIFTY options records inserted")
        else:
            print(f"{current} -> no NIFTY options found")
    except Exception as e:
        msg = str(e)
        if any(k in msg.lower() for k in ("holiday", "not available", "404", "no data")):
            print(f"{current} -> holiday/no data")
        else:
            print(f"{current} -> ERROR: {msg}")
            errors.append((current, msg))

    current += timedelta(days=1)
    time.sleep(0.5)

print("-" * 60)
print(f"Done! Total records inserted: {total_inserted}")
print(f"Total records in collection: {col.count_documents({})}")
if errors:
    print(f"\nErrors on {len(errors)} days:")
    for d, e in errors:
        print(f"  {d}: {e}")

MongoRepository.close()

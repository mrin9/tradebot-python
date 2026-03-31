from datetime import datetime, timedelta, timezone
import random
import re
import string

import pytz

# Constants
MARKET_TZ = pytz.timezone("Asia/Kolkata")
UTC_TZ = pytz.utc
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
FMT_ISO_DATE = DATE_FORMAT
FMT_CLI_FULL = "%Y-%m-%d %H:%M:%S"


class DateUtils:
    """
    Standardized date and time utilities for the trade-bot project.
    Enforces Asia/Kolkata for inputs/display and UTC for internal storage where applicable.
    """

    MARKET_TZ = MARKET_TZ
    UTC_TZ = UTC_TZ
    DATE_FORMAT = DATE_FORMAT
    DATETIME_FORMAT = DATETIME_FORMAT

    @staticmethod
    def to_utc(dt: datetime) -> datetime:
        """Converts a datetime object to UTC."""
        if dt.tzinfo is None:
            # Assume it's in MARKET_TZ if naive, or raise warning?
            # For safety, let's localize to MARKET_TZ first if naive
            dt = MARKET_TZ.localize(dt)
        return dt.astimezone(UTC_TZ)

    @staticmethod
    def to_iso(dt: datetime) -> str:
        """Returns ISO 8601 formatted string with timezone offset (e.g. 2026-03-08T10:00:00+05:30)."""
        if dt.tzinfo is None:
            dt = MARKET_TZ.localize(dt)
        return dt.isoformat(timespec="seconds")

    @staticmethod
    def to_iso_date(dt: datetime) -> str:
        """Returns ISO 8601 date string (YYYY-MM-DD)."""
        return dt.strftime(DATE_FORMAT)

    @staticmethod
    def to_timestamp(dt: datetime, end_of_day: bool = False) -> int:
        """
        Converts a datetime to a UNIX timestamp.
        If end_of_day is True, sets the time to the end of that day (23:59:59).
        """
        if dt.tzinfo is None:
            dt = MARKET_TZ.localize(dt)

        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)

        return int(dt.timestamp())

    # XTS Epoch Offset: 10 years (1970 to 1980) including leap years 1972, 1976
    # 3652 days * 86400 seconds = 315532800
    XTS_EPOCH_OFFSET = 315532800

    @staticmethod
    def _check_bounds(ts: float, source: str) -> float:
        """Sanity check: Warns if the timestamp is > 1 day in the future."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).timestamp()
        if ts > (now + 86400):
            import logging

            logging.getLogger(__name__).warning(f"Anomalous timestamp from {source}: {ts} (>{now + 86400})")
        return ts

    @staticmethod
    def rest_timestamp_to_utc(ts: int | float) -> float:
        """
        XTS REST API (Historical OHLC): 1970-base, IST-shifted.
        Subtracts 19800 to convert to true UTC Epoch (seconds).
        """
        from packages.settings import settings

        if not ts:
            return 0.0
        utc_ts = float(ts) - settings.XTS_TIME_OFFSET
        return DateUtils._check_bounds(utc_ts, "REST")

    @staticmethod
    def socket_timestamp_to_utc(ts: int | float) -> float:
        """
        XTS Socket (Real-time 1501/1505): 1980-base, IST-shifted.
        Adds 10 years (315532800) and subtracts 19800 to get true UTC Epoch (seconds).
        """
        from packages.settings import settings

        if not ts:
            return 0.0
        utc_ts = float(ts) + DateUtils.XTS_EPOCH_OFFSET - settings.XTS_TIME_OFFSET
        return DateUtils._check_bounds(utc_ts, "SOCKET")

    @staticmethod
    def market_timestamp_to_iso(ts: int | float) -> str:
        """Converts a market/feed UTC epoch timestamp to Asia/Kolkata ISO string with offset."""
        if ts is None or ts == 0:
            return ""
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        dt_kolkata = dt.astimezone(MARKET_TZ)
        return dt_kolkata.isoformat(timespec="seconds")

    @staticmethod
    def market_timestamp_to_datetime(ts: int | float) -> datetime:
        """Converts a market/feed UNIX timestamp to a localized Asia/Kolkata datetime object."""
        return datetime.fromtimestamp(ts, tz=MARKET_TZ)

    @staticmethod
    def parse_iso(date_str: str) -> datetime:
        """Parses ISO string into a localized datetime object. Handles offsets if present."""
        if not date_str:
            return datetime.now(MARKET_TZ)

        try:
            # Normalize 'Z' to '+00:00' for fromisoformat compatibility on older Py3
            normalized = date_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                return MARKET_TZ.localize(dt)
            return dt.astimezone(MARKET_TZ)
        except Exception:
            # Fallback for non-standard formats (e.g. spaces instead of T, or sub-seconds)
            try:
                clean_str = date_str.replace("T", " ").split(".")[0].strip()
                dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
                return MARKET_TZ.localize(dt)
            except Exception:
                # Last resort: just date
                try:
                    dt = datetime.strptime(date_str.split("T", maxsplit=1)[0], "%Y-%m-%d")
                    return MARKET_TZ.localize(dt)
                except Exception:
                    return datetime.now(MARKET_TZ)

    @staticmethod
    def parse_date_range(range_str: str) -> tuple[datetime, datetime]:
        """
        Parses a date range string in the format 'start|end'.
        Supports keywords: 'now', 'yesterday', 'today', '2dago', etc.
        Example: '2dago|now' -> (2 days ago start of day, current time)
        """
        if "|" not in range_str:
            # Treat as single date/start point? Or imply |now?
            # For now, let's assume it's a single date for start, and end is end of that day
            start_str = range_str
            end_str = range_str  # If single date, range is that full day?
            # Or maybe single date implies start=date, end=now?
            # Let's stick to the separator rule for clarity, but handle single dates as full day
            pass
        else:
            start_str, end_str = range_str.split("|")

        start_dt = DateUtils._parse_keyword(start_str, is_end=False)
        end_dt = DateUtils._parse_keyword(end_str, is_end=True)

        return start_dt, end_dt

    @staticmethod
    def _parse_keyword(keyword: str, is_end: bool = False) -> datetime:
        now = datetime.now(MARKET_TZ)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)

        keyword = keyword.lower().strip()

        if keyword == "now":
            return now
        elif keyword == "today":
            return today if not is_end else today.replace(hour=23, minute=59, second=59)
        elif keyword == "yesterday":
            Yesterday = today - timedelta(days=1)
            return Yesterday if not is_end else Yesterday.replace(hour=23, minute=59, second=59)
        elif "dago" in keyword:
            try:
                days = int(keyword.replace("dago", ""))
                target_date = today - timedelta(days=days)
                return target_date if not is_end else target_date.replace(hour=23, minute=59, second=59)
            except ValueError:
                pass  # Fall through to ISO parse

        if keyword == "":
            return now if is_end else today  # Default empty start to today start, empty end to now?

        # Try parsing as explicit date
        try:
            dt = DateUtils.parse_iso(keyword)
            # If it was just a date (00:00:00), and we want end, move to end of day
            if is_end and dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError as e:
            raise ValueError(f"Unknown date keyword or format: {keyword}") from e


    @staticmethod
    def get_date_chunks(
        start_dt: datetime, end_dt: datetime, chunk_size_days: int
    ) -> list[tuple[datetime, datetime]]:
        """
        Splits a date range into smaller chunks of 'chunk_size_days'.
        Returns a list of (chunk_start, chunk_end) tuples.
        """
        chunks = []
        current_start = start_dt
        while current_start < end_dt:
            current_end = min(current_start + timedelta(days=chunk_size_days), end_dt)
            chunks.append((current_start, current_end))
            current_start = current_end + timedelta(seconds=1)
        return chunks

    @staticmethod
    def get_available_dates(db, collection_name: str) -> list[str]:
        """
        Scans a collection for unique trading days (YYYY-MM-DD).
        Relies on the 't' (timestamp) field.
        """
        pipeline = [
            {
                "$project": {
                    "date": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": {"$toDate": {"$multiply": ["$t", 1000]}},
                            "timezone": "Asia/Kolkata",
                        }
                    }
                }
            },
            {"$group": {"_id": "$date"}},
            {"$sort": {"_id": 1}},
        ]
        results = db[collection_name].aggregate(pipeline)
        return [r["_id"] for r in results if r["_id"]]

    @staticmethod
    def generate_session_id(strategy_id: str = "default", custom_time: datetime | None = None) -> str:
        """
        Generates a standardized session ID: monthday-hourminute-strategyPrefix-rand3-python
        Example: mar12-0928-triple-hlf-python
        """

        real_now = datetime.now(DateUtils.MARKET_TZ)
        # We use custom_time (the backtest start date) for date_part, but current real time for time_part
        date_part = (custom_time or real_now).strftime("%b%d").lower()
        time_part = real_now.strftime("%H%M")

        # Extract first word of strategy indicator (clean prefix)
        clean_prefix = re.split("[-_ ]", str(strategy_id or "default"))[0][:10].lower()

        rand_alpha = "".join(random.choices(string.ascii_lowercase + string.digits, k=3))

        return f"{date_part}-{time_part}-{clean_prefix}-{rand_alpha}-python"

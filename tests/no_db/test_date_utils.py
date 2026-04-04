"""Unit tests for packages.utils.date_utils.DateUtils — pure logic, no DB."""

from datetime import datetime, timedelta, timezone

import pytz
import pytest

from packages.utils.date_utils import DateUtils, MARKET_TZ


# ── to_utc ──────────────────────────────────────────────────────────────────

class TestToUtc:
    def test_naive_datetime_assumed_market_tz(self):
        """Naive datetime is localized to Asia/Kolkata before converting to UTC."""
        naive = datetime(2026, 1, 1, 12, 0, 0)
        result = DateUtils.to_utc(naive)
        assert result.tzinfo == pytz.utc
        assert result.hour == 6  # 12:00 IST = 06:30 UTC
        assert result.minute == 30

    def test_aware_datetime_converted(self):
        """Already-aware datetime is converted correctly."""
        aware = MARKET_TZ.localize(datetime(2026, 3, 15, 9, 15, 0))
        result = DateUtils.to_utc(aware)
        assert result.tzinfo == pytz.utc
        assert result.hour == 3
        assert result.minute == 45


# ── to_iso ──────────────────────────────────────────────────────────────────

class TestToIso:
    def test_naive_gets_offset(self):
        """Naive datetime gets +05:30 offset."""
        result = DateUtils.to_iso(datetime(2026, 6, 1, 10, 0, 0))
        assert "+05:30" in result
        assert result.startswith("2026-06-01T10:00:00")

    def test_aware_preserves_offset(self):
        dt = MARKET_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
        assert DateUtils.to_iso(dt) == "2026-01-01T00:00:00+05:30"


# ── to_timestamp ────────────────────────────────────────────────────────────

class TestToTimestamp:
    def test_basic(self):
        dt = MARKET_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
        ts = DateUtils.to_timestamp(dt)
        assert isinstance(ts, int)
        assert ts > 0

    def test_end_of_day(self):
        dt = MARKET_TZ.localize(datetime(2026, 1, 1, 0, 0, 0))
        ts_eod = DateUtils.to_timestamp(dt, end_of_day=True)
        ts_start = DateUtils.to_timestamp(dt)
        assert ts_eod > ts_start
        # Difference should be ~86399 seconds
        assert 86398 <= (ts_eod - ts_start) <= 86400


# ── XTS timestamp conversions ──────────────────────────────────────────────

class TestXtsTimestamps:
    def test_rest_timestamp_zero(self):
        assert DateUtils.rest_timestamp_to_utc(0) == 0.0

    def test_rest_timestamp_subtracts_offset(self):
        result = DateUtils.rest_timestamp_to_utc(1700000000)
        # Should subtract 19800 (XTS_TIME_OFFSET)
        assert result == 1700000000 - 19800

    def test_socket_timestamp_zero(self):
        assert DateUtils.socket_timestamp_to_utc(0) == 0.0

    def test_socket_timestamp_adds_epoch_subtracts_offset(self):
        result = DateUtils.socket_timestamp_to_utc(1000000)
        expected = 1000000 + 315532800 - 19800
        assert result == expected


# ── parse_iso ───────────────────────────────────────────────────────────────

class TestParseIso:
    def test_standard_iso(self):
        dt = DateUtils.parse_iso("2026-03-15T10:30:00+05:30")
        assert dt.hour == 10
        assert dt.minute == 30

    def test_z_suffix(self):
        dt = DateUtils.parse_iso("2026-03-15T05:00:00Z")
        # UTC 05:00 = IST 10:30
        assert dt.hour == 10
        assert dt.minute == 30

    def test_date_only(self):
        dt = DateUtils.parse_iso("2026-03-15")
        assert dt.year == 2026
        assert dt.month == 3
        assert dt.day == 15

    def test_empty_returns_now(self):
        dt = DateUtils.parse_iso("")
        assert dt.tzinfo is not None
        assert (datetime.now(MARKET_TZ) - dt).total_seconds() < 2


# ── parse_date_range ────────────────────────────────────────────────────────

class TestParseDateRange:
    def test_keywords(self):
        start, end = DateUtils.parse_date_range("2dago|now")
        now = datetime.now(MARKET_TZ)
        assert start.day == (now - timedelta(days=2)).day
        assert (now - end).total_seconds() < 2

    def test_today_keyword(self):
        start, end = DateUtils.parse_date_range("today|today")
        assert start.hour == 0
        assert end.hour == 23
        assert end.minute == 59

    def test_yesterday(self):
        start, end = DateUtils.parse_date_range("yesterday|yesterday")
        yesterday = datetime.now(MARKET_TZ) - timedelta(days=1)
        assert start.day == yesterday.day
        assert end.hour == 23


# ── get_date_chunks ─────────────────────────────────────────────────────────

class TestGetDateChunks:
    def test_single_chunk(self):
        start = MARKET_TZ.localize(datetime(2026, 1, 1))
        end = MARKET_TZ.localize(datetime(2026, 1, 3))
        chunks = DateUtils.get_date_chunks(start, end, chunk_size_days=5)
        assert len(chunks) == 1
        assert chunks[0] == (start, end)

    def test_multiple_chunks(self):
        start = MARKET_TZ.localize(datetime(2026, 1, 1))
        end = MARKET_TZ.localize(datetime(2026, 1, 10))
        chunks = DateUtils.get_date_chunks(start, end, chunk_size_days=3)
        assert len(chunks) >= 3
        assert chunks[0][0] == start
        assert chunks[-1][1] == end

    def test_empty_range(self):
        dt = MARKET_TZ.localize(datetime(2026, 1, 1))
        chunks = DateUtils.get_date_chunks(dt, dt, chunk_size_days=1)
        assert len(chunks) == 0


# ── market_timestamp_to_iso ─────────────────────────────────────────────────

class TestMarketTimestampToIso:
    def test_zero_returns_empty(self):
        assert DateUtils.market_timestamp_to_iso(0) == ""

    def test_none_returns_empty(self):
        assert DateUtils.market_timestamp_to_iso(None) == ""

    def test_valid_timestamp(self):
        # 2026-01-01 00:00:00 UTC = 2026-01-01 05:30:00 IST
        ts = 1767225600
        result = DateUtils.market_timestamp_to_iso(ts)
        assert "+05:30" in result


# ── generate_session_id ─────────────────────────────────────────────────────

class TestGenerateSessionId:
    def test_format(self):
        sid = DateUtils.generate_session_id("triple-confirmation")
        parts = sid.split("-")
        assert len(parts) == 5  # date-time-prefix-rand-python
        assert parts[-1] == "python"
        assert len(parts[3]) == 3  # random 3 chars

    def test_custom_time(self):
        custom = MARKET_TZ.localize(datetime(2026, 3, 15, 10, 0, 0))
        sid = DateUtils.generate_session_id("test", custom_time=custom)
        assert sid.startswith("mar15-")

    def test_default_strategy(self):
        sid = DateUtils.generate_session_id()
        parts = sid.split("-")
        assert parts[2] == "default"

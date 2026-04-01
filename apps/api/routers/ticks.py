from datetime import datetime, timedelta

import polars as pl
from fastapi import APIRouter, HTTPException, Query

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import get_db
from packages.xts.xts_normalizer import XTSNormalizer

router = APIRouter(prefix="/api/ticks", tags=["ticks"])


def parse_interval(interval_str: str) -> int:
    """Convert interval string (e.g., '1m', '5m', '1h') to seconds."""
    unit = interval_str[-1]
    value = int(interval_str[:-1])
    if unit == "s":
        return value
    if unit == "m":
        return value * 60
    if unit == "h":
        return value * 3600
    if unit == "d":
        return value * 86400
    return 60  # Default


@router.get("")
async def get_ticks(
    id: str,
    interval: str = Query("1m", alias="candle-interval"),
    limit: int = 1200,
    start_dt: str | None = Query(None, alias="start-dt"),
    end_dt: str | None = Query(None, alias="end-dt"),
    skip_metadata: bool = Query(False, alias="skip-metadata"),
):
    """
    Fetch and Resample Ticks/Candles.
    Expected response format: { ticks: [...], hasMoreOld: bool, hasMoreNew: bool }
    """
    db = get_db()

    # 1. Resolve Instrument ID
    try:
        inst_id = XTSNormalizer.get_instrument_id(db, id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=f"Instrument {id} not found") from e


    # 2. Choose collection based on resolved Instrument ID
    if inst_id == settings.NIFTY_INSTRUMENT_ID:
        collection_name = settings.NIFTY_CANDLE_COLLECTION
    else:
        # All other FO/Options go to options_candle
        collection_name = settings.OPTIONS_CANDLE_COLLECTION
    # Find latest data point for this instrument
    latest_record = db[collection_name].find_one({"i": inst_id}, sort=[("t", -1)])
    latest_t = latest_record["t"] if latest_record else None

    query = {"i": inst_id}
    time_query = {}

    requested_start_t = None
    requested_end_t = None

    if start_dt:
        dt_start = DateUtils.parse_iso(start_dt)
        requested_start_t = DateUtils.to_timestamp(dt_start)
    if end_dt:
        dt_end = DateUtils.parse_iso(end_dt)
        requested_end_t = DateUtils.to_timestamp(dt_end)

    # Shifting logic: if end_dt is in the future or past lateast data, shift window back
    if latest_t and requested_end_t and requested_end_t > latest_t:
        offset = requested_end_t - latest_t
        requested_end_t = latest_t
        if requested_start_t:
            requested_start_t -= offset

    if requested_start_t:
        time_query["$gte"] = requested_start_t
    elif not requested_end_t:
        # Default to last 5 days
        dt = datetime.now(DateUtils.MARKET_TZ) - timedelta(days=5)
        time_query["$gte"] = DateUtils.to_timestamp(dt)

    if requested_end_t:
        time_query["$lte"] = requested_end_t

    if time_query:
        query["t"] = time_query

    # 3. Fetch Data
    interval_seconds = parse_interval(interval)
    fetch_limit = (limit + 1) * (interval_seconds // 60 if interval_seconds > 60 else 1) * 2

    # Sort DESC to get latest records in the window
    cursor = db[collection_name].find(query).sort("t", -1).limit(fetch_limit)
    data = list(cursor)
    data.reverse()  # Sort back to chronological for Polars

    if not data:
        return {"ticks": [], "hasMoreOld": False, "hasMoreNew": False} if not skip_metadata else []

    # 4. Resample using Polars
    df = pl.DataFrame(data)
    df = df.with_columns(
        pl.from_epoch(pl.col("t"), time_unit="s").dt.replace_time_zone("UTC").dt.convert_time_zone("Asia/Kolkata")
    )

    period = f"{interval_seconds}s"
    resampled = (
        df.sort("t")
        .group_by_dynamic("t", every=period)
        .agg(
            [
                pl.col("o").first().alias("o"),
                pl.col("h").max().alias("h"),
                pl.col("l").min().alias("l"),
                pl.col("c").last().alias("c"),
                pl.col("v").sum().alias("v"),
            ]
        )
    )

    # 5. Format Response
    result_ticks = []
    for row in resampled.iter_rows(named=True):
        result_ticks.append(
            {"t": int(row["t"].timestamp()), "o": row["o"], "h": row["h"], "l": row["l"], "c": row["c"], "v": row["v"]}
        )

    # Calculate more flags
    has_more_old = False
    if result_ticks:
        earliest_returned_t = result_ticks[0]["t"]
        # Explicit check for data BEFORE our earliest resampled tick
        more_old = db[collection_name].find_one({"i": inst_id, "t": {"$lt": earliest_returned_t}})
        has_more_old = more_old is not None

    if len(result_ticks) > limit:
        result_ticks = result_ticks[-limit:]
        has_more_old = True  # We truncated, so there is definitely more old data

    has_more_new = False
    if result_ticks and latest_t:
        # If we didn't shift or even if we did, check if there's any data LATER than our newest tick
        newest_returned_t = result_ticks[-1]["t"]
        # A tick covers [t, t + interval), so next tick starts at t + interval
        has_more_new = newest_returned_t + interval_seconds <= latest_t

    if skip_metadata:
        return result_ticks

    return {"ticks": result_ticks, "hasMoreOld": has_more_old, "hasMoreNew": has_more_new}

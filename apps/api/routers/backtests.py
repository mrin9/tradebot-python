from fastapi import APIRouter

from packages.settings import settings
from packages.utils.mongo import get_db, serialize_mongo

router = APIRouter(prefix="/api/backtests", tags=["backtests"])


@router.get("")
async def get_backtests():
    db = get_db()
    # Exclude _id and heavy fields to keep the summary list light
    projection = {"_id": 0, "trades": 0, "tradeCycles": 0, "dailyPnl": 0, "instrumentsTraded": 0}
    
    results = list(
        db[settings.BACKTEST_RESULT_COLLECTION]
        .find({}, projection)
        .sort([("createdAt", -1), ("timestamp", -1)])
        .limit(50)
    )

    processed = []
    for res in results:
        # Convert any remaining ObjectIds (e.g. in config) to strings
        res = serialize_mongo(res)
        processed.append(res)

    return processed


@router.get("/{sessionId}")
async def get_backtest_detail(sessionId: str):
    db = get_db()
    # Use strict sessionId for retrieval
    query = {"sessionId": sessionId}
    res = db[settings.BACKTEST_RESULT_COLLECTION].find_one(query, {"_id": 0})
    if res:
        return serialize_mongo(res)
    return {}

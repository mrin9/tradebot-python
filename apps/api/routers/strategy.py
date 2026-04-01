from typing import Any

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.settings import settings
from packages.utils.mongo import get_db, serialize_mongo

router = APIRouter(prefix="/api/strategy-indicators", tags=["strategy-indicators"])


class StrategyIndicator(BaseModel):
    strategyId: str
    name: str = "Default"
    enabled: bool = True
    timeframeSeconds: int = 180
    pythonStrategyPath: str | None = None
    indicators: list[dict[str, Any]] = []


@router.get("")
async def get_strategies():
    db = get_db()
    # Exclude raw _id from the list
    strategies = list(db[settings.STRATEGY_INDICATORS_COLLECTION].find({}, {"_id": 0}))

    processed = []
    for s in strategies:
        # Use serialize_mongo for safety against nested ObjectIds
        s = serialize_mongo(s)
        processed.append(s)

    return processed


@router.get("/{id}")
async def get_strategy(id: str):
    db = get_db()
    try:
        query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"strategyId": id}
        # Exclude raw _id from detail response
        strategy = db[settings.STRATEGY_INDICATORS_COLLECTION].find_one(query, {"_id": 0})
        if strategy:
            strategy = serialize_mongo(strategy)
            return strategy
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error retrieving strategy: {e!s}") from e

    return {}


@router.post("")
async def create_strategy(strategy: StrategyIndicator):
    db = get_db()
    doc = strategy.dict()
    res = db[settings.STRATEGY_INDICATORS_COLLECTION].insert_one(doc)
    return {"id": str(res.inserted_id), "status": "created"}


@router.put("/{id}")
async def update_strategy(id: str, strategy: StrategyIndicator):
    db = get_db()
    query = {"_id": ObjectId(id)} if ObjectId.is_valid(id) else {"strategyId": id}
    db[settings.STRATEGY_INDICATORS_COLLECTION].update_one(query, {"$set": strategy.dict()})
    return {"status": "updated"}


@router.post("/reset")
async def reset_strategies():
    """Trigger the seeding script to reset strategy indicators."""
    try:
        from packages.db.seed_strategy_indicators import seed_strategy_indicators

        seed_strategy_indicators()
        return {"status": "ok", "message": "Strategy indicators reset to factory defaults"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


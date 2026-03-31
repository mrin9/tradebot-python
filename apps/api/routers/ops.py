import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

logger = logging.getLogger("apps.api.ops")
router = APIRouter(prefix="/api/ops", tags=["Operations"])


class OperationResponse(BaseModel):
    status: str
    message: str
    task_id: str | None = None


@router.post("/indicators/update", response_model=OperationResponse)
async def update_indicators(background_tasks: BackgroundTasks):
    """
    Trigger re-calculation of technical indicators for all active instruments.
    """
    raise HTTPException(status_code=501, detail="Not Implemented: Delegate to CLI logic")


@router.post("/data/age-out", response_model=OperationResponse)
async def age_out_data(background_tasks: BackgroundTasks):
    """
    Age out old tick data by moving it to historical archives or deleting it.
    """
    raise HTTPException(status_code=501, detail="Not Implemented: Use CLI age_out command")


@router.post("/master/update", response_model=OperationResponse)
async def update_master_instruments(background_tasks: BackgroundTasks):
    """
    Synchronize the local instrument master with the XTS API.
    """
    raise HTTPException(status_code=501, detail="Not Implemented: Use CLI update_master command")


@router.post("/data/history", response_model=OperationResponse)
async def update_history(background_tasks: BackgroundTasks):
    """
    Fetch and backfill historical data for the currently tracked instruments.
    """
    raise HTTPException(status_code=501, detail="Not Implemented: Use CLI sync_history command")

import traceback

import socketio
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routers import backtests, instruments, ops, strategy, ticks
from apps.api.socket_instance import sio
from packages.utils.log_utils import setup_logger

logger = setup_logger("API_GLOBAL")

# Initialize FastAPI
app = FastAPI(title="Trade Bot API")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled Exception: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation Error: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": "Validation Error", "errors": exc.errors()},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Socket.IO
# sio is imported from apps.api.socket_instance
socket_app = socketio.ASGIApp(sio, app)

# Routers
app.include_router(instruments.router)
app.include_router(ticks.router)
app.include_router(backtests.router)
app.include_router(strategy.router)
app.include_router(ops.router)


@app.get("/api/status")
async def status():
    return {"status": "ok", "version": "v2"}


# Socket Events (Placeholder for now)
@sio.event
async def connect(sid, environ):
    logger.info(f"Socket Connected: {sid}")


@sio.event
async def disconnect(sid):
    logger.info(f"Socket Disconnected: {sid}")


# To run: uvicorn apps.api.main:socket_app --reload

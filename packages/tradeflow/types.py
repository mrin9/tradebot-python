from datetime import datetime
from enum import Enum, auto
from typing import NewType, TypedDict

from pydantic import BaseModel


class SignalType(Enum):
    LONG = 1
    SHORT = -1
    NEUTRAL = 0
    EXIT = 2


class MarketIntentType(Enum):
    LONG = auto()
    SHORT = auto()


class InstrumentKindType(Enum):
    CASH = auto()
    FUTURES = auto()
    OPTIONS = auto()


class InstrumentCategoryType(Enum):
    SPOT = "SPOT"
    CE = "CE"
    PE = "PE"
    OPTIONS_BOTH = "OPTIONS_BOTH"  # Pseudo-category for Rule seeding


class CandleType(TypedDict):
    """
    Represents a finalized resampled candle.
    Used across all strategy types (Rule, ML, Python).
    """

    instrument_id: int
    timestamp: int  # Unix epoch seconds (period start)
    open: float
    high: float
    low: float
    close: float
    volume: int
    is_final: bool


# Strong Typing for Timestamps
UtcTimestamp = NewType("UtcTimestamp", float)  # Seconds since 1970 UTC
XtsRestTimestamp = NewType("XtsRestTimestamp", int)  # Seconds since 1970 IST (Shifted)
XtsSocketTimestamp = NewType("XtsSocketTimestamp", int)  # Seconds since 1980 IST (Shifted)

# Type Aliases for cleaner signatures
SignalReturnType = tuple[SignalType, str, float]


class SignalPayload(BaseModel):
    """
    Unified payload passed from FundManager down to PositionManager.
    """

    signal: MarketIntentType
    price: float
    timestamp: float | datetime
    symbol: str | int
    display_symbol: str
    confidence: float = 0.0
    reason: str = "N/A"
    reason_desc: str = ""
    nifty_price: float = 0.0
    is_continuity: bool = False

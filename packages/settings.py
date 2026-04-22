from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 1. MongoDB Settings
    MONGODB_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "tradebot"

    @property
    def COLLECTION_SUFFIX(self) -> str:
        if self.DB_NAME == "tradebot_test":
            return "_test"
        if self.DB_NAME == "tradebot_frozen":
            return "_frozen"
        return ""

    @property
    def NIFTY_CANDLE_COLLECTION(self) -> str:
        return f"nifty_candle{self.COLLECTION_SUFFIX}"

    @property
    def OPTIONS_CANDLE_COLLECTION(self) -> str:
        return f"options_candle{self.COLLECTION_SUFFIX}"

    @property
    def STOCK_TICKS_PER_SECOND_COLLECTION(self) -> str:
        return f"stockticks_per_second{self.COLLECTION_SUFFIX}"

    @property
    def ACTIVE_CONTRACT_COLLECTION(self) -> str:
        return f"active_contract{self.COLLECTION_SUFFIX}"

    @property
    def INSTRUMENT_MASTER_COLLECTION(self) -> str:
        return f"instrument_master{self.COLLECTION_SUFFIX}"

    @property
    def STOCK_INDICATOR_COLLECTION(self) -> str:
        return f"stock_indicator{self.COLLECTION_SUFFIX}"

    @property
    def BACKTEST_RESULT_COLLECTION(self) -> str:
        return f"backtest{self.COLLECTION_SUFFIX}"

    @property
    def STRATEGY_INDICATORS_COLLECTION(self) -> str:
        return f"strategy_indicator{self.COLLECTION_SUFFIX}"

    @property
    def LIVE_TRADES_COLLECTION(self) -> str:
        return f"livetrade{self.COLLECTION_SUFFIX}"

    @property
    def PAPERTRADE_COLLECTION(self) -> str:
        return f"papertrade{self.COLLECTION_SUFFIX}"

    # 1.5 NIFTY Specifics
    NIFTY_EXCHANGE_SEGMENT: int = 1
    NIFTY_INSTRUMENT_ID: int = 26000
    NIFTY_LOT_SIZE: int = 65
    NIFTY_STRIKE_STEP: int = 50

    OPTIONS_STRIKE_COUNT: int = 20  # ATM +/- 20 strikes (Aligned with Java)
    SYNC_HISTORY_WORKERS: int = 4  # Concurrent workers for historical sync

    GLOBAL_WARMUP_CANDLES: int = 250
    TRADE_PRICE_SOURCE: str = "open"  # 'open' better mimics live entry since backtests use 1-min candles 
    TRADE_INVEST_MODE: str = "fixed"
    TRADE_BUDGET: str = "200000-inr"

    # Trade Defaults (Percentage-based & General)
    TRADE_STOP_LOSS_PCT: float = 7.0
    TRADE_TARGET_PCT_STEPS: str = "4"
    TRADE_TSL_PCT: float = 7
    TRADE_TSL_ID: str = "trade-ema-5"
    TRADE_USE_BE: bool = True
    TRADE_INSTRUMENT_TYPE: str = "OPTIONS"
    TRADE_STRIKE_SELECTION: str = "ATM"
    TRADE_PYRAMID_STEPS: str = "100"
    TRADE_PYRAMID_CONFIRM_PTS: float = 10.0

    # 2. Core Operation Modes
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    DEFAULT_TIMEFRAME: int = 180
    TRADE_START_TIME: str = "09:20:00"
    TRADE_LAST_ENTRY_TIME: str = "15:00:00"
    TRADE_SQUARE_OFF_TIME: str = "15:15:00"
    TRADE_EXPIRY_JUMP_CUTOFF: str = "14:30:00"
    LOG_HEARTBEAT: bool = False
    LOG_ACTIVE_INDICATOR: bool = False
    ARCHIVE_FNO_EQUITIES: bool = True

    # 4. Socket & Simulator Settings
    SOCKET_SIMULATOR_URL: str = "http://localhost:5050"

    # 6. XTS API Configuration
    XTS_ROOT_URL: str = "https://blazemum.indiainfoline.com"
    XTS_SOURCE: str = "WEBAPI"
    XTS_DISABLE_SSL: bool = True
    XTS_BROADCAST_MODE: Literal["Full", "Partial"] = "Full"

    # XTS Time Offset: API returns timestamps shifted by +5.5h (treats IST as UTC)
    XTS_TIME_OFFSET: int = 19800

    # 7. Sensitive API Credentials (Stored in .env)
    MARKET_API_KEY: str | None = None
    MARKET_API_SECRET: str | None = None
    INTERACTIVE_API_KEY: str | None = None
    INTERACTIVE_API_SECRET: str | None = None

    # Mock Trading
    USE_MOCK_ORDER_MANAGER: bool = True
    MOCK_SIMULATE_MARGIN_REJECTION: bool = False
    MOCK_AVAILABLE_MARGIN: float = 500000.0

    @field_validator("*", mode="after")
    @classmethod
    def unescape_dollar_signs(cls, v):
        if isinstance(v, str):
            return v.replace("$$", "$")
        return v

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()

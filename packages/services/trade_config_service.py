from typing import Any

from packages.settings import settings
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger("TradeConfigService")


class TradeConfigService:
    """
    Centralized service for building, validating, and normalizing trade configurations.
    Consolidates logic from CLI, Backtest Runner, and FundManager.
    """

    @staticmethod
    def fetch_strategy_config(strategy_id: str) -> dict[str, Any]:
        """
        Fetches strategy configuration from MongoDB by strategyId.
        Centralizes logic previously split between BacktestRunner and CLI.
        """
        db = MongoRepository.get_db()
        # Use a setting for this collection name to allow environment-aware redirection
        coll_name = getattr(settings, "STRATEGY_INDICATORS_COLLECTION", "strategy_indicators")
        strategy = db[coll_name].find_one({"strategyId": strategy_id})

        if not strategy:
            raise ValueError(f"Strategy ID '{strategy_id}' not found in '{settings.STRATEGY_INDICATORS_COLLECTION}' collection.")

        # Normalize and return
        return TradeConfigService.normalize_strategy_config(strategy)

    @staticmethod
    def normalize_strategy_config(raw_config: dict[str, Any]) -> dict[str, Any]:
        """
        Normalizes a strategy document (e.g. from DB) into the internal format.
        Handles casing differences like 'Indicators' vs 'indicators'.
        """
        normalized = raw_config.copy()

        # 1. Normalize Indicators Key
        if "Indicators" in normalized and "indicators" not in normalized:
            normalized["indicators"] = normalized.pop("Indicators")
        elif "indicators" not in normalized:
            normalized["indicators"] = []

        # 2. Normalize basic fields
        if "timeframe" in normalized and "timeframeSeconds" not in normalized:
            normalized["timeframeSeconds"] = normalized.pop("timeframe")

        if "timeframe_seconds" in normalized and "timeframeSeconds" not in normalized:
            normalized["timeframeSeconds"] = normalized.pop("timeframe_seconds")

        # 3. Standardize common configuration fields to camelCase
        mappings = {
            "sl_pct": "slPct",
            "target_pct": "targetPct",
            "tsl_pct": "tslPct",
            "tsl_id": "tslId",
            "use_be": "useBe",
            "instrument_type": "instrumentType",
            "strike_selection": "strikeSelection",
            "invest_mode": "investMode",
            "python_strategy_path": "pythonStrategyPath",
            "pyramid_steps": "pyramidSteps",
            "pyramid_confirm_pts": "pyramidConfirmPts",
            "price_source": "priceSource",
            "start_date": "startDate",
            "end_date": "endDate"
        }
        for snake, camel in mappings.items():
            if snake in normalized and camel not in normalized:
                normalized[camel] = normalized.pop(snake)

        normalized.setdefault("strategyId", "default")
        normalized.setdefault("name", "Unnamed Strategy")
        normalized.setdefault("timeframeSeconds", settings.DEFAULT_TIMEFRAME)

        # 3. Normalize individual indicators
        indicators = normalized.get("indicators", [])
        for ind in indicators:
            if "indicator" not in ind and "type" in ind:
                # Construct shorthand like 'rsi-14' or 'ema-20'
                it_type = ind["type"].lower()
                params = ind.get("params", {})
                if it_type in ["rsi", "ema", "sma", "atr", "vwap", "obv"]:
                    period = params.get("period", 14)
                    ind["indicator"] = f"{it_type}-{period}"
                elif it_type == "supertrend":
                    period = params.get("period", 10)
                    mult = params.get("multiplier", 3.0)
                    ind["indicator"] = f"supertrend-{period}-{mult}"
                elif it_type == "macd":
                    fast = params.get("fast", 12)
                    slow = params.get("slow", 26)
                    sig = params.get("signal", 9)
                    ind["indicator"] = f"macd-{fast}-{slow}-{sig}"
                elif it_type == "bbands":
                    period = params.get("period", 20)
                    dev = params.get("stdDev", 2.0)
                    ind["indicator"] = f"bbands-{period}-{dev}"
                else:
                    ind["indicator"] = it_type

        return normalized

    @staticmethod
    def build_position_config(
        budget: str | float = "200000-inr",
        sl_pct: float = 3.0,
        target_pct: str | list[float] = "2,3,4",
        tsl_pct: float = 0.0,
        tsl_id: str | None = "trade-ema-5",
        use_be: bool = True,
        instrument_type: str = "OPTIONS",
        strike_selection: str = "ATM",
        invest_mode: str = "fixed",
        python_strategy_path: str = "packages/tradeflow/python_strategies.py:TripleLockStrategy",
        pyramid_steps: str | list[int] = "100",
        pyramid_confirm_pts: float = 10.0,
        price_source: str = "close",
        symbol: str = "NIFTY",
        **kwargs,
    ) -> dict[str, Any]:
        """
        Factory method to build a validated position_config dictionary.
        """
        # Parse target percentage steps
        if isinstance(target_pct, str):
            targets = [float(x.strip()) for x in target_pct.split(",")]
        else:
            targets = target_pct

        # Parse pyramid steps
        if isinstance(pyramid_steps, str):
            steps = [int(s.strip()) for s in pyramid_steps.split(",")]
        else:
            steps = pyramid_steps

        config = {
            "budget": budget,
            "slPct": sl_pct,
            "targetPct": targets,
            "tslPct": tsl_pct,
            "tslId": tsl_id,
            "useBe": use_be,
            "instrumentType": instrument_type.upper(),
            "strikeSelection": strike_selection.upper(),
            "investMode": invest_mode.lower(),
            "pythonStrategyPath": python_strategy_path,
            "pyramidSteps": steps,
            "pyramidConfirmPts": pyramid_confirm_pts,
            "priceSource": price_source.lower(),
            "symbol": symbol,
        }

        # Merge remaining kwargs, ensuring camelCase for known fields
        for k, v in kwargs.items():
            camel_k = mappings.get(k, k) if 'mappings' in locals() else k
            # Heuristic for internal kwargs that didn't go through mappings
            if k == "sl_pct": camel_k = "slPct"
            elif k == "target_pct": camel_k = "targetPct"
            elif k == "tsl_pct": camel_k = "tslPct"
            
            if camel_k not in config:
                config[camel_k] = v

        # Validation
        if config["investMode"] not in ["fixed", "compound"]:
            raise ValueError(f"Invalid investMode: {investMode}. Must be 'fixed' or 'compound'.")

        if config["instrumentType"] not in ["CASH", "OPTIONS", "FUTURES"]:
            raise ValueError(f"Invalid instrumentType: {instrumentType}")

        if config["slPct"] >= 100.0:
            raise ValueError(f"Invalid slPct: {sl_pct}. Percentage must be less than 100 to avoid zero/negative Stop Loss.")

        return config

from datetime import datetime, timedelta
from typing import Any

from packages.settings import settings
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository
from packages.utils.trade_formatter import TradeFormatter
from packages.utils.trade_persistence import TradePersistence

logger = setup_logger("TradeEventService")


class TradeEventService:
    """
    Centralized sink for all trade-related events (init, signals, trades, summary).
    Handles formatting, logging, and DB persistence.
    """

    def __init__(self, session_id: str, record_papertrade: bool = True):
        self.session_id = session_id
        self.record_papertrade = record_papertrade
        self.persistence = TradePersistence()
        self.db = MongoRepository.get_db()
        self.active_signals: list[dict] = []

    def record_init(self, fund_manager: Any, mode: str = "live"):
        """Records the session initialization."""
        if not self.record_papertrade:
            return

        config = self.build_config_summary(fund_manager, mode=mode)
        event = {"type": "INIT", "msg": "Trading session initialized.", "config": config}
        self._persist_non_position_event(event)

    def record_signal(self, payload: dict):
        """Records a strategy signal."""
        self.active_signals.append(payload)

        # Format and log the signal
        log_msg = TradeFormatter.format_signal(
            signal_name=payload.get("reason_desc", "SIGNAL"),
            reason=payload.get("reason", ""),
            time_str=datetime.fromtimestamp(payload.get("timestamp", 0)).strftime("%H:%M:%S"),
            timeframe=payload.get("timeframe", 0),
            indicators=payload.get("indicators", {}),
            is_continuity=payload.get("is_continuity", False),
        )
        logger.info(log_msg)

    def record_trade_event(self, event_data: dict, fund_manager: Any):
        """
        Records position-specific events (Entry, Target, Exit, SL).
        """
        if not self.record_papertrade:
            return

        nifty_price = fund_manager.latest_tick_prices.get(26000, 0.0)
        pos_manager = fund_manager.position_manager
        pos = pos_manager.current_position

        if pos:
            # Update realised pnl for the session on the position object for formatter
            pos.session_realized_pnl = pos_manager.session_realized_pnl

            # Record via persistence utility
            self.persistence.record_granular_event(
                session_id=self.session_id,
                event_type=event_data.get("type", "EVENT"),
                pos=pos,
                nifty_price=nifty_price,
                msg=event_data.get("transaction"),
                action_pnl=event_data.get("actionPnL", 0.0),
            )

            # If it's an exit or target event, sync the full session summary
            if event_data.get("type", "").lower() in ["exit", "target", "breakeven"]:
                self.sync_session_summary(fund_manager)
        else:
            # Handle events that happen when no position is active (e.g., target hit on closed chunk)
            self._persist_non_position_event(event_data, fund_manager)

    @staticmethod
    def build_config_summary(fund_manager: Any, mode: str = "live") -> dict:
        """
        Builds a comprehensive configuration summary for the session.
        """
        if isinstance(fund_manager, dict):
            # Fallback for unit tests passing dicts
            config = fund_manager.copy()
            if "budget" not in config:
                config["budget"] = 0
            if "investMode" not in config:
                config["investMode"] = "fixed"
            if "slPct" not in config:
                config["slPct"] = 0
            if "targets" not in config:
                config["targets"] = []
            if "tslPct" not in config:
                config["tslPct"] = 0
            if "useBe" not in config:
                config["useBe"] = False
            return config

        config = fund_manager.config.copy()
        config.update(
            {
                "mode": mode,
                "name": fund_manager.config.get("name"),
                "strategyId": fund_manager.config.get("strategyId"),
                "enabled": True,
                "pythonStrategyPath": fund_manager.position_config.get("python_strategy_path")
                or fund_manager.config.get("pythonStrategyPath"),
                "timeframeSeconds": fund_manager.global_timeframe,
                "indicators": [
                    f"{ind.get('InstrumentType', 'SPOT').replace('_', '-')}-{ind.get('indicator', 'N/A')}".upper()
                    for ind in fund_manager.indicator_calculator.config
                ],
                "tslId": fund_manager.tsl_id,
                "budget": fund_manager.position_config.get("budget"),
                "initialBudget": fund_manager.initial_budget,
                "investMode": fund_manager.invest_mode,
                "slPct": fund_manager.sl_pct,
                "targets": fund_manager.target_pct,
                "tslPct": fund_manager.tsl_pct,
                "useBe": fund_manager.use_be,
                "strikeSelection": getattr(fund_manager, "strike_selection", "ATM"),
                "priceSource": getattr(fund_manager, "price_source", "close"),
                "pyramidSteps": fund_manager.position_config.get("pyramid_steps"),
                "pyramidConfirm": fund_manager.position_config.get("pyramid_confirm_pts"),
            }
        )
        return config

    def sync_session_summary(self, fund_manager: Any):
        """
        Synchronizes the current session state to the summary collection.
        """
        try:
            pos_manager = fund_manager.position_manager

            daily_pnl = {}
            today_str = datetime.now(DateUtils.MARKET_TZ).strftime("%Y-%m-%d")
            daily_pnl[today_str] = pos_manager.session_realized_pnl

            # Prepare config summary
            config = self.build_config_summary(fund_manager, mode="live")

            self.persistence.save_session_summary(
                session_id=self.session_id,
                trades=pos_manager.trades_history,
                config=config,
                daily_pnl=daily_pnl,
                is_live=True,
            )
            self.persistence.update_session_status(self.session_id, "ACTIVE", is_live=True)

        except Exception as e:
            logger.error(f"❌ Failed to sync session summary: {e}")

    def _persist_non_position_event(self, event_data: dict, fund_manager: Any | None = None):
        """Helper to persist generic events to papertrade collection."""
        if not self.record_papertrade:
            return

        event_data.update(
            {
                "sessionId": self.session_id,
                "createdAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
            }
        )
        # Remove redundant timestamp
        event_data.pop("timestamp", None)

        try:
            self.db[settings.PAPERTRADE_COLLECTION].insert_one(event_data)
        except Exception as e:
            logger.error(f"❌ Failed to record non-position event: {e}")

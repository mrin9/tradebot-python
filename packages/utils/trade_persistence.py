from datetime import datetime

from packages.settings import settings
from packages.tradeflow.position_manager import Position
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.mongo import MongoRepository

logger = setup_logger(__name__)


class TradePersistence:
    """
    Centralized utility for persisting trade data to MongoDB.
    Uses atomic operators ($push, $set) to ensure data integrity.
    """

    def __init__(self):
        self.db = MongoRepository.get_db()
        self.live_col = settings.LIVE_TRADES_COLLECTION
        self.backtest_col = settings.BACKTEST_RESULT_COLLECTION
        self.paper_col = settings.PAPERTRADE_COLLECTION

    def record_granular_event(
        self,
        session_id: str,
        event_type: str,
        pos: Position,
        nifty_price: float,
        msg: str = "",
        action_pnl: float = 0.0,
    ):
        """
        Records a real-time event to the 'papertrade' collection for granular tracking.
        """
        try:
            event_data = {
                "sessionId": session_id,
                "type": event_type.upper(),
                "createdAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
                "symbol": pos.symbol,
                "description": pos.display_symbol,
                "price": pos.current_price,
                "quantity": pos.remaining_quantity,
                "actionPnL": action_pnl,
                "cyclePnL": pos.total_realized_pnl,
                "totalPnL": getattr(pos, "session_realized_pnl", 0.0),
                "niftyPrice": nifty_price,
                "msg": msg or f"{event_type} for {pos.display_symbol}",
                "isContinuity": getattr(pos, "is_continuity", False),
            }
            self.db[self.paper_col].insert_one(event_data)
        except Exception as e:
            logger.error(f"❌ Failed to record granular event: {e}")

    def sync_live_cycle(self, session_id: str, pos: Position):
        """
        Incrementally updates the 'live_trades' session document with the current cycle state.
        Uses $push for target_events if needed, or updates the entire cycle in a list.
        Actually, for simplicity and reliability, we upsert the entire cycle into the 'tradeCycles' array
        using the cycleId as a key if we use $[].
        """
        try:
            cycle_data = pos.to_cycle_dict()

            # Atomic Update:
            # 1. Try to update existing cycle in the array
            # 2. If not found, push to array

            query = {"sessionId": session_id, "tradeCycles.cycleId": pos.trade_cycle}
            update = {
                "$set": {
                    "tradeCycles.$": cycle_data,
                    "updatedAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
                },
            }


            res = self.db[self.live_col].update_one(query, update)

            if res.matched_count == 0:
                # Cycle doesn't exist, push it
                self.db[self.live_col].update_one(
                    {"sessionId": session_id},
                    {
                        "$push": {"tradeCycles": cycle_data},
                        "$set": {"updatedAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat()},
                    },
                    upsert=True,
                )
        except Exception as e:
            logger.error(f"❌ Failed to sync live cycle: {e}")

    def save_session_summary(
        self, session_id: str, trades: list[Position], config: dict, daily_pnl: dict, is_live: bool = True
    ):
        """
        Finalizes the session document with summary stats and all trade cycles.
        Groups individual chunks by 'trade_cycle' to form unified Cycle objects.
        """
        try:
            col = self.live_col if is_live else self.backtest_col

            # Group Chunks by trade_cycle
            cycle_groups = {}
            for t in trades:
                cid = t.trade_cycle
                if cid not in cycle_groups:
                    cycle_groups[cid] = []
                cycle_groups[cid].append(t)

            # Form Unified Cycles
            trade_cycles = []
            total_session_pnl = 0.0
            for _cid, chunks in cycle_groups.items():
                if not chunks:
                    continue

                # Sort chunks by exit time to identify targets and final exit
                chunks.sort(key=lambda x: x.exit_time if x.exit_time else datetime.max)

                # Use the first chunk as the entry template (they all share entry info)
                entry_template = chunks[0]

                # Sum PnL across all chunks for this cycle
                cycle_total_pnl = sum([c.pnl for c in chunks if c.pnl is not None])
                total_session_pnl += cycle_total_pnl

                # Build unified cycle object
                cycle_obj = entry_template.to_cycle_dict()
                cycle_obj["cyclePnl"] = cycle_total_pnl

                # Rebuild targets list from all chunks except the final exit
                targets = []
                final_exit = None

                for c in chunks:
                    if str(c.status).upper().startswith("TARGET"):
                        # This chunk was a target hit
                        targets.append(
                            {
                                "step": c.achieved_targets
                                or (int(str(c.status).split("_")[1]) if "_" in str(c.status) else 1),
                                "time": c.formatted_exit_time,
                                "price": c.exit_price,
                                "quantity": c.initial_quantity,
                                "actionPnl": c.pnl,
                                "niftyPrice": c.nifty_price_at_exit,
                                "transaction": c.exit_transaction_desc,
                            }
                        )
                    else:
                        # This is the final or main exit (Stop Loss, Signal, BE, etc.)
                        final_exit = c

                cycle_obj["targets"] = targets
                if final_exit:
                    cycle_obj["exit"] = {
                        "time": final_exit.formatted_exit_time,
                        "price": final_exit.exit_price,
                        "quantity": final_exit.initial_quantity,
                        "actionPnl": final_exit.pnl,
                        "reason": final_exit.status,
                        "reasonDescription": final_exit.exit_reason_description,
                        "niftyPrice": final_exit.nifty_price_at_exit,
                    }
                else:
                    # If we only had targets and no final exit yet (rare but possible in live)
                    # We use the last hit target as the temporary 'exit' for the UI
                    pass

                trade_cycles.append(cycle_obj)

            # Aggregate unique instruments for UI sidebar grouping
            instruments_traded = []
            seen_symbols = set()
            for cyc in trade_cycles:
                sym = cyc["symbol"]
                if sym not in seen_symbols:
                    instruments_traded.append(
                        {"symbol": sym, "description": cyc.get("description") or sym}
                    )
                    seen_symbols.add(sym)

            # Use the numeric initialBudget if provided by TradeEventService, 
            # otherwise fallback to parsing the potentially string-based 'budget'
            initial_budget = config.get("initialBudget")
            if initial_budget is None:
                budget_raw = config.get("budget", 0.0)
                if isinstance(budget_raw, str) and "-" in budget_raw:
                    if budget_raw.endswith("-inr"):
                        initial_budget = float(budget_raw.split("-")[0])
                    else:
                        initial_budget = 0.0 # Lots
                else:
                    initial_budget = float(budget_raw)

            doc = {
                "sessionId": session_id,
                "status": "COMPLETED",
                "config": config,
                "summary": {
                    "initialCapital": initial_budget,
                    "finalCapital": initial_budget + total_session_pnl,
                    "totalPnl": total_session_pnl,
                    "roi": (total_session_pnl / initial_budget * 100) if initial_budget > 0 else 0,
                    "tradeCount": len(trade_cycles),
                },
                "tradeCycles": trade_cycles,
                "instrumentsTraded": instruments_traded,
                "dailyPnl": daily_pnl,
                "createdAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
                "updatedAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
            }

            # Compatibility: Use sessionId as the unique identifier for all sessions

            self.db[col].update_one({"sessionId": session_id}, {"$set": doc}, upsert=True)
            logger.info(f"✅ Session Summary saved for {session_id} in {col} ({len(trade_cycles)} cycles)")
        except Exception as e:
            logger.error(f"❌ Failed to save session summary: {e}")
            import traceback

            logger.error(traceback.format_exc())

    def update_session_status(self, session_id: str, status: str, is_live: bool = True):
        """Updates the status of an ongoing session (e.g., ACTIVE -> COMPLETED)."""
        col = self.live_col if is_live else self.backtest_col
        self.db[col].update_one(
            {"sessionId": session_id},
            {
                "$set": {
                    "status": status,
                    "updatedAt": datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0).isoformat(),
                }
            },
        )

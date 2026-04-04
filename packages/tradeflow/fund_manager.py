import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from packages.services.contract_discovery import ContractDiscoveryService
from packages.services.market_history import MarketHistoryService
from packages.services.trade_config_service import TradeConfigService
from packages.tradeflow.candle_resampler import CandleResampler
from packages.tradeflow.indicator_calculator import IndicatorCalculator
from packages.tradeflow.order_manager import PaperTradingOrderManager
from packages.tradeflow.position_manager import PositionManager
from concurrent.futures import ThreadPoolExecutor
from packages.tradeflow.python_strategy_loader import PythonStrategy
from packages.tradeflow.types import InstrumentCategoryType, InstrumentKindType, MarketIntentType, SignalType
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger(__name__)


class FundManager:
    """
    The Orchestrator (Brain) for Multi-Timeframe Analysis (MTFA).
    Coordinates data flow between Market Data, Resamplers, Indicators, and Strategy Logic.
    """

    def __init__(
        self,
        strategy_config: dict[str, Any],
        position_config: dict[str, Any] | None = None,
        reduced_log: bool = False,
        is_backtest: bool = False,
        config_service: TradeConfigService | None = None,
        discovery_service: ContractDiscoveryService | None = None,
        history_service: MarketHistoryService | None = None,
        fetch_ohlc_fn: Callable | None = None,  # Legacy injection
        fetch_quote_fn: Callable | None = None,  # Legacy injection
        active_grid_ids: set[int] | None = None,
    ):
        # 1. Initialize Services
        self.config_service = config_service or TradeConfigService()
        self.discovery_service = discovery_service or ContractDiscoveryService()
        self.history_service = history_service or MarketHistoryService(fetch_ohlc_api_fn=fetch_ohlc_fn)

        # 2. Normalize and Build Configs
        self.config = self.config_service.normalize_strategy_config(strategy_config)
        self.position_config = self.config_service.build_position_config(**(position_config or {}))

        self.indicators_config = self.config.get("indicators", [])
        self.reduced_log = reduced_log
        self.log_heartbeat = not reduced_log
        self.is_backtest = is_backtest

        self.indicator_calculator = IndicatorCalculator(indicators_config=self.indicators_config)
        if self.reduced_log:
            self.indicator_calculator.suppress_logs = True

        # 3. Load Strategy
        python_path = self.position_config.get("pythonStrategyPath") or self.config.get("pythonStrategyPath")
        if not python_path:
            raise ValueError("No 'pythonStrategyPath' found in position_config or strategy_config.")

        self.strategy = PythonStrategy(script_path=python_path)
        logger.info(f"🐍 Strategy: {python_path}")

        # 4. Core Parameters (Budget & Investment)
        self.budget_val, self.budget_type = self._parse_budget(self.position_config["budget"])
        self.initial_budget = self.budget_val if self.budget_type == "inr" else 0.0
        self.fixed_lots = int(self.budget_val) if self.budget_type == "lots" else None
        self.invest_mode = "fixed" if self.fixed_lots else self.position_config["investMode"]
        self.sl_pct = self.position_config.get("slPct", 3.0)
        self.target_pct = self.position_config.get("targetPct", [2, 3, 4])
        self.tsl_pct = self.position_config.get("tslPct", 0.0)
        self.tsl_id = self.position_config.get("tslId", "trade-ema-5")
        self.use_be = self.position_config.get("useBe", True)

        self.trade_instrument_type = self.position_config["instrumentType"]
        self.strike_selection = self.position_config["strikeSelection"]
        self.price_source = self.position_config["priceSource"]
        self.record_papertrade_db = self.position_config.get("record_papertrade_db", False)

        enum_map = {
            "CASH": InstrumentKindType.CASH,
            "OPTIONS": InstrumentKindType.OPTIONS,
            "FUTURES": InstrumentKindType.FUTURES,
        }
        instr_enum = enum_map.get(self.trade_instrument_type, InstrumentKindType.CASH)

        self.position_manager = PositionManager(
            symbol=self.position_config["symbol"],
            quantity=self.position_config.get("quantity", 50),
            sl_pct=self.sl_pct,
            target_pct=self.target_pct,
            instrument_type=instr_enum,
            tsl_pct=self.tsl_pct,
            use_be=self.use_be,
            pyramid_steps=self.position_config["pyramidSteps"],
            pyramid_confirm_pts=self.position_config["pyramidConfirmPts"],
            price_source=self.position_config["priceSource"],
            tsl_id=self.tsl_id,
        )
        self.order_manager = PaperTradingOrderManager()
        self.position_manager.set_order_manager(self.order_manager)

        if self.fixed_lots:
            self.position_manager.quantity = self.fixed_lots
            logger.info(f"📦 Fixed Lots Mode: {self.fixed_lots} lots")
        else:
            logger.info(f"💰 Budget Mode: {self.initial_budget} INR ({self.invest_mode})")

        self.on_signal: Callable[[dict], None] | None = None
        self.latest_tick_prices: dict[int, float] = {}

        self.global_timeframe = self.config["timeframeSeconds"]

        # Track active ATM instruments being monitored {category: instrument_id}
        self.active_instruments: dict[str, int | str] = {}
        self.monitored_instrument_ids = active_grid_ids or set()
        
        # Initialize Resamplers per instrument_id
        self.resamplers: dict[int, CandleResampler] = {}
        self._ensure_resampler(26000, InstrumentCategoryType.SPOT)

        # Global cache
        self.latest_indicators_state: dict[str, float] = {}
        self._cached_mapped_indicators: dict[str, float] = {}
        self._needs_mapping_update = True

        self.is_warming_up = False
        self.latest_market_time: float | None = None

        # Position Events also invalidate the mapping cache (due to direction-based Active/Inverse mapping)
        def invalidate_mapping_cache(event):
            self._needs_mapping_update = True

        self.position_manager.on_trade_event = invalidate_mapping_cache

    def _ensure_resampler(self, instrument_id: int, category: InstrumentCategoryType) -> None:
        """Ensures a resampler exists for the given instrument ID."""
        if instrument_id not in self.resamplers:
            self.resamplers[instrument_id] = CandleResampler(
                instrument_id=instrument_id,
                symbol=category.value,
                timeframe_mins=self.global_timeframe // 60,
                on_candle_closed=self._on_resampled_candle_closed,
                category=category,
            )
            logger.debug(f"🛠️ Created resampler for {category.value} ({instrument_id})")

    def _parse_budget(self, budget: str | float) -> tuple[float, str]:
        """Parses budget string like '200000-inr' or '10-lots'."""
        if isinstance(budget, (int, float)):
            return float(budget), "inr"

        b_str = str(budget).lower().strip()
        if b_str.endswith("-inr"):
            return float(b_str.replace("-inr", "")), "inr"
        elif b_str.endswith("-lots"):
            return float(b_str.replace("-lots", "")), "lots"
        elif b_str.endswith("-lot"):
            return float(b_str.replace("-lot", "")), "lots"
        else:
            raise ValueError(
                f"Invalid budget format: '{budget}'. Must end with -inr, -lots, or -lot"
            )



    def _get_fallback_option_price(
        self, symbol_id: int, current_ts: float | None, is_entry: bool = False
    ) -> float | None:
        """
        Attempts to find a reliable price for an option when the live tick is missing.
        Priority:
        1. Tick Cache
        2. API/DB Fallback (nearest quote/candle before or at current_ts)
        3. Position Manager's current_price (only for exits)
        """
        # 1. Tick Cache
        price = self.latest_tick_prices.get(symbol_id)
        if price:
            return price

        # 2. API/DB Fallback
        logger.info(f"🔍 No live tick for {symbol_id}. Checking fallbacks...")

        # Try fetching from history service (which handles API/DB)
        history = self.history_service.fetch_historical_candles(
            symbol_id, start_ts=0, end_ts=current_ts or 0, limit=1, use_api=not self.is_backtest
        )
        if history:
            price = history[0].get("c", history[0].get("p"))
            if price is not None:
                logger.info(f"✅ Found history service fallback price for {symbol_id}: {price}")
                return price

        # 3. Position Manager Fallback (Exits Only)
        if (
            not is_entry
            and self.position_manager.current_position
            and str(symbol_id) == self.position_manager.current_position.symbol
        ):
            price = self.position_manager.current_position.current_price
            if price is not None and price > 0:
                logger.info(f"⚠️ Using PositionManager last known price for {symbol_id}: {price}")
                return price

        return None

    def on_tick_or_base_candle(self, market_data: dict[str, Any]) -> None:
        """
        Process a real-time TICK or a base 1-minute CANDLE from the stream.
        Routes it to all configured timeframes for resampling and updates
        the PositionManager for real-time stop loss/target monitoring.

        Indicators:
            Before updating the PositionManager, this method fetches 'mapped'
            indicators (active-*, inverse-*, etc.) which are used for
            Indicator-based Trailing SL (e.g. EMA-5 exit).

        Args:
            market_data (Dict): OHLCV data or Tick data containing instrument ID ('i'),
                               price ('p' or 'c'), and timestamp ('t').
        """
        inst_id = market_data.get("i", market_data.get("instrument_id"))

        # Update global market time if available
        ts = market_data.get("t", market_data.get("timestamp"))
        if ts is not None:
            if self.latest_market_time is None or ts > self.latest_market_time:
                self.latest_market_time = ts

        # In Backtest mode, we use the configured price source (Open or Close)
        # In Live/Socket mode (ticks), we use 'p' (LTP)
        is_candle = any(k in market_data for k in ["c", "close", "o", "open"])
        is_spot = (inst_id == 26000) or getattr(self, "spot_instrument_id", 26000) == inst_id

        if self.is_backtest and is_candle:
            if self.price_source == "open":
                price = market_data.get("o", market_data.get("open"))
            else:
                price = market_data.get("c", market_data.get("close"))
        else:
            price = market_data.get("c", market_data.get("close", market_data.get("p")))

        if price is None or price <= 0:
            return

        # 0. Tick Normalization: If this is a raw tick (no OHLC), populate OHLC for downstream compatibility
        if "p" in market_data and any(k not in market_data for k in ["o", "h", "l", "c"]):
            market_data.update({"o": price, "h": price, "l": price, "c": price})

        if inst_id:
            self.latest_tick_prices[int(inst_id)] = price



        # 2. Update Position Manager immediately for Stop Loss / Target Checks
        if self.position_manager.current_position and not self.is_warming_up:
            # Only update position if the tick belongs to the active traded instrument
            if str(inst_id) == self.position_manager.current_position.symbol:
                nifty_price = self.latest_tick_prices.get(26000)

                mapped = self._get_mapped_indicators()
                # In Backtest Mode, if we receive a 1-minute Candle, we explode it into
                # 4 virtual ticks (O, H, L, C) to match Socket/Live granularity.
                if self.is_backtest and is_candle:
                    from packages.utils.replay_utils import ReplayUtils

                    virtual_ticks = ReplayUtils.explode_bar_to_ticks(
                        int(inst_id) if inst_id else 0, market_data, ts, default_price=price
                    )
                    for v_tick in virtual_ticks:
                        if not self.position_manager.current_position:
                            break
                        self.position_manager.update_tick(v_tick, nifty_price=nifty_price, indicators=mapped)
                else:
                    self.position_manager.update_tick(market_data, nifty_price=nifty_price, indicators=mapped)

        # 3. Route to Resamplers based on Category
        category = None
        
        if is_spot:
            category = InstrumentCategoryType.SPOT

        if not category:
            # Check if it's one of the primary monitored instruments (Spot, current ATM CE/PE)
            for cat, active_id in self.active_instruments.items():
                if active_id == int(inst_id):
                    category = cat
                    break

        # If not primary but currently being traded, it's still CE or PE
        if not category and self.position_manager.current_position:
            if str(inst_id) == self.position_manager.current_position.symbol:
                # It's a traded instrument that drifted. We still need to resample it!
                # We can heuristic the category based on intent (LONG=CE, SHORT=PE for options)
                if self.trade_instrument_type == "OPTIONS":
                    category = "CE" if self.position_manager.current_position.intent == MarketIntentType.LONG else "PE"
                else:
                    category = "SPOT"  # Fallback for futures/cash

        if not category:
            if (self.is_backtest and self.monitored_instrument_ids and int(inst_id) in self.monitored_instrument_ids) or (not self.is_backtest):
                # Resolve actual option type from discovery cache instead of guessing
                category = self.discovery_service.get_option_type(int(inst_id))
            else:
                return  # Data for instrument not actively monitored

        # Ensure resampler exists (especially for drifted/traded instruments)
        self._ensure_resampler(int(inst_id), InstrumentCategoryType(category))

        resampler = self.resamplers.get(int(inst_id))
        if resampler:
            resampler.add_candle(market_data)

    def _on_resampled_candle_closed(self, candle: dict[str, Any], category: InstrumentCategoryType, triggering_tick: dict[str, Any] | None = None) -> None:
        """
        Callback triggered when a specific Category Resampler finalizes a candle.
        For Triple-Lock, we evaluate the unified state ONLY when the SPOT candle closes.
        """
        ts = candle.get("t", candle.get("timestamp"))
        if ts is None:
            return

        # Update indicators (Python strategy receives them in on_resampled_candle_closed)
        inst_id = candle.get("instrument_id", candle.get("i"))
        self.indicator_calculator.add_candle(candle, instrument_category=category, instrument_id=inst_id)

        # Invalidate mapping cache as raw indicator values just changed
        self._needs_mapping_update = True



        # Refresh the flat state for logging and heartbeats after sync
        # We pull the fully mapped (active/inverse/trade) indicators so logs match strategy view
        self.latest_indicators_state = self._get_mapped_indicators()

        if self.log_heartbeat and not self.is_warming_up and category == InstrumentCategoryType.SPOT:
            # Format candle start and end times for clarity
            if ts:
                start_str = DateUtils.market_timestamp_to_datetime(ts).strftime("%H:%M:%S")
                end_str = DateUtils.market_timestamp_to_datetime(ts + self.global_timeframe).strftime("%H:%M:%S")
                time_display = f"{start_str} - {end_str}"
            else:
                time_display = "N/A"

            # Determine descriptions for the heartbeat log
            pos = self.position_manager.current_position
            is_long = pos.intent == MarketIntentType.LONG if pos else True
            active_cat = "CE" if is_long else "PE"
            inverse_cat = "PE" if is_long else "CE"

            logger.info(
                TradeFormatter.format_heartbeat(
                    time_display=time_display,
                    indicators=self.latest_indicators_state,
                    trade_desc=pos.display_symbol if pos else "None",
                    active_desc=self.active_instruments.get(f"{active_cat}_DESC", "N/A"),
                    inverse_desc=self.active_instruments.get(f"{inverse_cat}_DESC", "N/A"),
                )
            )

        # ONLY execute strategy decision synchronously when the SPOT candle acts as the anchor
        # ONLY execution and synchronization happens when the SPOT candle acts as the anchor
        if category != InstrumentCategoryType.SPOT:
            # 0. Risk Checks (SL/Target) - Still need to check if the TRADED instrument just closed
            if (
                self.position_manager.current_position 
                and not self.is_warming_up 
                and str(inst_id) == self.position_manager.current_position.symbol
            ):
                nifty_price = self.latest_tick_prices.get(26000)
                mapped = self._get_mapped_indicators()
                
                # Use triggering tick timestamp for exact timing
                ts_to_use = triggering_tick.get("t", ts) if triggering_tick else ts
                candle_for_tick = candle.copy()
                candle_for_tick["t"] = ts_to_use
                candle_for_tick["timestamp"] = ts_to_use
                
                self.position_manager.update_tick(candle_for_tick, nifty_price=nifty_price, indicators=mapped)
            return

        # 1. Synchronize other resamplers (CE/PE/Traded) to current SPOT timestamp
        # This ensures that if Option ticks arrived slightly late, they are still
        # processed into the current or previous candle before we run indicators.
        for r_id, r in self.resamplers.items():
            if r_id != 26000:  # Not Spot
                # If resampler is at or behind current SPOT timestamp, flush it
                if r.last_period_start is not None and r.last_period_start <= ts:
                    r.add_candle({"t": ts + self.global_timeframe, "is_flush": True})

        # 2. Dynamic Strike Resolution: Update active CE/PE based on selection (ATM, ITM-x, OTM-x)
        # This happens ONLY when the SPOT candle acts as the anchor
        if self.trade_instrument_type == "OPTIONS" and ts:
            spot_price = candle.get("c", candle.get("close", 26000))
            
            # Fetch CE based on selection
            _, ce_id, ce_desc = self.discovery_service.get_target_strike(spot_price, self.strike_selection, True, ts)
            if ce_id:
                self.active_instruments["CE"] = int(ce_id)
                self.active_instruments["CE_DESC"] = ce_desc
            
            # Fetch PE based on selection
            _, pe_id, pe_desc = self.discovery_service.get_target_strike(spot_price, self.strike_selection, False, ts)
            if pe_id:
                self.active_instruments["PE"] = int(pe_id)
                self.active_instruments["PE_DESC"] = pe_desc

        # Refresh indicators for strategy evaluation
        self.latest_indicators_state = self._get_mapped_indicators()



        # Determine current intent for strategy evaluation
        intent_enum = None
        if self.position_manager.current_position:
            intent_enum = self.position_manager.current_position.intent

        # Execute Strategy (Python script)
        mapped_indicators = self.latest_indicators_state.copy()
        mapped_indicators["meta-is-warming-up"] = self.is_warming_up

        signal, reason, confidence = self.strategy.on_resampled_candle_closed(
            candle, mapped_indicators, current_position_intent=intent_enum
        )

        is_cont = "(Continuity)" in reason

        if signal != SignalType.NEUTRAL:
            if self.is_warming_up:
                # No signals/trades during warmup!
                return

            # 0. Stale SignalType Protection (Max 30 minutes)
            if ts and self.latest_market_time and (self.latest_market_time - ts) > 1800:
                logger.warning(f"⚠️ SignalType ignored: Triggered by stale data from {ts}")
                return

            # Use period end for signal/entry time (signal is finalized at end of candle)
            signal_ts = ts + self.global_timeframe
            spot_price = candle.get("c", candle.get("close"))

            # 1. Handle SignalTypes for existing positions
            if self.position_manager.current_position:
                if signal == SignalType.EXIT:
                    # Fallback to market time if signal_ts is missing
                    ts_dt = self._resolve_signal_time(signal_ts)
                    ts_str = ts_dt.strftime("%d-%b %H:%M")
                    logger.info(
                        TradeFormatter.format_signal(
                            "EXIT",
                            reason,
                            ts_str,
                            self.global_timeframe,
                            self.latest_indicators_state,
                            is_continuity=is_cont,
                        )
                    )

                    pos = self.position_manager.current_position
                    opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                    if not opt_price:
                        logger.error(
                            f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort."
                        )
                        opt_price = pos.entry_price if pos.entry_price else spot_price  # Extremely rare
                    self.position_manager._close_position(
                        opt_price, ts_dt, "STRATEGY_EXIT", reason_desc=reason, nifty_price=spot_price
                    )
                    return

                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT

                # If current intent matches signal, do nothing (already in position)
                if self.position_manager.current_position.intent == intent:
                    return

                # SignalType changed (flip) - log it and handle closure
                ts_dt = self._resolve_signal_time(signal_ts)
                ts_str = ts_dt.strftime("%d-%b %H:%M")
                logger.info(
                    TradeFormatter.format_signal(
                        signal.name,
                        reason,
                        ts_str,
                        self.global_timeframe,
                        self.latest_indicators_state,
                        is_continuity=is_cont,
                    )
                )

                pos = self.position_manager.current_position
                opt_price = self._get_fallback_option_price(int(pos.symbol), signal_ts)
                if not opt_price:
                    logger.error(f"Cannot exit {pos.symbol}, ALL fallbacks failed. Using entry price as last resort.")
                    opt_price = pos.entry_price if pos.entry_price else spot_price

                self.position_manager._close_position(
                    opt_price, ts_dt, "SIGNAL_FLIP", reason_desc=reason, nifty_price=spot_price
                )
            else:
                if signal == SignalType.EXIT:
                    return  # Ignore lone exit signals when not in position

                intent = MarketIntentType.LONG if signal == SignalType.LONG else MarketIntentType.SHORT

                # No existing position - log new entry signal
                ts_dt = self._resolve_signal_time(signal_ts)
                ts_str = ts_dt.strftime("%d-%b %H:%M")
                logger.info(
                    TradeFormatter.format_signal(
                        signal.name,
                        reason,
                        ts_str,
                        self.global_timeframe,
                        self.latest_indicators_state,
                        is_continuity=is_cont,
                    )
                )

            # 2. Handle Entries
            target_symbol = "26000"  # default spot
            target_display_symbol = "NIFTY SPOT"
            entry_price = spot_price

            if self.trade_instrument_type == "OPTIONS":
                t_cat = "CE" if intent == MarketIntentType.LONG else "PE"
                resolved_id = self.active_instruments.get(t_cat)
                resolved_desc = self.active_instruments.get(f"{t_cat}_DESC")

                # We also need the contract description if possible for the Payload.
                # In Triple-Lock, the contract is already resolved and tracked during drift!
                if not resolved_id:
                    logger.error(f"Failed to find active {t_cat} instrument from drift tracker")
                    return

                target_symbol = str(resolved_id)
                target_display_symbol = resolved_desc or f"NIFTY {t_cat} ({target_symbol})"  # Use resolved description

                from packages.settings import settings
                if settings.LOG_ACTIVE_INDICATOR:
                    dump_dt = self._resolve_signal_time(signal_ts)
                    clean_sym = target_display_symbol.replace(' ', '')
                    dump_fname = f"logs/diagnostics/{dump_dt.strftime('%b-%d-%H-%M-%S').upper()}-{clean_sym}.csv"
                    dump_cat = InstrumentCategoryType.CE if intent == MarketIntentType.LONG else InstrumentCategoryType.PE
                    self.indicator_calculator.dump_to_csv(int(target_symbol), dump_cat, dump_fname)

                # Entry Price Cache check
                entry_price = self._get_fallback_option_price(int(resolved_id), signal_ts, is_entry=True)
                if not entry_price:
                    logger.warning(f"No active tick feed OR DB fallback for option {target_symbol}. Skipping entry.")
                    return
            elif self.trade_instrument_type == "FUTURES":
                target_display_symbol = "NIFTY FUT"  # Example, could be more dynamic

            # Use on_signal for centralized entry/exit logic
            payload = {
                "signal": intent,
                "confidence": confidence,
                "price": entry_price,
                "symbol": target_symbol,
                "display_symbol": target_display_symbol,
                "timestamp": signal_ts,
                "reason": reason,
                "reason_desc": signal.name,
                "nifty_price": spot_price,
                "is_continuity": is_cont,
                "timeframe": self.global_timeframe,
            }

            # Recalculate quantity based on exact entry price and budget
            if self.fixed_lots:
                self.position_manager.quantity = self.fixed_lots
            else:
                from packages.settings import settings
                lot_size = settings.NIFTY_LOT_SIZE

                # Decide which capital to use (Total Capital vs Initial Budget)
                total_realized_pnl = sum([t.pnl for t in self.position_manager.trades_history])
                current_capital = self.initial_budget + total_realized_pnl

                # If compounding, we use current_capital. If fixed, we use initial_budget.
                capital_to_use = current_capital if self.invest_mode == "compound" else self.initial_budget

                # Calculate exactly how many lots we can afford
                if entry_price > 0:
                    new_qty = int(capital_to_use // (entry_price * lot_size))
                    if new_qty > 0:
                        self.position_manager.quantity = new_qty
                        if self.invest_mode == "compound":
                            logger.debug(
                                f"📈 [COMPOUND] Recalculated Qty: {new_qty} based on Capital: ₹{current_capital:,.2f} and Price: {entry_price}"
                            )
                        else:
                            logger.debug(
                                f"💰 [FIXED] Calculated Qty: {new_qty} based on Budget: ₹{self.initial_budget:,.2f} and Price: {entry_price}"
                            )
                    else:
                        logger.warning(
                            f"⚠️ Insufficient budget (₹{capital_to_use:,.2f}) for entry at {entry_price}. Qty remains {self.position_manager.quantity}"
                        )

            self.position_manager.on_signal(payload)

            if self.on_signal:
                payload.update({
                    "indicators": self.latest_indicators_state.copy(),
                    "is_buy": signal == SignalType.LONG,
                    "timeframe": self.global_timeframe
                })
                self.on_signal(payload)

    def handle_eod_settlement(self, timestamp: float) -> None:
        """
        Forces closure of any open positions at the end of the trading day.

        Args:
            timestamp (float): The UNIX timestamp for the settlement (typically 15:30).
        """
        if not self.position_manager.current_position:
            return

        pos = self.position_manager.current_position
        # Use price from fund_manager's tick cache for the specific instrument
        eod_price = self.latest_tick_prices.get(int(pos.symbol))

        # If for some reason tick price isn't in cache, use the last known price
        if not eod_price:
            eod_price = pos.current_price

        # Guard against settling at zero — use entry price as absolute last resort
        if not eod_price or eod_price <= 0:
            logger.error(f"⚠️ EOD price is {eod_price} for {pos.symbol}. Using entry price {pos.entry_price} as fallback.")
            eod_price = pos.entry_price

        eod_time = DateUtils.market_timestamp_to_datetime(timestamp)
        nifty_price = self.latest_tick_prices.get(26000)

        logger.info(TradeFormatter.format_eod(pos.symbol, eod_price))
        desc = f"End of Day Settlement at {eod_price:.2f}"
        self.position_manager._close_position(eod_price, eod_time, "EOD", reason_desc=desc, nifty_price=nifty_price)

    def _get_mapped_indicators(self) -> dict[str, float]:
        """
        Builds a unified indicator dictionary for the strategy.
        Caches the result to avoid redundant mapping on every tick.
        New Scheme:
        - active-*: Always current ATM
        - inverse-*: Always current opposing ATM
        - trade-*: Pinned to the specifically traded instrument (if in position)
        """
        if not self._needs_mapping_update:
            return self._cached_mapped_indicators

        mapped = {}

        # 1. Pull Spot Indicators (Always present)
        mapped.update(self.indicator_calculator.extract_indicators(26000, InstrumentCategoryType.SPOT))

        # 2. Pull Current Monitored ATM Contract Indicators
        ce_id = self.active_instruments.get("CE")
        pe_id = self.active_instruments.get("PE")

        ce_inds = self.indicator_calculator.extract_indicators(ce_id, InstrumentCategoryType.CE) if ce_id else {}
        pe_inds = self.indicator_calculator.extract_indicators(pe_id, InstrumentCategoryType.PE) if pe_id else {}

        mapped.update(ce_inds)
        mapped.update(pe_inds)

        # 3. Handle Mappings
        pos = self.position_manager.current_position
        is_long = pos.intent == MarketIntentType.LONG if pos else True
        
        # 3a. ATM Mappings (active/inverse) - ALWAYS follows current ATM
        self._apply_prefix_mapping(mapped, ce_inds if is_long else pe_inds, "active-", is_long)
        self._apply_prefix_mapping(mapped, pe_inds if is_long else ce_inds, "inverse-", not is_long)

        # 3b. Trade Mapping (trade-) - PINNED to pos instrument
        if pos:
            traded_id = int(pos.symbol)
            t_cat = InstrumentCategoryType.CE if is_long else InstrumentCategoryType.PE
            traded_inds = self.indicator_calculator.extract_indicators(traded_id, t_cat)
            self._apply_prefix_mapping(mapped, traded_inds, "trade-", is_long)
        else:
             # Fallback: if no position, trade-* = active-*
             self._apply_prefix_mapping(mapped, ce_inds if is_long else pe_inds, "trade-", is_long)

        self._cached_mapped_indicators = mapped
        self._needs_mapping_update = False
        return mapped

    def _apply_prefix_mapping(
        self, target: dict[str, Any], source: dict[str, Any], new_prefix: str, is_ce: bool
    ) -> None:
        """Helper to apply a specific prefix to indicators from a source dict."""
        orig_prefix = "ce-" if is_ce else "pe-"

        for k, v in source.items():
            if k.startswith(orig_prefix):
                target[k.replace(orig_prefix, new_prefix, 1)] = v

    def _resolve_signal_time(self, signal_ts: float | None) -> datetime:
        """Centralized helper to resolve a signal timestamp to a market-aware datetime."""
        if isinstance(signal_ts, (int, float)):
            return DateUtils.market_timestamp_to_datetime(signal_ts)
        if self.latest_market_time:
            return DateUtils.market_timestamp_to_datetime(self.latest_market_time)
        return datetime.now(DateUtils.MARKET_TZ)

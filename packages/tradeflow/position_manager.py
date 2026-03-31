from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from packages.settings import settings
from packages.tradeflow.types import InstrumentKindType, MarketIntentType, SignalPayload
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.utils.trade_formatter import TradeFormatter

logger = setup_logger(__name__)

# MarketIntent Enum moved to tradeflow.types as MarketIntentType

# InstrumentType Enum moved to tradeflow.types as InstrumentKindType


class OrderStatus(Enum):
    PENDING = auto()
    FILLED = auto()
    REJECTED = auto()
    CANCELLED = auto()


@dataclass
class Position:
    symbol: str
    display_symbol: str
    intent: MarketIntentType
    entry_price: float
    initial_quantity: int
    entry_time: datetime
    stop_loss: float
    targets: list[float]
    entry_timestamp: float = 0.0
    current_price: float = 0.0
    status: str = "OPEN"
    pnl: float = 0.0
    total_realized_pnl: float = 0.0  # Tracking cumulative PnL for multi-target trades

    # Nifty Underlying Tracking
    nifty_price_at_entry: float = 0.0
    nifty_price_at_exit: float = 0.0
    nifty_price_at_break_even: float = 0.0

    # Advanced Execution Tracking
    remaining_quantity: int = field(init=False)
    achieved_targets: int = 0
    highest_price: float = field(init=False)
    lowest_price: float = field(init=False)
    exit_price: float | None = None
    exit_time: datetime | None = None
    trade_cycle: str = "N/A"
    event_count: int = 0
    entry_signal: str = "N/A"
    entry_reason_description: str = ""
    exit_reason_description: str = ""

    # Enriched Fields for UI/Reporting
    formatted_entry_time: str = ""
    formatted_exit_time: str = ""
    entry_transaction_desc: str = ""
    exit_transaction_desc: str = ""

    # Pyramiding
    pyramid_step: int = 0  # Current pyramid step index (0 = first entry)
    total_intended_quantity: int = 0  # Full quantity before splitting into pyramid steps

    # Event History for Unified Schema
    target_events: list[dict] = field(default_factory=list)
    is_continuity: bool = False

    def __post_init__(self):
        self.remaining_quantity = self.initial_quantity
        self.highest_price = self.entry_price
        self.lowest_price = self.entry_price

    def to_cycle_dict(self) -> dict[str, Any]:
        """
        Converts the stateful Position object into the unified 'Trade Cycle' dictionary format
        standardized for MongoDB persistence.
        """
        # Identify Option Type
        str(self.symbol)
        if hasattr(self.intent, "name"):
            # This is a bit of a heuristic if we don't have the full instrument metadata here
            # But in Position context, CE usually means MarketIntentType.LONG (buying CE)
            # and PE usually means MarketIntentType.SHORT (buying PE).
            # However, the instrument_master is better.
            pass

        cycle_obj = {
            "cycleId": self.trade_cycle,
            "symbol": self.symbol,
            "description": self.display_symbol,
            "cyclePnl": self.total_realized_pnl,
            "entry": {
                "time": self.formatted_entry_time,
                "price": self.entry_price,
                "quantity": self.initial_quantity,
                "signal": self.entry_signal,
                "niftyPrice": self.nifty_price_at_entry,
                "isContinuity": self.is_continuity,
            },
            "targets": self.target_events,
            "stopLossPrice": self.stop_loss,
            "exit": None,
        }

        if self.exit_time:
            cycle_obj["exit"] = {
                "time": self.formatted_exit_time,
                "price": self.exit_price,
                "quantity": self.initial_quantity - sum([t["quantity"] for t in self.target_events]),
                "actionPnl": self.pnl,  # Last chunk PnL
                "reason": self.status,
                "reasonDescription": self.exit_reason_description,
                "niftyPrice": self.nifty_price_at_exit,
            }

        return cycle_obj


class PositionManager:
    """
    Manages the lifecycle of a trade:
    - Entry based on Signals
    - Stop Loss / Target Monitoring
    - Exit Execution
    - PnL Calculation
    """

    def __init__(
        self,
        symbol: str,
        quantity: int,
        sl_pct: float = 2.0,
        target_pct: list[float] | str | None = None,
        instrument_type: InstrumentKindType = InstrumentKindType.OPTIONS,
        tsl_pct: float = 0.0,
        use_be: bool = True,
        display_symbol: str | None = None,
        pyramid_steps: list[int] | None = None,
        pyramid_confirm_pts: float = 10.0,
        price_source: str = "close",
        tsl_id: str | None = None,
    ):
        self.symbol = symbol
        self.display_symbol = display_symbol or symbol
        self.quantity = quantity
        self.sl_pct = sl_pct
        self.tsl_pct = tsl_pct
        self.tsl_id = tsl_id
        self.use_be = use_be
        self.instrument_type = instrument_type

        # Parse Target Percentages
        if isinstance(target_pct, str):
            self.target_pct_steps = [float(x.strip()) for x in target_pct.split(",")]
        elif isinstance(target_pct, (list, tuple)):
            self.target_pct_steps = [float(x) for x in target_pct]
        elif target_pct is not None:
            self.target_pct_steps = [float(target_pct)]
        else:
            self.target_pct_steps = []

        self.current_position: Position | None = None
        self._last_pos_for_summary: Any = None
        self.trades_history: list[Position] = []

        # Callbacks
        self.on_trade_event: Callable[[dict[str, Any]], None] | None = None

        # Cycle Tracking
        self.cycle_count: int = 0
        self.entry_count: int = 0
        self.last_trade_date: Any = None

        # Interface to OrderManager (to be injected)
        self.order_manager = None

        # Pyramiding Config
        self.pyramid_steps = pyramid_steps or [100]  # Default: 100% all-in
        self.pyramid_confirm_pts = pyramid_confirm_pts
        self.price_source = price_source.lower()
        self.session_realized_pnl = 0.0

    # --- Directional Logic Helpers ---

    def _is_long_dir(self, intent: MarketIntentType) -> bool:
        """
        Determines if the trade direction is 'Long' (profit on price increase).
        1. All Option trades (CE/PE) are 'Long' the contract itself.
        2. Equity/Futures can be LONG or SHORT.
        """
        return (self.instrument_type == InstrumentKindType.OPTIONS) or (intent == MarketIntentType.LONG)

    def _is_better(self, p1: float, p2: float, is_long: bool) -> bool:
        """Returns True if p1 is more favorable than p2."""
        return p1 > p2 if is_long else p1 < p2

    def _is_worse(self, p1: float, p2: float, is_long: bool) -> bool:
        """Returns True if p1 is less favorable than p2."""
        return p1 < p2 if is_long else p1 > p2

    def _is_equal(self, p1: float, p2: float) -> bool:
        """Returns True if p1 is roughly equal to p2 (within precision)."""
        return abs(p1 - p2) < 0.0001

    def _get_sl_price(self, entry: float, pct: float, is_long: bool) -> float:
        """Calculates Stop Loss price from entry and percentage offset."""
        offset = float(entry) * (float(pct) / 100.0)
        return round(float(entry) - offset, 2) if is_long else round(float(entry) + offset, 2)

    def _get_target_prices(self, entry: float, target_pcts: list[float], is_long: bool) -> list[float]:
        """Calculates a list of Target prices from entry and percentage steps."""
        if is_long:
            return [round(float(entry) * (1 + float(t) / 100.0), 2) for t in target_pcts]
        return [round(float(entry) * (1 - float(t) / 100.0), 2) for t in target_pcts]

    def set_order_manager(self, order_manager: Any) -> None:
        self.order_manager = order_manager

    def on_signal(self, payload: SignalPayload | dict[str, Any]) -> None:
        """
        Processes a New Signal.
        """
        # If payload is a dict, parse it via Pydantic model (backward compatibility)
        if isinstance(payload, dict):
            payload = SignalPayload(**payload)

        intent = payload.signal
        price = payload.price
        timestamp = payload.timestamp

        if (isinstance(timestamp, (int, float))):
            timestamp = DateUtils.market_timestamp_to_datetime(timestamp)
        symbol = str(payload.symbol) if payload.symbol else self.symbol
        display_symbol = payload.display_symbol or symbol
        
        # 4. Entry Start Time Guard
        if timestamp.time() < datetime.strptime(settings.TRADE_START_TIME, "%H:%M:%S").time():
            return

        if self.current_position:
            if self.current_position.intent != intent:
                # Signal flip → close current position
                nifty_price = payload.nifty_price
                self._close_position(price, timestamp, "SIGNAL_EXIT", nifty_price=nifty_price)
            else:
                # Same-direction signal → attempt pyramid add
                self._try_pyramid_add(price, timestamp, payload)
                return
        else:
            # Check for Entry Signal
            # 1. Handle Daily Cycle Reset
            trade_date = timestamp.date()
            if self.last_trade_date != trade_date:
                self.cycle_count = 1
                self.last_trade_date = trade_date
            else:
                self.cycle_count += 1

            # 2. Extract specific trigger name if provided
            entry_reason = payload.reason
            nifty_price = payload.nifty_price
            
            # Ensure entry_timestamp is always a float epoch
            raw_ts = payload.timestamp
            if isinstance(raw_ts, datetime):
                raw_ts = raw_ts.timestamp()

            date_prefix = trade_date.strftime("%Y%m%d")
            self._open_position(
                intent,
                price,
                timestamp,
                symbol,
                display_symbol,
                cycle_id=f"cycle-{self.cycle_count}",
                reason=entry_reason,
                reason_desc=payload.reason_desc,
                nifty_price=nifty_price,
                is_continuity=payload.is_continuity,
                entry_timestamp=raw_ts,
            )

    def _try_pyramid_add(self, price: float, timestamp: datetime, payload: SignalPayload) -> None:
        """
        Attempts to add to an existing position via pyramiding.
        Only adds if:
          1. There are more pyramid steps remaining.
          2. Price has moved >= pyramid_confirm_pts in our favor.
        """
        pos = self.current_position
        if not pos:
            return

        # Check if more steps are available
        next_step = pos.pyramid_step + 1
        if next_step >= len(self.pyramid_steps):
            return  # All pyramid steps exhausted

        # Check price confirmation
        # Check price confirmation (has it moved enough in our favor?)
        is_long = self._is_long_dir(pos.intent)
        price_moved = (price - pos.entry_price) if is_long else (pos.entry_price - price)

        if price_moved < self.pyramid_confirm_pts:
            return  # Price hasn't moved enough

        # Calculate quantity for this step
        step_pct = self.pyramid_steps[next_step]
        add_qty = max(1, (pos.total_intended_quantity * step_pct) // 100)

        # Update position with weighted average entry
        old_total = pos.entry_price * pos.remaining_quantity
        new_total = price * add_qty
        pos.entry_price = (old_total + new_total) / (pos.remaining_quantity + add_qty)
        pos.remaining_quantity += add_qty
        pos.initial_quantity += add_qty
        pos.pyramid_step = next_step
        self.entry_count += 1

        # Recalculate SL and Targets based on new weighted average entry
        pos.stop_loss = self._get_sl_price(pos.entry_price, self.sl_pct, is_long)
        pos.targets = self._get_target_prices(pos.entry_price, self.target_pct_steps, is_long)
        
        # NOTE: We DO NOT reset achieved_targets. 
        # If we already hit Target-1, we continue from Target-2 (new level).

        log_msg = TradeFormatter.format_pyramid(
            timestamp=timestamp,
            step=next_step + 1,
            total_steps=len(self.pyramid_steps),
            quantity=add_qty,
            price=price,
            avg_price=pos.entry_price,
            total_qty=pos.remaining_quantity,
        )
        logger.info(log_msg)

        if self.order_manager:
            self.order_manager.place_order(pos.symbol, "BUY", add_qty, timestamp=timestamp)

    def update_tick(
        self, tick: dict[str, Any], nifty_price: float | None = None, indicators: dict[str, Any] | None = None
    ) -> None:
        """
        Updates current position status based on latest price (tick/candle).
        Checks Stop Loss, Targets, and Trailing features.

        Args:
            tick: The latest price data (LTP or finalized candle).
            nifty_price: Current price of Nifty Spot for tracking/logging.
            indicators: Dictionary containing technical and meta-indicators.
                        Used for Indicator-based Trailing SL (e.g. EMA-5).
                        Example: {
                            'active-ema-5': 120.5,
                            'nifty-ema-21': 24120.0,
                            'meta-is-warming-up': False
                        }
                        The value at key `self.tsl_id` is used as the trailing stop level.
        """
        if not self.current_position:
            return

        # Determine price based on source (Open vs Close) for backtests
        if self.price_source == "open":
            current_price = tick.get("o", tick.get("open"))
        else:
            current_price = tick.get("c", tick.get("close"))

        # Fallback to LTP for live/ticks
        if current_price is None:
            current_price = tick.get("ltp", tick.get("p"))

        if not current_price:
            return

        # Parse realistic exit time from tick if available
        ts = tick.get("t", tick.get("timestamp"))

        pos = self.current_position
        if not pos:
            return

        # Determine trade direction once
        is_long = self._is_long_dir(pos.intent)

        # Allow checking on the same timestamp as entry for backtest fidelity.

        if (isinstance(ts, (int, float))):
            exit_time = DateUtils.market_timestamp_to_datetime(ts)
        else:
            exit_time = datetime.now(DateUtils.MARKET_TZ).replace(microsecond=0)

        pos.current_price = current_price
        pos.current_price = current_price

        # Determine if we are in a 'Long' direction trade (expecting price to go up)
        is_long = self._is_long_dir(pos.intent)

        # Extract OHLC for "Wide Check" (Backtest fidelity)
        # If high/low are missing, they fall back to current_price (LTP)
        high = tick.get("h", tick.get("high", current_price))
        low = tick.get("l", tick.get("low", current_price))

        # PnL Calculation (based on latest Close/LTP)
        lot_size = settings.NIFTY_LOT_SIZE
        price_diff = (current_price - pos.entry_price) if is_long else (pos.entry_price - current_price)
        pos.pnl = price_diff * pos.remaining_quantity * lot_size

        # 2. Check for Stop Loss or Trailing Stop Loss hits
        # For Long: use 'low' (price drop). For Short: use 'high' (price rise)
        sl_test_price = low if is_long else high
        
        # Check if price hit or exceeded Stop Loss
        if self._is_worse(sl_test_price, pos.stop_loss, is_long) or self._is_equal(float(sl_test_price), float(pos.stop_loss)):
            # Categorize the exit reason based on current SL vs Entry
            if self._is_equal(float(pos.stop_loss), float(pos.entry_price)):
                reason = "BREAK_EVEN"
            elif self._is_better(pos.stop_loss, pos.entry_price, is_long):
                reason = "TSL_PCT"
            else:
                reason = "STOP_LOSS"
            
            self._close_position(pos.stop_loss, exit_time, reason, reason_desc=f"{sl_test_price:.2f}", nifty_price=nifty_price)
            return

        # 3. Targets execution (using High for LONG, Low for SHORT)
        target_reference_price = high if is_long else low

        while pos.achieved_targets < len(pos.targets):
            next_target = pos.targets[pos.achieved_targets]
            hit = (target_reference_price >= next_target) if is_long else (target_reference_price <= next_target)

            if hit:
                pos.achieved_targets += 1

                # Move SL to Break-Even if first target hit
                if pos.achieved_targets == 1 and self.use_be:
                    if self._is_better(pos.entry_price, pos.stop_loss, is_long):
                        pos.stop_loss = pos.entry_price
                        pos.nifty_price_at_break_even = nifty_price or 0.0
                        logger.info(TradeFormatter.format_breakeven(exit_time, pos.stop_loss))

                        if self.on_trade_event:
                            pos.event_count += 1
                            self.on_trade_event(
                                {
                                    "tradetime": DateUtils.to_iso(exit_time),
                                    "instrument": self.display_symbol,
                                    "cycleId": pos.trade_cycle,
                                    "cycleSeq": pos.event_count,
                                    "type": "breakeven",
                                    "transaction": f"Break-Even Triggered! SL moved to {pos.stop_loss}",
                                    "actionPnL": 0.0,
                                    "cyclePnL": pos.total_realized_pnl,
                                    "totalPnL": self.session_realized_pnl,
                                }
                            )

                # CUSTOM LOT CALCULATION RULES:
                # 1. If target step resolves to < 1 lot, sell 1 lot (minimum).
                # 2. If target step resolves to decimal, floor it (e.g. 2.3 -> 2).
                # 3. Never exceed remaining_quantity.
                calculated_qty = self.quantity / (len(pos.targets) + 1)
                if calculated_qty < 1.0:
                    close_qty = 1
                else:
                    close_qty = int(calculated_qty)  # Flooring
                
                close_qty = min(close_qty, pos.remaining_quantity)

                # Check if this target hit exhausts the position
                is_exhaustion = (close_qty == pos.remaining_quantity)
                reason = f"TARGET_{pos.achieved_targets}"
                if is_exhaustion:
                    reason = "EXIT"
                    desc = f"Exhausted via Target {pos.achieved_targets} (@{next_target})"
                else:
                    desc = f"{target_reference_price:.2f}"

                self._close_position(
                    target_reference_price,
                    exit_time,
                    reason,
                    reason_desc=desc,
                    quantity=close_qty,
                    nifty_price=nifty_price,
                )


                if self.current_position:
                    price_diff = (current_price - pos.entry_price) if is_long else (pos.entry_price - current_price)
                    pos.pnl = price_diff * pos.remaining_quantity * lot_size

                if not self.current_position:
                    break
            else:
                break

        if not self.current_position:
            return

        # 4. Update Extremes and Trailing SL (TSL active ONLY after Target-1)
        if is_long:
            pos.highest_price = max(pos.highest_price, high)
        else:
            pos.lowest_price = min(pos.lowest_price, low)

        # Move TSL-percentage if at least one target hit
        if self.tsl_pct > 0 and pos.achieved_targets >= 1:
            fav_price = pos.highest_price if is_long else pos.lowest_price
            new_sl = self._get_sl_price(fav_price, self.tsl_pct, is_long)
            
            # Only trail in favor of the trade
            if self._is_better(new_sl, pos.stop_loss, is_long):
                pos.stop_loss = new_sl

        # 5. Indicator-based Trailing SL (e.g., EMA-5) - ONLY after Target-1
        if self.tsl_id and indicators and pos.achieved_targets >= 1:
            ind_val = indicators.get(self.tsl_id)
            if ind_val is not None and pos.pnl > 0:
                if self._is_worse(sl_test_price, ind_val, is_long):
                    desc = f"{self.tsl_id}: {ind_val:.2f}"
                    self._close_position(
                        sl_test_price, exit_time, "TSL_ID", reason_desc=desc, nifty_price=nifty_price
                    )
                    return

    def _open_position(
        self,
        intent: MarketIntentType,
        price: float,
        timestamp: datetime,
        symbol: str | None = None,
        display_symbol: str | None = None,
        cycle_id: str = "N/A",
        reason: str = "N/A",
        reason_desc: str = "",
        nifty_price: float = 0.0,
        is_continuity: bool = False,
        entry_timestamp: float = 0.0,
    ) -> None:
        """
        Logic for entering a trade.
        """
        if symbol:
            self.symbol = symbol
        if display_symbol:
            self.display_symbol = display_symbol

        # Disable Shorting for Futures/Cash
        if (
            self.instrument_type in [InstrumentKindType.CASH, InstrumentKindType.FUTURES]
            and intent == MarketIntentType.SHORT
        ):
            # logger.info(f"skipping SHORT signal for {self.instrument_type.name}") # Avoid noise
            return

        # Determine trade direction logic once
        is_long = self._is_long_dir(intent)

        # Set SL and Targets based on Direction (Percentage-based)
        sl = self._get_sl_price(price, self.sl_pct, is_long)
        targets = self._get_target_prices(price, self.target_pct_steps, is_long)

        # Calculate initial pyramid quantity
        step_pct = self.pyramid_steps[0]  # First step percentage
        pyramid_qty = max(1, (self.quantity * step_pct) // 100)

        lot_size = settings.NIFTY_LOT_SIZE
        fmt_time = DateUtils.to_iso(timestamp)
        total_price = pyramid_qty * lot_size * price
        trans_desc = f"Purchased {pyramid_qty} lots({lot_size}) @ {price} | Total: ₹{total_price:,.2f}"
        if self.display_symbol:
            trans_desc = f"[{self.display_symbol}] " + trans_desc

        self.current_position = Position(
            symbol=self.symbol,
            display_symbol=self.display_symbol,
            intent=intent,
            entry_price=round(float(price or 0.0), 2),
            initial_quantity=pyramid_qty,
            entry_time=timestamp,
            stop_loss=round(float(sl), 2),
            targets=[round(float(p), 2) for p in targets],
            current_price=price,
            trade_cycle=cycle_id,
            entry_signal=reason,
            entry_reason_description=reason_desc,
            nifty_price_at_entry=nifty_price,
            pyramid_step=0,
            total_intended_quantity=self.quantity,
            entry_timestamp=entry_timestamp,
            formatted_entry_time=fmt_time,
            entry_transaction_desc=trans_desc,
            is_continuity=is_continuity,
        )
        self.entry_count += 1

        # Trigger entry event
        if self.on_trade_event:
            self.current_position.event_count += 1
            self.on_trade_event(
                {
                    "tradetime": DateUtils.to_iso(timestamp),
                    "instrument": self.display_symbol,
                    "cycleId": self.current_position.trade_cycle,
                    "cycleSeq": self.current_position.event_count,
                    "type": "entry",
                    "transaction": trans_desc,
                    "actionPnL": 0.0,
                    "cyclePnL": 0.0,
                    "totalPnL": self.session_realized_pnl,
                }
            )

        # Place Order:
        # For OPTIONS: Always BUY
        # For CASH/FUTURES: BUY (Shorts are disabled)
        side = "BUY"
        if self.instrument_type != InstrumentKindType.OPTIONS and intent == MarketIntentType.SHORT:
            side = "SELL"  # This part is technically unreachable now due to the lock above

        if len(self.pyramid_steps) > 1:
            f" (Pyramid 1/{len(self.pyramid_steps)})"

        log_msg = TradeFormatter.format_entry(
            timestamp=timestamp,
            symbol=self.display_symbol,
            quantity=pyramid_qty,
            price=price,
            total=total_price,
            lot_size=lot_size,
            step=1 if len(self.pyramid_steps) > 1 else None,
            total_steps=len(self.pyramid_steps) if len(self.pyramid_steps) > 1 else None,
        )
        logger.info(log_msg)

        if self.order_manager:
            self.order_manager.place_order(self.symbol, side, pyramid_qty, timestamp=timestamp)

    def _close_position(
        self,
        price: float,
        timestamp: datetime,
        reason: str,
        reason_desc: str = "",
        quantity: int | None = None,
        nifty_price: float | None = None,
    ) -> None:
        """
        Executes a partial or full exit.
        If current_position is None, it might be recording a summary exit for a just-closed position.
        """
        pos = self.current_position or self._last_pos_for_summary

        if not pos:
            return

        close_qty = quantity if quantity is not None else pos.remaining_quantity

        # Allow 0 quantity ONLY for SUMMARY_EXIT
        if close_qty <= 0 and reason != "SUMMARY_EXIT":
            return

        # Determine exit side
        is_long_dir = (self.instrument_type == InstrumentKindType.OPTIONS) or (pos.intent == MarketIntentType.LONG)
        exit_side = "SELL" if is_long_dir else "BUY"

        lot_size = settings.NIFTY_LOT_SIZE
        # PnL is (Exit - Entry) for Long, (Entry - Exit) for Short
        if is_long_dir:
            chunk_pnl = (price - pos.entry_price) * close_qty * lot_size
        else:
            chunk_pnl = (pos.entry_price - price) * close_qty * lot_size

        pos.total_realized_pnl += chunk_pnl
        self.session_realized_pnl += chunk_pnl

        lot_size = settings.NIFTY_LOT_SIZE
        fmt_time = DateUtils.to_iso(timestamp)
        total_price = close_qty * lot_size * price
        trans_desc = f"Sold {close_qty} lots({lot_size}) @ {price} | Total: ₹{total_price:,.2f}"
        if pos.display_symbol:
            trans_desc = f"[{pos.display_symbol}] " + trans_desc

        if quantity is not None and reason.startswith("TARGET"):
            log_msg = TradeFormatter.format_target(
                timestamp=timestamp,
                target_num=pos.achieved_targets,
                symbol=pos.display_symbol,
                quantity=close_qty,
                price=price,
                total=total_price,
                lot_size=lot_size,
                action_pnl=chunk_pnl,
            )
            logger.info(log_msg)
            if self.on_trade_event:
                pos.event_count += 1
                self.on_trade_event(
                    {
                        "tradetime": DateUtils.to_iso(timestamp),
                        "instrument": pos.display_symbol,
                        "cycleId": pos.trade_cycle,
                        "cycleSeq": pos.event_count,
                        "type": reason.lower(),
                        "transaction": f"{reason} Hit: {trans_desc} | Action PnL: {chunk_pnl:+.2f} | Total PnL: {self.session_realized_pnl:+.2f}",
                        "actionPnL": chunk_pnl,
                        "cyclePnL": pos.total_realized_pnl,
                        "totalPnL": self.session_realized_pnl,
                    }
                )

            # Record in Position's target_events
                pos.target_events.append(
                    {
                        "step": pos.achieved_targets,
                        "time": fmt_time,
                        "price": price,
                        "quantity": close_qty,
                        "actionPnl": chunk_pnl,
                        "niftyPrice": nifty_price or 0.0,
                        "transaction": trans_desc,
                    }
                )
        else:
            log_msg = TradeFormatter.format_exit(
                timestamp=timestamp,
                reason=reason,
                symbol=pos.display_symbol,
                quantity=close_qty,
                price=price,
                total=total_price,
                lot_size=lot_size,
                action_pnl=chunk_pnl,
                cycle_pnl=pos.total_realized_pnl,
                session_pnl=self.session_realized_pnl,
                reason_desc=reason_desc,
            )
            logger.info(log_msg)
            if self.on_trade_event:
                pos.event_count += 1
                self.on_trade_event(
                    {
                        "tradetime": DateUtils.to_iso(timestamp),
                        "instrument": pos.display_symbol,
                        "cycleId": pos.trade_cycle,
                        "cycleSeq": pos.event_count,
                        "type": "exit",
                        "transaction": f"Exit {reason}: {trans_desc} | Action PnL: {chunk_pnl:+.2f} | Total PnL: {self.session_realized_pnl:+.2f}",
                        "actionPnL": chunk_pnl,
                        "cyclePnL": pos.total_realized_pnl,
                        "totalPnL": self.session_realized_pnl,
                    }
                )

        closed_chunk = Position(
            symbol=pos.symbol,
            display_symbol=pos.display_symbol,
            intent=pos.intent,
            entry_price=pos.entry_price,
            initial_quantity=close_qty,
            entry_time=pos.entry_time,
            stop_loss=pos.stop_loss,
            targets=pos.targets,
            trade_cycle=pos.trade_cycle,
            entry_signal=pos.entry_signal,
            entry_reason_description=pos.entry_reason_description,
            exit_reason_description=reason_desc,
            nifty_price_at_entry=pos.nifty_price_at_entry,
            formatted_entry_time=pos.formatted_entry_time,
            formatted_exit_time=fmt_time,
            entry_transaction_desc=pos.entry_transaction_desc,
            exit_transaction_desc=trans_desc,
        )
        closed_chunk.exit_price = price
        closed_chunk.exit_time = timestamp
        closed_chunk.nifty_price_at_exit = nifty_price or 0.0
        closed_chunk.status = reason
        closed_chunk.pnl = chunk_pnl
        closed_chunk.quantity = close_qty

        self.trades_history.append(closed_chunk)
        pos.remaining_quantity -= close_qty

        if self.order_manager and close_qty > 0:
            self.order_manager.place_order(self.symbol, exit_side, close_qty, timestamp=timestamp)

        if pos.remaining_quantity <= 0:
            self._last_pos_for_summary = pos # Keep reference for summary exit if needed
            self.current_position = None

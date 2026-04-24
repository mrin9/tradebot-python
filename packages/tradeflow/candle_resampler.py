import logging
from typing import Any, Callable
from packages.settings import settings


class CandleResampler:
    """
    Resamples smaller timeframe candles (e.g., 1-minute) into larger timeframe candles (e.g., 5-minute).
    """

    def __init__(
        self,
        instrument_id: int,
        symbol: str,
        timeframe_mins: int,
        on_candle_closed: Callable[[dict, Any], None] | None = None,
        category: Any = None,
        logger: logging.Logger | None = None,
    ):
        """
        Args:
            instrument_id (int): Instrument ID to filter/track.
            symbol (str): A string representation of the instrument (e.g., "SPOT").
            timeframe_mins (int): Target candle interval in minutes (e.g., 5 for 5-min).
            on_candle_closed (callable, optional): Callback for closed candles.
            category (Any, optional): Category identifier (e.g. InstrumentCategoryType enum) passed to callback.
            logger (logging.Logger, optional): Custom logger instance.
        """
        self.instrument_id = instrument_id
        self.symbol = symbol
        self.timeframe_mins = timeframe_mins
        self.interval_seconds = timeframe_mins * 60  # Convert minutes to seconds for internal use
        self.on_candle_closed = on_candle_closed
        self.category = category

        # Initialize logger with a clear, symbol-specific name if not provided
        self.logger = logger or logging.getLogger(f"CandleResampler.{symbol}")

        self.current_candle: dict[str, Any] | None = None
        self.last_period_start: int | None = None
        self.source_candle_count = 0
        self.suppress_logs = False

        # Identify if this instrument is an index (e.g. NIFTY SPOT)
        self.is_index = (self.instrument_id == settings.NIFTY_INSTRUMENT_ID)

    def reset(self):
        """Resets the resampler state for a clean start."""
        self.current_candle = None
        self.last_period_start = None
        self.source_candle_count = 0

    def _normalize_candle(self, tick: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        """
        Extracts OHLCV and Timestamp from various common tick/candle formats.
        Ensures all values are floats for consistency.
        """
        timestamp = tick.get("t", tick.get("timestamp"))
        open_ = tick.get("o", tick.get("open"))
        high_ = tick.get("h", tick.get("high"))
        low_ = tick.get("l", tick.get("low"))
        close_ = tick.get("c", tick.get("close", tick.get("ltp", tick.get("p"))))
        volume_ = tick.get("v", tick.get("volume"))

        # Convert to float, defaulting to 0.0 or None if not present
        timestamp = float(timestamp) if timestamp is not None else 0.0
        open_ = float(open_) if open_ is not None else 0.0
        high_ = float(high_) if high_ is not None else 0.0
        low_ = float(low_) if low_ is not None else 0.0
        close_ = float(close_) if close_ is not None else 0.0
        volume_ = float(volume_) if volume_ is not None else 0.0

        return timestamp, open_, high_, low_, close_, volume_

    def add_candle(self, tick: dict[str, Any]) -> dict | None:
        """
        Processes a new tick/1m-candle and accumulates it into the resampled timeframe.

        Args:
            tick (Dict): Source tick or smaller timeframe candle.
                         Expected keys: 'o', 'h', 'l', 'c', 'v', 't' (or 'open', 'high'...)

        Returns:
            Dict | None: The *closed* candle if this source tick finalized a period, else None.
        """
        timestamp, open_, high_, low_, close_, volume_ = self._normalize_candle(tick)

        if timestamp == 0:
            self.logger.warning(f"Received tick for {self.symbol} with no valid timestamp: {tick}")
            return None

        # Determine the start of the current aggregation period
        # e.g., for a 5-min candle, 09:16:30 would map to 09:15:00
        period_start = int((timestamp // self.interval_seconds) * self.interval_seconds)

        closed_candle = None

        period_start = (timestamp // self.interval_seconds) * self.interval_seconds

        # Check if we have moved to a new aggregation period
        if self.last_period_start is not None and period_start != self.last_period_start:
            if self.current_candle and self.source_candle_count > 0:
                # The previous candle is now complete and can be emitted
                closed_candle = self.current_candle
                closed_candle["is_final"] = True

                if self.on_candle_closed:
                    if not self.suppress_logs:
                        from datetime import datetime
                        pretty_ts = datetime.fromtimestamp(self.last_period_start).strftime('%H:%M:%S')
                        self.logger.info(
                            f"💡 [CR] Finalizing {self.timeframe_mins}m Candle for {self.symbol} ({self.instrument_id}) "
                            f"@ {pretty_ts} | Source Ticks: {self.source_candle_count} | Close: {closed_candle['close']}"
                        )
                    self.on_candle_closed(closed_candle, self.category or self.symbol, triggering_tick=tick)

            # Reset for the new period, regardless of whether a candle was emitted
            self.current_candle = None
            self.source_candle_count = 0

        self.last_period_start = period_start


        # Initialize or Update
        if not self.current_candle:
            self.current_candle = {
                "instrument_id": self.instrument_id,
                # MATCH JAVA: Use period START as the candle timestamp
                "timestamp": period_start,
                "open": open_,
                "high": high_,
                "low": low_,
                "close": close_,
                "volume": volume_,
                "is_final": False,
            }
        else:
            # Accumulate values for the rest of the period
            self.current_candle["high"] = max(self.current_candle["high"], high_)
            self.current_candle["low"] = min(self.current_candle["low"], low_)
            self.current_candle["close"] = close_
            self.current_candle["volume"] += volume_
        
        # SOURCE COUNT LOGIC:
        # 1. Reject flush markers (already handled above)
        # 2. For traded instruments, only count if volume > 0 (to ignore quote noise)
        # 3. For indices (Nifty Spot), always count (since volume is always 0)
        if not tick.get("is_flush"):
            if self.is_index or volume_ > 0:
                self.source_candle_count += 1

        return closed_candle

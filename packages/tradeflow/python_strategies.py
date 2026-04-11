from datetime import datetime
from typing import Any

import pytz

from packages.settings import settings
from packages.tradeflow.types import CandleType, MarketIntentType, SignalType


class TripleLockStrategy:
    """
    Standard Triple Confirmation Strategy implementation.

    Logic:
    - Entry: Requires a crossover on the Option (CE/PE) EMA, confirmed by Nifty Spot EMA state
      and the opposing option's EMA state (pe-ema < pe-ema-21 for call entry).
    - Session Protection: Only triggers on fresh intraday crossovers. Gap-induced crossovers
      from the previous day are ignored.

    Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:TripleLockStrategy
    """

    def __init__(self):
        """Initializes strategy state."""
        pass

    def on_resampled_candle_closed(
        self, candle: CandleType, indicators: dict[str, Any], current_position_intent: MarketIntentType | None = None
    ) -> tuple[SignalType, str, float]:
        # Market Open Stability Guard
        tz = pytz.timezone(settings.MARKET_TIMEZONE)
        ts = candle.get("t", candle.get("timestamp"))
        candle_dt = datetime.fromtimestamp(ts, tz)
        start_time = datetime.strptime(settings.TRADE_START_TIME, "%H:%M:%S").time()

        is_warming_up = indicators.get("meta-is-warming-up", False)

        if candle_dt.time() < start_time:
            return SignalType.NEUTRAL, f"PYTHON: BEFORE START TIME ({settings.TRADE_START_TIME})", 0.0

        spot_fast = indicators.get("nifty-ema-5")
        spot_slow = indicators.get("nifty-ema-21")

        # 1. Gather Required Data
        ce_fast = indicators.get("ce-ema-5")
        ce_slow = indicators.get("ce-ema-21")
        ce_f_prev = indicators.get("ce-ema-5-prev")
        ce_s_prev = indicators.get("ce-ema-21-prev")

        pe_fast = indicators.get("pe-ema-5")
        pe_slow = indicators.get("pe-ema-21")
        pe_f_prev = indicators.get("pe-ema-5-prev")
        pe_s_prev = indicators.get("pe-ema-21-prev")

        # Wait for history and ensure all indicators are non-None
        required_indicators = [
            ce_fast,
            ce_slow,
            ce_f_prev,
            ce_s_prev,
            pe_fast,
            pe_slow,
            pe_f_prev,
            pe_s_prev,
            spot_fast,
            spot_slow,
        ]
        if any(v is None for v in required_indicators):
            return SignalType.NEUTRAL, "PYTHON: WAITING FOR INDICATOR WARMUP", 0.0

        # 2. Entry Logic (Bidirectional)
        if current_position_intent is None:
            # --- CHECK CALL ENTRY ---
            crossover_ce = (ce_f_prev <= ce_s_prev) and (ce_fast > ce_slow)

            if crossover_ce:
                if spot_fast > spot_slow and pe_fast < pe_slow:  # Confirmations
                    reason = "Triple Lock CALL Entry"
                    return SignalType.LONG, f"PYTHON: {reason}", 1.0

            # --- CHECK PUT ENTRY ---
            crossover_pe = (pe_f_prev <= pe_s_prev) and (pe_fast > pe_slow)

            if crossover_pe:
                if spot_fast < spot_slow and ce_fast < ce_slow:  # Confirmations
                    reason = "Triple Lock PUT Entry"
                    return SignalType.SHORT, f"PYTHON: {reason}", 1.0

        # 3. Exit Logic
        if current_position_intent == MarketIntentType.LONG:
            if (ce_f_prev >= ce_s_prev) and (ce_fast < ce_slow):  # Crossunder
                return SignalType.EXIT, "PYTHON: CALL Crossunder Exit", 0.0
        elif current_position_intent == MarketIntentType.SHORT:
            if (pe_f_prev >= pe_s_prev) and (pe_fast < pe_slow):  # Crossunder
                return SignalType.EXIT, "PYTHON: PUT Crossunder Exit", 0.0

        # 4. Final Maintenance
        return SignalType.NEUTRAL, "No signal", 0.0


class SimpleMACDStrategy:
    """Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:SimpleMACDStrategy"""

    def __init__(self):
        self.ce_prev_hist = None
        self.pe_prev_hist = None
        self._last_trade_date = None

    def on_resampled_candle_closed(
        self, candle: CandleType, indicators: dict[str, Any], current_position_intent: MarketIntentType | None = None
    ) -> tuple[SignalType, str, float]:

        # Market Open Stability Guard
        tz = pytz.timezone(settings.MARKET_TIMEZONE)
        ts = candle.get("t", candle.get("timestamp"))
        candle_dt = datetime.fromtimestamp(ts, tz)
        start_time = datetime.strptime(settings.TRADE_START_TIME, "%H:%M:%S").time()

        if candle_dt.time() < start_time:
            return SignalType.NEUTRAL, f"PYTHON: BEFORE START TIME ({settings.TRADE_START_TIME})", 0.0

        # Reset stale state on day change to prevent false crossovers
        if self._last_trade_date != candle_dt.date():
            self.ce_prev_hist = None
            self.pe_prev_hist = None
            self._last_trade_date = candle_dt.date()

        ce_hist = indicators.get("ce-macd-hist")
        pe_hist = indicators.get("pe-macd-hist")

        if ce_hist is None or pe_hist is None:
            return SignalType.NEUTRAL, "PYTHON: WARMING UP", 0.0

        signal = SignalType.NEUTRAL
        reason = "No signal"

        # 1. Entry Logic (Bidirectional)
        if current_position_intent is None:
            c_ce = self.ce_prev_hist is not None and self.ce_prev_hist <= 0 and ce_hist > 0
            c_pe = self.pe_prev_hist is not None and self.pe_prev_hist <= 0 and pe_hist > 0

            if c_ce:
                signal, reason = (
                    SignalType.LONG,
                    "PYTHON: CE MACD Crossover",
                )
            elif c_pe:
                signal, reason = (
                    SignalType.SHORT,
                    "PYTHON: PE MACD Crossover",
                )

        # 2. Exit Logic (Bidirectional)
        elif current_position_intent == MarketIntentType.LONG:
            if self.ce_prev_hist is not None and self.ce_prev_hist > 0 and ce_hist <= 0:
                signal, reason = SignalType.EXIT, "PYTHON: CE MACD Crossunder Exit"
        elif current_position_intent == MarketIntentType.SHORT:
            if self.pe_prev_hist is not None and self.pe_prev_hist > 0 and pe_hist <= 0:
                signal, reason = SignalType.EXIT, "PYTHON: PE MACD Crossunder Exit"

        # Update state for next cycle
        self.ce_prev_hist = ce_hist
        self.pe_prev_hist = pe_hist

        return signal, reason, 1.0 if signal in [SignalType.LONG, SignalType.SHORT] else 0.0


class EmaCrossWithRsiStrategy:
    """
    Standard EMA Crossover confirmed by RSI.
    Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:EmaCrossWithRsiStrategy

    Logic:
    - Entry: active-ema-5 crosses ABOVE active-ema-21 AND active-rsi-14 > 50.
    """

    def __init__(self):
        pass

    def on_resampled_candle_closed(
        self, candle: CandleType, indicators: dict[str, Any], current_position_intent: MarketIntentType | None = None
    ) -> tuple[SignalType, str, float]:

        # Market Open Stability Guard
        tz = pytz.timezone(settings.MARKET_TIMEZONE)
        ts = candle.get("t", candle.get("timestamp"))
        candle_dt = datetime.fromtimestamp(ts, tz)
        start_time = datetime.strptime(settings.TRADE_START_TIME, "%H:%M:%S").time()

        if candle_dt.time() < start_time:
            return SignalType.NEUTRAL, f"PYTHON: BEFORE START TIME ({settings.TRADE_START_TIME})", 0.0

        is_warming_up = indicators.get("meta-is-warming-up", False)

        # 1. Gather Required Data (using active mapping for entries, trade for exits)
        fast = indicators.get("active-ema-5")
        slow = indicators.get("active-ema-21")
        fast_prev = indicators.get("active-ema-5-prev")
        slow_prev = indicators.get("active-ema-21-prev")
        rsi = indicators.get("active-rsi-14")

        # Pull trade-pinned indicators for exit stability
        t_fast = indicators.get("trade-ema-5")
        t_slow = indicators.get("trade-ema-21")
        t_fast_prev = indicators.get("trade-ema-5-prev")
        t_slow_prev = indicators.get("trade-ema-21-prev")

        # Wait for indicator warmup
        if any(v is None for v in [fast, slow, fast_prev, slow_prev, rsi]):
            return SignalType.NEUTRAL, "PYTHON: WAITING FOR INDICATOR WARMUP", 0.0

        # 2. Entry Logic
        if current_position_intent is None:
            # Check for bullish crossover
            crossover = fast_prev <= slow_prev and fast > slow

            if crossover:
                if rsi > 50:
                    reason = f"EMA Cross + RSI Confirm ({rsi:.2f})"
                    return SignalType.LONG, f"PYTHON: {reason}", 1.0

        # 3. Exit Logic (uses trade-pinned indicators)
        elif current_position_intent == MarketIntentType.LONG:
            if any(v is None for v in [t_fast, t_slow, t_fast_prev, t_slow_prev]):
                return SignalType.NEUTRAL, "PYTHON: WAITING FOR TRADE INDICATOR WARMUP", 0.0
                
            if t_fast_prev >= t_slow_prev and t_fast < t_slow:
                return SignalType.EXIT, "PYTHON: EMA Crossunder Exit", 0.0

        return SignalType.NEUTRAL, "No signal", 0.0


class SuperTrendAndPriceCrossStrategy:
    """
    Trend-following strategy based on Price vs SuperTrend line.
    Target this via CLI: --python-strategy-path packages/tradeflow/python_strategies.py:SuperTrendAndPriceCrossStrategy
    """

    def __init__(self):
        pass

    def on_resampled_candle_closed(
        self, candle: CandleType, indicators: dict[str, Any], current_position_intent: MarketIntentType | None = None
    ) -> tuple[SignalType, str, float]:

        # Market Open Stability Guard
        tz = pytz.timezone(settings.MARKET_TIMEZONE)
        ts = candle.get("t", candle.get("timestamp"))
        candle_dt = datetime.fromtimestamp(ts, tz)
        start_time = datetime.strptime(settings.TRADE_START_TIME, "%H:%M:%S").time()

        if candle_dt.time() < start_time:
            return SignalType.NEUTRAL, f"PYTHON: BEFORE START TIME ({settings.TRADE_START_TIME})", 0.0

        # 1. Gather Required Data
        is_warming_up = indicators.get("meta-is-warming-up", False)
        price = candle.get("c", candle.get("close"))
        
        # Entries use active (latest market ATM)
        st_line = indicators.get("active-supertrend-10-3")
        st_line_prev = indicators.get("active-supertrend-10-3-prev")
        
        # Exits use trade (specifically held instrument)
        t_st_line = indicators.get("trade-supertrend-10-3")

        # Wait for indicator warmup
        if any(v is None for v in [price, st_line, st_line_prev, t_st_line]):
            return SignalType.NEUTRAL, "PYTHON: WAITING FOR INDICATOR WARMUP", 0.0

        # 2. Entry Logic
        if current_position_intent is None:
            # Price cross ABOVE ST line
            crossover = price > st_line and st_line_prev is not None and candle.get("o", candle.get("c", price)) <= st_line_prev

            if crossover:
                reason = "Price Above Supertrend"
                return SignalType.LONG, f"PYTHON: {reason}", 1.0

        # 3. Exit Logic (uses trade-pinned supertrend)
        elif current_position_intent == MarketIntentType.LONG:
            if price < t_st_line:
                return SignalType.EXIT, "PYTHON: Price Below Supertrend Exit", 0.0

        return SignalType.NEUTRAL, "No signal", 0.0

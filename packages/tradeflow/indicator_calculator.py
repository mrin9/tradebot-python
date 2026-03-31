import logging
import os
from collections import deque
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from packages.tradeflow.types import InstrumentCategoryType

logger = logging.getLogger(__name__)

# InstrumentCategory Enum removed - now imported as InstrumentCategoryType from tradeflow.types

from packages.settings import settings


class IndicatorCalculator:
    """
    Calculates technical indicators dynamically based on strategy rules.
    Maintains separate rolling windows of historical candles per instrument category (SPOT, CE, PE).
    """

    def __init__(self, indicators_config: list[dict[str, Any]], max_window_size: int = settings.GLOBAL_WARMUP_CANDLES):
        """
        Args:
            indicators_config (List[Dict]): The 'indicators' array from strategy_indicator Collection.
                Example: [{'indicatorId': 'fast_ema', 'indicator': 'ema-5', 'InstrumentType': 'SPOT'}]
            max_window_size (int): Max candles to keep per category.
        """
        self.config = indicators_config
        self.max_window_size = max_window_size

        # Dictionary of deques, keyed by instrument_id (e.g., 26000 for NIFTY SPOT)
        self.instrument_candles: dict[int, deque[dict[str, float | int]]] = {}
        # Track the 'current' active instrument ID per category
        self.active_instrument_ids: dict[InstrumentCategoryType, int | None] = {}
        # Cache of the latest calculated results per instrument
        self.latest_results: dict[int, dict[str, float | int | None]] = {}
        self.suppress_logs = False

        # Initialize deques for each unique instrument category from config
        for ind in self.config:
            cat_str = ind.get("InstrumentType", "SPOT")
            try:
                cat = InstrumentCategoryType(cat_str)
            except ValueError:
                cat = InstrumentCategoryType.SPOT

            if cat not in self.active_instrument_ids:
                self.active_instrument_ids[cat] = None

    def reset(self):
        """Clears the deque caches for a fresh start (e.g., between backtest days)."""
        self.instrument_candles.clear()
        self.active_instrument_ids.clear()
        self.latest_results.clear()
        
        for ind in self.config:
            cat_str = ind.get("InstrumentType", "SPOT")
            try:
                cat = InstrumentCategoryType(cat_str)
            except ValueError:
                cat = InstrumentCategoryType.SPOT

            if cat not in self.active_instrument_ids:
                self.active_instrument_ids[cat] = None

    def add_candle(
        self,
        candle: dict[str, Any],
        instrument_category: InstrumentCategoryType = InstrumentCategoryType.SPOT,
        instrument_id: int | None = None,
    ) -> dict[str, float | int | None]:
        """
        Ingests a new candle for a specific instrument category, and recalculates those indicators.
        """
        if isinstance(instrument_category, str):
            try:
                instrument_category = InstrumentCategoryType(instrument_category)
            except ValueError:
                instrument_category = InstrumentCategoryType.SPOT

        # Fallback for old calls or missing IDs
        if instrument_id is None:
            instrument_id = candle.get("instrument_id", candle.get("i"))

        if instrument_id is None:
            # If still None, we can't store by ID. Use a virtual ID based on category hash
            instrument_id = hash(instrument_category)

        ts = candle.get("timestamp", candle.get("t"))

        # Deduplication per instrument: If already seen, just return current cached state
        if instrument_id in self.instrument_candles:
            target_deque = self.instrument_candles[instrument_id]
            if target_deque and target_deque[-1]["timestamp"] == ts:
                return self.extract_indicators(instrument_id, instrument_category)

        # 1. Update active pointer
        self.active_instrument_ids[instrument_category] = instrument_id

        # 2. Initialize deque if new instrument seen
        if instrument_id not in self.instrument_candles:
            self.instrument_candles[instrument_id] = deque(maxlen=self.max_window_size)

        target_deque = self.instrument_candles[instrument_id]
        if target_deque and target_deque[-1]["timestamp"] == ts:
            return self.extract_indicators(instrument_id, instrument_category)

        candle_dict = {
            "open": candle.get("open", candle.get("o")),
            "high": candle.get("high", candle.get("h")),
            "low": candle.get("low", candle.get("l")),
            "close": candle.get("close", candle.get("c")),
            "volume": candle.get("volume", candle.get("v", 0)),
            "timestamp": ts,
        }

        # Validate candle content: drop if all price fields are None (Ghost Candle protection)
        if candle_dict["close"] is None and candle_dict["open"] is None:
            if not self.suppress_logs:
                logger.debug(f"🧹 [IC] Skipping null candle for {instrument_id} @ {ts}")
            return self.extract_indicators(instrument_id, instrument_category)

        target_deque.append(candle_dict)
        
        if not self.suppress_logs:
            from datetime import datetime
            pretty_ts = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
            logger.info(f"📊 [IC] {instrument_category.value} ({instrument_id}) @ {pretty_ts} | Memory: {len(target_deque)} candles | Close: {candle_dict['close']}")


        if len(target_deque) < 1:
            return {}

        # Create DataFrame from the specific instrument's history
        schema = {
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "timestamp": pl.Int64,
        }
        df = pl.DataFrame(list(target_deque), schema=schema)

        # Calculate indicators for this specific category
        indicators_to_calc = []
        for ind in self.config:
            itype_str = ind.get("InstrumentType", "SPOT")
            try:
                itype = InstrumentCategoryType(itype_str)
            except ValueError:
                itype = InstrumentCategoryType.SPOT

            if itype == instrument_category:
                indicators_to_calc.append(ind)
            elif itype == InstrumentCategoryType.OPTIONS_BOTH and instrument_category in [
                InstrumentCategoryType.CE,
                InstrumentCategoryType.PE,
            ]:
                indicators_to_calc.append(ind)

        # 3. Stability Check: Warn if history is too short for long-period indicators (e.g. EMA-21)
        # Rule of thumb: EMA needs approx 3.5 * period to stabilize
        for ind in indicators_to_calc:
            ind_str = ind.get("indicator", ind.get("type", "N/A")).lower()
            if ind_str.startswith("ema-"):
                try:
                    period = int(ind_str.split("-")[1])
                    required = int(period * 3.5)
                    if len(target_deque) < required and not self.suppress_logs:
                        logger.warning(
                            f"⚠️ [IC] Low history for {ind_str} on {instrument_category.value} ({instrument_id}). "
                            f"Have {len(target_deque)} bars, need ~{required} for stabilization. Values may lag."
                        )
                except (ValueError, IndexError):
                    pass

        try:
            # Forward fill null prices to ensure indicator calculations (like EMA) don't break
            df = df.with_columns([
                pl.col(c).forward_fill() for c in ["open", "high", "low", "close"]
            ])

            for ind in indicators_to_calc:
                ind_shorthand = ind.get("indicator", ind.get("type", "N/A"))
                key = ind.get("indicatorId") or ind_shorthand
                df = self.calculate_indicator(df, ind_shorthand, key)

            res = self._extract_results_from_df(df, instrument_category, indicators_to_calc)
            self.latest_results[instrument_id] = res
            
            # Log results for debugging
            if not self.suppress_logs:
                ema_logs = [f"{k}: {v:.2f}" for k, v in res.items() if "ema" in k and "prev" not in k and v is not None]
                if ema_logs:
                    logger.info(f"📈 [IC] Results for {instrument_id}: {', '.join(ema_logs)}")
                
            return res
        except Exception as e:
            logger.error(f"Error calculating indicators for category {instrument_category}: {e}", exc_info=True)
            return {}

    def extract_indicators(
        self, instrument_id: int, instrument_category: InstrumentCategoryType
    ) -> dict[str, float | int | None]:
        """
        Manually extracts the latest indicator values for a specific instrument from the internal cache.
        """
        return self.latest_results.get(instrument_id, {})

    def dump_to_csv(self, instrument_id: int, instrument_category: InstrumentCategoryType, filename: str):
        """Re-calculates the full dataframe for an instrument and writes it to CSV for diagnostics."""
        if instrument_id not in self.instrument_candles:
            logger.warning(f"No history to dump for {instrument_id}")
            return
            
        target_deque = self.instrument_candles[instrument_id]
        if len(target_deque) < 1:
            return

        schema = {
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Float64,
            "timestamp": pl.Int64,
        }
        df = pl.DataFrame(list(target_deque), schema=schema)

        indicators_to_calc = []
        for ind in self.config:
            itype_str = ind.get("InstrumentType", "SPOT")
            try:
                itype = InstrumentCategoryType(itype_str)
            except ValueError:
                itype = InstrumentCategoryType.SPOT

            if itype == instrument_category:
                indicators_to_calc.append(ind)
            elif itype == InstrumentCategoryType.OPTIONS_BOTH and instrument_category in [
                InstrumentCategoryType.CE,
                InstrumentCategoryType.PE,
            ]:
                indicators_to_calc.append(ind)

        df = df.with_columns([
            pl.col(c).forward_fill() for c in ["open", "high", "low", "close"]
        ])

        for ind in indicators_to_calc:
            ind_shorthand = ind.get("indicator", ind.get("type", "N/A"))
            key = ind.get("indicatorId") or ind_shorthand
            df = self.calculate_indicator(df, ind_shorthand, key)
            
        # Convert timestamp to human readable format before saving
        df = df.with_columns(
            pl.from_epoch("timestamp", time_unit="s")
            .dt.cast_time_unit("ms")
            .dt.replace_time_zone("UTC")
            .dt.convert_time_zone("Asia/Kolkata")
            .alias("datetime")
        )
        
        try:
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            df.write_csv(filename)
            logger.info(f"💾 Dumped {len(df)} rows of {instrument_category.value} data to {filename}")
        except Exception as e:
            logger.error(f"Failed to dump CSV to {filename}: {e}")

    def _extract_results_from_df(
        self, df: pl.DataFrame, category: InstrumentCategoryType, indicators: list[dict[str, Any]]
    ) -> dict[str, float | int | None]:
        """Helper to pull latest and prev rows from a calculated Polars DataFrame."""
        if df.height < 1:
            return {}

        result = {}
        last_row = df.row(-1, named=True)
        prev_row = df.row(-2, named=True) if df.height >= 2 else None

        prefix = "nifty-" if category == InstrumentCategoryType.SPOT else f"{category.value.lower()}-"

        # logger.debug(f"Extracting results for {category} with prefix {prefix}. Indicators: {[i.get('indicatorId') for i in indicators]}")

        for ind in indicators:
            ind_shorthand = ind.get("indicator", ind.get("type", "N/A"))
            orig_key = ind.get("indicatorId") or ind_shorthand
            ind_str = ind_shorthand.lower()

            keys_to_extract = [orig_key]
            if ind_str.startswith("supertrend"):
                keys_to_extract.append(f"{orig_key}-dir")
            elif ind_str.startswith("macd"):
                keys_to_extract.extend([f"{orig_key}-signal", f"{orig_key}-hist"])
            elif ind_str.startswith("bbands"):
                keys_to_extract = [f"{orig_key}-upper", f"{orig_key}-middle", f"{orig_key}-lower"]

            for k in keys_to_extract:
                prefixed_key = f"{prefix}{k}"
                if k in last_row:
                    result[prefixed_key] = last_row[k]
                if prev_row and k in prev_row:
                    result[f"{prefixed_key}-prev"] = prev_row[k]

        return result

    @staticmethod
    def calculate_indicator(df: pl.DataFrame, indicator_str: str, result_key: str) -> pl.DataFrame:
        """
        Calculates indicators using shorthand string notation (e.g. 'ema-9', 'bbands-20-2').
        Uses purely vectorized Polars expressions.
        """
        parts = indicator_str.lower().split("-")
        ind_type = parts[0]

        if ind_type == "ema":
            period = int(parts[1]) if len(parts) > 1 else 14
            return df.with_columns(pl.col("close").ewm_mean(span=period, adjust=False).alias(result_key))

        elif ind_type == "sma":
            period = int(parts[1]) if len(parts) > 1 else 14
            return df.with_columns(pl.col("close").rolling_mean(window_size=period).alias(result_key))

        elif ind_type == "rsi":
            period = int(parts[1]) if len(parts) > 1 else 14
            delta = pl.col("close").diff()
            gain = delta.clip(lower_bound=0)
            loss = delta.clip(upper_bound=0).abs()
            avg_gain = gain.ewm_mean(alpha=1 / period, adjust=False, min_samples=period)
            avg_loss = loss.ewm_mean(alpha=1 / period, adjust=False, min_samples=period)
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            return df.with_columns(rsi.alias(result_key))

        elif ind_type == "atr":
            period = int(parts[1]) if len(parts) > 1 else 14
            prev_close = pl.col("close").shift(1)
            tr = pl.max_horizontal(
                [
                    pl.col("high") - pl.col("low"),
                    (pl.col("high") - prev_close).abs(),
                    (pl.col("low") - prev_close).abs(),
                ]
            )
            atr = tr.ewm_mean(span=period, adjust=False)
            return df.with_columns(atr.alias(result_key))

        elif ind_type == "supertrend":
            period = int(parts[1]) if len(parts) > 1 else 10
            multiplier = float(parts[2]) if len(parts) > 2 else 3.0
            return IndicatorCalculator._calc_supertrend(df, period, multiplier, result_key)

        elif ind_type == "macd":
            fast = int(parts[1]) if len(parts) > 1 else 12
            slow = int(parts[2]) if len(parts) > 2 else 26
            signal = int(parts[3]) if len(parts) > 3 else 9
            ema_fast = pl.col("close").ewm_mean(span=fast, adjust=False)
            ema_slow = pl.col("close").ewm_mean(span=slow, adjust=False)
            macd_line = ema_fast - ema_slow
            macd_signal = macd_line.ewm_mean(span=signal, adjust=False)
            macd_hist = macd_line - macd_signal
            return df.with_columns(
                [
                    macd_line.alias(f"{result_key}"),
                    macd_signal.alias(f"{result_key}-signal"),
                    macd_hist.alias(f"{result_key}-hist"),
                ]
            )

        elif ind_type == "bbands":
            period = int(parts[1]) if len(parts) > 1 else 20
            std_dev_mult = float(parts[2]) if len(parts) > 2 else 2.0
            middle_band = pl.col("close").rolling_mean(window_size=period)
            std_dev = pl.col("close").rolling_std(window_size=period)
            upper_band = middle_band + (std_dev * std_dev_mult)
            lower_band = middle_band - (std_dev * std_dev_mult)
            return df.with_columns(
                [
                    upper_band.alias(f"{result_key}-upper"),
                    middle_band.alias(f"{result_key}-middle"),
                    lower_band.alias(f"{result_key}-lower"),
                ]
            )

        elif ind_type == "vwap":
            cum_pv = (pl.col("close") * pl.col("volume")).cum_sum()
            cum_v = pl.col("volume").cum_sum()
            vwap = cum_pv / (cum_v + 1e-10)
            return df.with_columns(vwap.alias(result_key))

        elif ind_type == "obv":
            price_change_sign = pl.col("close").diff().sign().fill_null(0)
            obv = (price_change_sign * pl.col("volume")).cum_sum()
            return df.with_columns(obv.alias(result_key))

        elif ind_type == "price":
            return df.with_columns(pl.col("close").alias(result_key))

        else:
            logger.warning(f"Unknown indicator format: {indicator_str}")
            return df

    @staticmethod
    def _calc_supertrend(df: pl.DataFrame, period: int, multiplier: float, result_key: str) -> pl.DataFrame:
        """
        Implementation of Supertrend using Polars and a small recursive loop for final bands.
        """
        # 1. Calculate ATR
        prev_close = df.select(pl.col("close").shift(1)).to_series()
        tr_expr = pl.max_horizontal(
            [pl.col("high") - pl.col("low"), (pl.col("high") - prev_close).abs(), (pl.col("low") - prev_close).abs()]
        ).fill_null(strategy="zero")
        atr_expr = tr_expr.ewm_mean(span=period, adjust=False)
        atr = df.select(atr_expr).to_series().to_numpy()

        # 2. Basic Bands
        hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
        upper_basic = hl2 + (multiplier * atr)
        lower_basic = hl2 - (multiplier * atr)

        closes = df["close"].to_numpy()
        n = len(closes)

        upper_final = np.zeros(n)
        lower_final = np.zeros(n)
        supertrend = np.zeros(n)
        direction = np.zeros(n)  # 1 for Bullish, -1 for Bearish

        for i in range(n):
            if i == 0:
                upper_final[i] = upper_basic[i]
                lower_final[i] = lower_basic[i]
                direction[i] = 1
                supertrend[i] = lower_final[i]
            else:
                # Upper Final
                if upper_basic[i] < upper_final[i - 1] or closes[i - 1] > upper_final[i - 1]:
                    upper_final[i] = upper_basic[i]
                else:
                    upper_final[i] = upper_final[i - 1]

                # Lower Final
                if lower_basic[i] > lower_final[i - 1] or closes[i - 1] < lower_final[i - 1]:
                    lower_final[i] = lower_basic[i]
                else:
                    lower_final[i] = lower_final[i - 1]

                # Direction and Supertrend
                if direction[i - 1] == 1:
                    if closes[i] <= lower_final[i]:
                        direction[i] = -1
                        supertrend[i] = upper_final[i]
                    else:
                        direction[i] = 1
                        supertrend[i] = lower_final[i]
                elif closes[i] >= upper_final[i]:
                    direction[i] = 1
                    supertrend[i] = lower_final[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_final[i]

        return df.with_columns(
            [pl.Series(name=result_key, values=supertrend), pl.Series(name=f"{result_key}-dir", values=direction)]
        )

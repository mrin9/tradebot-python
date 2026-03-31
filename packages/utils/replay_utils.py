

class ReplayUtils:
    @staticmethod
    def explode_bar_to_ticks(
        instrument_id: int, candle: dict, base_timestamp: int, default_price: float = 0.0
    ) -> list[dict]:
        """
        Explodes a 1-minute OHLCV bar into 4 sequential virtual ticks.
        Sequence: Open (0s) -> High (15s) -> Low (30s) -> Close (59s)

        This guarantees both the socket simulator and the FundManager's backtester
        use the identical synthetic sequence, avoiding subtle replication bugs.
        """
        open_ = candle.get("o", candle.get("open", candle.get("p", default_price)))
        high = candle.get("h", candle.get("high", default_price))
        low = candle.get("l", candle.get("low", default_price))

        close = candle.get("c", candle.get("close", default_price))

        # Vol chunk logic
        vol = candle.get("v", candle.get("volume", 0))
        vol_chunk = vol // 4 if isinstance(vol, (int, float)) else 0

        start_t = base_timestamp - 59

        return [
            {"i": instrument_id, "p": open_, "t": start_t, "v": vol_chunk, "is_snapshot": False},
            {"i": instrument_id, "p": high, "t": start_t + 15, "v": vol_chunk, "is_snapshot": False},
            {"i": instrument_id, "p": low, "t": start_t + 30, "v": vol_chunk, "is_snapshot": True},

            {"i": instrument_id, "p": close, "t": base_timestamp, "v": vol_chunk, "is_snapshot": False},
        ]

from datetime import datetime


class TradeFormatter:
    """
    Centralized utility for formatting trade-related logs with consistent colors and emojis.
    Separates presentation logic from trading logic.
    """

    # Emojis
    EMOJI_ENTRY = "🔵"
    EMOJI_EXIT_PROFIT = "🟢"
    EMOJI_EXIT_NEUTRAL = "⚪"
    EMOJI_EXIT_LOSS = "🔴"
    EMOJI_TARGET = "🟠"
    EMOJI_BREAKEVEN = "🤟"
    EMOJI_PYRAMID = "📈"
    EMOJI_HEARTBEAT = "💚"
    EMOJI_SIGNAL = "⭕"
    EMOJI_WARNING = "⚠️"
    EMOJI_ERROR = "❌"
    EMOJI_SUCCESS = "✅"
    EMOJI_SYNC = "🔄"
    EMOJI_WARMUP = "🔥"
    EMOJI_ROCKET = "🚀"
    EMOJI_PLUG = "🔌"
    EMOJI_THREAD = "🧵"
    EMOJI_MOON = "🌙"
    EMOJI_CONTINUITY = "🔁"

    @staticmethod
    def _format_event_prefix(emoji: str, timestamp: datetime, symbol: str, event_label: str) -> str:
        """Helper to unify the [Emoji] [Timestamp] Event | Symbol prefix used in most logs."""
        fmt_time = timestamp.strftime("%d-%b-%y %H:%M:%S").upper()
        return f"{emoji} [{fmt_time}] {event_label} | {symbol}"

    @staticmethod
    def format_entry(
        timestamp: datetime,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        step: int | None = None,
        total_steps: int | None = None,
    ) -> str:
        """Formats the initial trade entry log, including optional pyramid step info."""
        step_suffix = f" (Pyramid {step}/{total_steps})" if step and total_steps else ""
        prefix = TradeFormatter._format_event_prefix(
            TradeFormatter.EMOJI_ENTRY, timestamp, symbol, f"Entry{step_suffix}"
        )
        return f"{prefix} | Purchased {quantity} lots({quantity * lot_size}) @ {price:,.2f} | Total: {int(total):,}"

    @staticmethod
    def format_target(
        timestamp: datetime,
        target_num: int,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        action_pnl: float,
    ) -> str:
        """Formats logs when a specific profit target is hit."""
        prefix = TradeFormatter._format_event_prefix(
            TradeFormatter.EMOJI_TARGET, timestamp, symbol, f"TARGET_{target_num} Hit"
        )
        return f"{prefix} | Sold {quantity} lots({quantity * lot_size}) @ {price:,.2f} | Total: {int(total):,} | Action PnL: {int(action_pnl):+,}"

    @staticmethod
    def format_exit(
        timestamp: datetime,
        reason: str,
        symbol: str,
        quantity: int,
        price: float,
        total: float,
        lot_size: int,
        action_pnl: float,
        cycle_pnl: float,
        session_pnl: float,
        reason_desc: str = "",
    ) -> str:
        """Formats the final or partial exit log with comprehensive PnL metrics."""
        if cycle_pnl > 0:
            emoji = TradeFormatter.EMOJI_EXIT_PROFIT
        elif cycle_pnl < 0:
            emoji = TradeFormatter.EMOJI_EXIT_LOSS
        else:
            emoji = TradeFormatter.EMOJI_EXIT_NEUTRAL
        
        desc_suffix = f": {reason_desc}" if reason_desc else ""
        prefix = TradeFormatter._format_event_prefix(emoji, timestamp, symbol, f"Exit {reason}{desc_suffix}")
        
        return (
            f"{prefix} | Sold {quantity} lots({quantity * lot_size}) @ {price:,.2f} | "
            f"Total: {int(total):,} | Action PnL: {int(action_pnl):+,} | "
            f"Cycle PnL: {int(cycle_pnl):+,} | Session PnL: {int(session_pnl):+,}"
        )

    @staticmethod
    def format_breakeven(timestamp: datetime, price: float) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M:%S").upper()
        return f"{TradeFormatter.EMOJI_BREAKEVEN} [{fmt_time}] Break-Even Triggered! SL moved to Entry ({price})"

    @staticmethod
    def format_pyramid(
        timestamp: datetime, step: int, total_steps: int, quantity: int, price: float, avg_price: float, total_qty: int
    ) -> str:
        fmt_time = timestamp.strftime("%d-%b %H:%M:%S").upper()
        return (
            f"{TradeFormatter.EMOJI_PYRAMID} [{fmt_time}] PYRAMID Step {step}/{total_steps}: "
            f"Added {quantity} lots @ {price} | New Avg: {avg_price:.2f} | "
            f"Total Qty: {total_qty}"
        )

    @staticmethod
    def format_heartbeat(
        time_display: str, indicators: dict[str, float], trade_desc: str = "", active_desc: str = "", inverse_desc: str = ""
    ) -> str:
        state_str = TradeFormatter._format_indicator_state(indicators)
        instr = " , ".join([f"{k}: {v}" for k, v in {"trade": trade_desc, "active": active_desc, "inverse": inverse_desc}.items() if v and v not in ("None", "N/A")])
        parts = [f"{TradeFormatter.EMOJI_HEARTBEAT} HEARTBEAT [{time_display}]"]
        if instr: parts.append(instr)
        parts.append(f"State: {state_str}")
        return " | ".join(parts)

    @staticmethod
    def _format_indicator_state(indicators: dict[str, float]) -> str:
        """
        Generic helper to format indicator states based on prefix types and parameter groups.
        E.g., ema-5 and ema-21 become ema-5~21: 23000 ~ 23050.
        """
        if not indicators:
            return "N/A"

        # tree: instrument -> is_prev -> indicator_type -> params -> sub_output -> value
        data = {}

        instruments = ["nifty", "active", "inverse", "ce", "pe", "spot", "trade"]

        for k, v in indicators.items():
            instrument = "other"
            for inst in instruments:
                if k.startswith(inst + "-") or k.startswith(inst + "_"):
                    instrument = inst
                    k = k[len(inst) + 1 :]
                    break

            parts = k.split("-")
            is_prev = False
            if "prev" in parts:
                is_prev = True
                parts.remove("prev")

            if not parts:
                continue

            indicator_type = parts[0]

            sub_output = "main"
            if len(parts) > 1 and not parts[-1].replace(".", "").isdigit():
                sub_output = parts[-1]
                params = "-".join(parts[1:-1])
            else:
                params = "-".join(parts[1:])

            (data.setdefault(instrument, {})
             .setdefault(is_prev, {})
             .setdefault(indicator_type, {})
             .setdefault(params, {})[sub_output]) = v

        def param_sort_key(p: str):
            parts_p = []
            for x in p.split("-"):
                try:
                    parts_p.append(float(x))
                except ValueError:
                    parts_p.append(x)
            return parts_p

        def sort_sub_output(sub: str):
            order = {"main": 0, "signal": 1, "hist": 2, "upper": 3, "lower": 4}
            return order.get(sub, 99)

        all_insts = [inst for inst in instruments if inst in data]
        all_insts += [inst for inst in data if inst not in instruments]

        def get_formatted_groups_for_prev(target_is_prev: bool) -> list[str]:
            groups = []
            for inst in all_insts:
                inst_data = data[inst]
                if target_is_prev not in inst_data:
                    continue

                inst_items = []
                type_data = inst_data[target_is_prev]

                for ind_type in sorted(type_data.keys()):
                    params_dict = type_data[ind_type]

                    sorted_params = sorted(params_dict.keys(), key=param_sort_key)

                    params_str = "~".join(p for p in sorted_params if p)

                    key_parts = [ind_type]
                    if target_is_prev:
                        key_parts.append("prev")
                    if params_str:
                        key_parts.append(params_str)

                    formatted_key = "-".join(key_parts)

                    val_groups = []
                    for p in sorted_params:
                        sub_dict = params_dict[p]
                        sorted_subs = sorted(sub_dict.keys(), key=sort_sub_output)

                        sub_vals = []
                        for sub in sorted_subs:
                            v = sub_dict[sub]
                            v_str = f"{v:.2f}" if isinstance(v, (int, float)) else str(v)
                            sub_vals.append(v_str)

                        val_groups.append(",".join(sub_vals))

                    formatted_vals = "~ ".join(val_groups)
                    inst_items.append(f"{formatted_key}: {formatted_vals}")

                if inst_items:
                    groups.append(f"{inst.upper()} " + " | ".join(inst_items))

            return groups

        formatted_groups_normal = get_formatted_groups_for_prev(False)
        formatted_groups_prev = get_formatted_groups_for_prev(True)

        formatted_groups = formatted_groups_normal + formatted_groups_prev

        return " | ".join(formatted_groups)

    @staticmethod
    def format_signal(
        signal_name: str,
        reason: str,
        time_str: str,
        timeframe: int,
        indicators: dict[str, float],
        is_continuity: bool = False,
    ) -> str:
        state_str = TradeFormatter._format_indicator_state(indicators)
        emoji = TradeFormatter.EMOJI_CONTINUITY if is_continuity else TradeFormatter.EMOJI_SIGNAL
        prefix = "Continuity " if is_continuity else ""
        return f"{emoji} {prefix}Signal: {signal_name} ({reason}) | Time: {time_str} | Timeframe: {timeframe}s | State: {state_str}"

    @staticmethod
    def format_instrument_switch(category: str, old_id: int, new_id: int) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Instrument switch detected for {category}: {old_id} -> {new_id}. Clearing indicator window."

    @staticmethod
    def format_warmup(
        category: str, instrument_id: int, timestamp_str: str, count: int = 0, complete: bool = False
    ) -> str:
        if complete:
            return f"Warmup complete for {category} ({instrument_id}) with {count} candles."
        return f"{TradeFormatter.EMOJI_WARMUP} Warming up {category} instrument: {instrument_id} at {timestamp_str}"

    @staticmethod
    def format_drift(current_spot: float, prev_spot: float) -> str:
        return f"{TradeFormatter.EMOJI_SYNC} Spot drifted to {current_spot} (prev {prev_spot}). Recalculating Active Options."

    @staticmethod
    def format_session_start(session_id: str, strategy_name: str, strategy_id: str) -> str:
        lines = [
            f"{TradeFormatter.EMOJI_ROCKET} Starting Live Trade Engine | Session: {session_id}",
            f"{TradeFormatter.EMOJI_SIGNAL} Strategy: {strategy_name} ({strategy_id})",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_connection(status: str, detail: str = "") -> str:
        if status.lower() == "connecting":
            return f"{TradeFormatter.EMOJI_PLUG} {detail}"
        elif status.lower() == "connected":
            return f"{TradeFormatter.EMOJI_SUCCESS} {detail}"
        elif status.lower() == "disconnected":
            return f"{TradeFormatter.EMOJI_WARNING} {detail}"
        return f"{TradeFormatter.EMOJI_PLUG} {status}: {detail}"

    @staticmethod
    def format_eod(symbol: str, price: float) -> str:
        return f"{TradeFormatter.EMOJI_MOON} FundManager: EOD Settlement for {symbol} at {price}"

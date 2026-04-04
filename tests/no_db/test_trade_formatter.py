"""Unit tests for TradeFormatter — pure logic, no DB."""

from datetime import datetime
import pytz

from packages.utils.trade_formatter import TradeFormatter
from packages.utils.date_utils import MARKET_TZ


def _ts(h=10, m=0):
    """Helper to create a market-tz datetime."""
    return MARKET_TZ.localize(datetime(2026, 4, 4, h, m, 0))


class TestFormatEntry:
    def test_basic_entry(self):
        """format_entry produces a string with key trade info."""
        result = TradeFormatter.format_entry(
            timestamp=_ts(), symbol="NIFTY26APR22800CE",
            quantity=1, price=150.0, total=9750.0, lot_size=65,
        )
        assert "NIFTY26APR22800CE" in result
        assert "Entry" in result
        assert "150" in result

    def test_pyramid_step(self):
        """Pyramid step info is included when provided."""
        result = TradeFormatter.format_entry(
            timestamp=_ts(), symbol="SYM", quantity=2, price=100.0,
            total=13000.0, lot_size=65, step=2, total_steps=3,
        )
        assert "Pyramid 2/3" in result


class TestFormatExit:
    def test_profit_emoji(self):
        """Profit exit uses green emoji."""
        result = TradeFormatter.format_exit(
            timestamp=_ts(), reason="TARGET-1", symbol="SYM",
            quantity=1, price=120.0, total=7800.0, lot_size=65,
            action_pnl=1300.0, cycle_pnl=1300.0, session_pnl=1300.0,
        )
        assert TradeFormatter.EMOJI_EXIT_PROFIT in result
        assert "TARGET-1" in result

    def test_loss_emoji(self):
        """Loss exit uses red emoji."""
        result = TradeFormatter.format_exit(
            timestamp=_ts(), reason="STOP-LOSS", symbol="SYM",
            quantity=1, price=90.0, total=5850.0, lot_size=65,
            action_pnl=-650.0, cycle_pnl=-650.0, session_pnl=-650.0,
        )
        assert TradeFormatter.EMOJI_EXIT_LOSS in result

    def test_neutral_emoji(self):
        """Zero PnL exit uses neutral emoji."""
        result = TradeFormatter.format_exit(
            timestamp=_ts(), reason="EOD", symbol="SYM",
            quantity=1, price=100.0, total=6500.0, lot_size=65,
            action_pnl=0.0, cycle_pnl=0.0, session_pnl=0.0,
        )
        assert TradeFormatter.EMOJI_EXIT_NEUTRAL in result


class TestFormatBreakeven:
    def test_breakeven(self):
        result = TradeFormatter.format_breakeven(timestamp=_ts(), price=150.0)
        assert "Break-Even" in result
        assert "150" in result


class TestFormatHeartbeat:
    def test_with_indicators(self):
        """Heartbeat includes indicator state."""
        result = TradeFormatter.format_heartbeat(
            time_display="10:00",
            indicators={"trade-ema-5": 22790.0, "trade-ema-21": 22750.0},
        )
        assert "HEARTBEAT" in result
        assert "TRADE" in result

    def test_empty_indicators(self):
        """Empty indicators shows N/A."""
        result = TradeFormatter.format_heartbeat(time_display="10:00", indicators={})
        assert "N/A" in result


class TestFormatSignal:
    def test_signal(self):
        result = TradeFormatter.format_signal(
            signal_name="LONG", reason="EMA crossover",
            time_str="10:00", timeframe=180, indicators={},
        )
        assert "LONG" in result
        assert "EMA crossover" in result

    def test_continuity_signal(self):
        result = TradeFormatter.format_signal(
            signal_name="LONG", reason="resume",
            time_str="10:00", timeframe=180, indicators={},
            is_continuity=True,
        )
        assert "Continuity" in result
        assert TradeFormatter.EMOJI_CONTINUITY in result


class TestFormatMisc:
    def test_instrument_switch(self):
        result = TradeFormatter.format_instrument_switch("CE", 1001, 2001)
        assert "CE" in result
        assert "1001" in result
        assert "2001" in result

    def test_format_drift(self):
        result = TradeFormatter.format_drift(22100.0, 22000.0)
        assert "22100" in result
        assert "22000" in result

    def test_format_session_start(self):
        result = TradeFormatter.format_session_start("sess-123", "Triple", "triple-confirmation")
        assert "sess-123" in result
        assert "Triple" in result

    def test_format_connection(self):
        assert TradeFormatter.EMOJI_PLUG in TradeFormatter.format_connection("connecting", "XTS")
        assert TradeFormatter.EMOJI_SUCCESS in TradeFormatter.format_connection("connected", "OK")
        assert TradeFormatter.EMOJI_WARNING in TradeFormatter.format_connection("disconnected", "lost")

    def test_format_eod(self):
        result = TradeFormatter.format_eod("NIFTY", 22800.0)
        assert "EOD" in result
        assert "22800" in result


class TestIndicatorStateGrouping:
    def test_ema_grouping(self):
        """Multiple EMA periods for same instrument are grouped."""
        indicators = {"trade-ema-5": 100.0, "trade-ema-21": 105.0}
        result = TradeFormatter._format_indicator_state(indicators)
        assert "TRADE" in result
        assert "ema" in result

    def test_prev_indicators(self):
        """Prev indicators are separated from current."""
        indicators = {"trade-ema-5": 100.0, "trade-ema-prev-5": 98.0}
        result = TradeFormatter._format_indicator_state(indicators)
        assert "prev" in result

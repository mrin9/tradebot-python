import datetime
import unittest

from packages.tradeflow.position_manager import PositionManager
from packages.tradeflow.types import MarketIntentType, SignalPayload


class TestTSLActivation(unittest.TestCase):
    def test_tsl_moves_before_t1(self):
        # Setup: Buy NIFTY at 100, SL at 90 (10 pts), T1 at 110 (10 pts), TSL 5 pts
        pm = PositionManager(
            symbol="NIFTY", quantity=50, sl_pct=10.0, target_pct=[10.0, 20.0], tsl_pct=5.0, use_be=True
        )

        # 1. Entry at 100
        payload = SignalPayload(
            symbol="NIFTY",
            display_symbol="NIFTY",
            signal=MarketIntentType.LONG,
            price=100.0,
            timestamp=datetime.datetime.now(),
            reason="ENTRY",
        )
        pm.on_signal(payload)

        pos = pm.current_position
        self.assertEqual(pos.stop_loss, 90.0)

        # 2. Price moves to 104 (In favor, but NOT T1 yet)
        # Expected: SL stays at 90.0 until T1 hit.
        tick = {"ltp": 104.0, "h": 104.0, "l": 104.0, "c": 104.0}
        pm.update_tick(tick)
        print(f"Price: 104, SL: {pos.stop_loss}, Targets Achieved: {pos.achieved_targets}")
        self.assertEqual(pos.stop_loss, 90.0, "TSL should NOT move SL before Target-1")

        # 3. Price moves to 110 (T1 hit)
        tick = {"ltp": 110.0, "h": 110.0, "l": 110.0, "c": 110.0}
        pm.update_tick(tick)
        print(f"Price: 110 (T1), SL: {pos.stop_loss}, Targets Achieved: {pos.achieved_targets}")
        self.assertGreater(pos.stop_loss, 100.0, "TSL should be active after Target-1")

    def test_tsl_id_moves_before_t1(self):
        # Setup: Buy NIFTY at 100, SL at 90, T1 at 110, TSL Indicator (active-ema-5)
        pm = PositionManager(
            symbol="NIFTY", quantity=50, sl_pct=10.0, target_pct=[10.0, 20.0], tsl_id="active-ema-5", use_be=True
        )

        # 1. Entry at 100
        payload = SignalPayload(
            symbol="NIFTY",
            display_symbol="NIFTY",
            signal=MarketIntentType.LONG,
            price=100.0,
            timestamp=datetime.datetime.now(),
            reason="ENTRY",
        )
        pm.on_signal(payload)

        pos = pm.current_position
        indicators = {"active-ema-5": 105.0}  # Indicator is at 105.0

        # 2. Tick at 106 (Low at 104 > SL, but < Indicator)
        # Price is in profit (106 > 100)
        # BUG: Currently it would exit because Low (104) < Indicator (105)
        # Expected: No exit because T1 (110) hasn't been hit.
        tick = {"ltp": 106.0, "h": 106.0, "l": 104.0, "c": 106.0}
        pm.update_tick(tick, indicators=indicators)

        if pm.current_position:
            print(f"TSL-ID Check - Price: 106, SL: {pos.stop_loss}, Status: {pos.status}")
        else:
            print("TSL-ID Check - Position CLOSED (BUG if T1 not hit)")

        self.assertIsNotNone(pm.current_position, "Position should NOT be closed by TSL-ID before Target-1")


if __name__ == "__main__":
    unittest.main()

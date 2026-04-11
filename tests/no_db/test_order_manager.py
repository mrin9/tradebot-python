"""Unit tests for PaperTradingOrderManager — pure logic, no DB."""

from packages.tradeflow.order_manager import PaperTradingOrderManager


class TestPaperTradingOrderManager:
    def test_place_order_returns_filled(self):
        """Orders are instantly filled in paper mode."""
        om = PaperTradingOrderManager()
        order = om.place_order("NIFTY26APR22800CE", "BUY", 65)
        assert order["status"] == "FILLED"
        assert order["symbol"] == "NIFTY26APR22800CE"
        assert order["side"] == "BUY"
        assert order["quantity"] == 65

    def test_order_ids_increment(self):
        """Each order gets a unique incrementing PAPER-N id."""
        om = PaperTradingOrderManager()
        o1 = om.place_order("SYM", "BUY", 1)
        o2 = om.place_order("SYM", "SELL", 1)
        assert o1["order_id"] == "PAPER-1"
        assert o2["order_id"] == "PAPER-2"

    def test_cancel_existing_order(self):
        """Cancelling an existing order returns True and sets status."""
        om = PaperTradingOrderManager()
        order = om.place_order("SYM", "BUY", 1)
        assert om.cancel_order(order["order_id"]) is True
        assert om.get_order_status(order["order_id"])["status"] == "CANCELLED"

    def test_cancel_nonexistent_order(self):
        """Cancelling a non-existent order returns False."""
        om = PaperTradingOrderManager()
        assert om.cancel_order("PAPER-999") is False

    def test_get_order_status_unknown(self):
        """Unknown order returns UNKNOWN status."""
        om = PaperTradingOrderManager()
        assert om.get_order_status("PAPER-999") == {"status": "UNKNOWN", "price": 0, "quantity": 0}

    def test_order_type_and_price(self):
        """Custom order type and price are stored."""
        om = PaperTradingOrderManager()
        order = om.place_order("SYM", "BUY", 10, order_type="LIMIT", price=150.5)
        assert order["type"] == "LIMIT"
        assert order["price"] == 150.5

    def test_default_order_type_is_market(self):
        """Default order type is MARKET with price 0."""
        om = PaperTradingOrderManager()
        order = om.place_order("SYM", "BUY", 1)
        assert order["type"] == "MARKET"
        assert order["price"] == 0.0

from abc import ABC, abstractmethod
from datetime import datetime

from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger

logger = setup_logger(__name__)


class OrderManager(ABC):
    """
    Abstract Base Class for Order Management.
    Implementations: PaperTradingOrderManager, XTSOrderManager
    """

    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        timestamp: datetime | None = None,
    ) -> dict:
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> dict:
        pass


class PaperTradingOrderManager(OrderManager):
    """
    Simulates order placement by logging them.
    Used for Backtesting and Paper Trading.
    """

    def __init__(self):
        self.orders = {}
        self.order_counter = 1

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        timestamp: datetime | None = None,
    ) -> dict:
        order_id = f"PAPER-{self.order_counter}"
        self.order_counter += 1

        order = {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "type": order_type,
            "price": price,
            "status": "FILLED",  # Instant fill for paper trading
            "timestamp": timestamp or datetime.now(DateUtils.MARKET_TZ),
        }

        self.orders[order_id] = order
        logger.debug(f"[PAPER TRADE] Placing Order: {side} {quantity} {symbol} @ {order_type} | ID: {order_id}")
        return order

    def cancel_order(self, order_id: str) -> bool:
        if order_id in self.orders:
            self.orders[order_id]["status"] = "CANCELLED"
            logger.info(f"[PAPER TRADE] Order {order_id} Cancelled.")
            return True
        return False

    def get_order_status(self, order_id: str) -> dict:
        return self.orders.get(order_id, {"status": "UNKNOWN"})

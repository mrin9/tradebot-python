import random
from datetime import datetime

from packages.settings import settings
from packages.tradeflow.order_manager import OrderManager
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository

import logging

logger = logging.getLogger(__name__)

MOCK_API_COLLECTION = "mock_api"


class MockOrderManager(OrderManager):
    """
    Order manager that persists orders to MongoDB (mock_api collection),
    mimicking XTS API response format. Drop-in replacement for PaperTradingOrderManager
    that can later be swapped for a real XTS order manager.
    """

    def __init__(self, client_id: str = "MOCK", exchange_segment: str = "NSEFO"):
        self.client_id = client_id
        self.exchange_segment = exchange_segment
        self.session_id = None
        self._collection = MongoRepository.get_collection(MOCK_API_COLLECTION)

    def _generate_app_order_id(self) -> int:
        return random.randint(1_000_000_000, 9_999_999_999)

    def _get_last_traded_price(self, instrument_id: int) -> float:
        """Fetch latest candle close price for the instrument from MongoDB."""
        # Try options_candle first, fall back to nifty_candle
        for coll_name in [settings.OPTIONS_CANDLE_COLLECTION, settings.NIFTY_CANDLE_COLLECTION]:
            coll = MongoRepository.get_collection(coll_name)
            doc = coll.find_one({"i": instrument_id}, sort=[("t", -1)])
            if doc:
                return float(doc.get("c", 0))
        return 0.0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        order_type: str = "MARKET",
        price: float = 0.0,
        timestamp: datetime | None = None,
    ) -> dict:
        now = timestamp or datetime.now(DateUtils.MARKET_TZ)
        app_order_id = self._generate_app_order_id()
        time_str = now.strftime("%d-%b-%Y %H:%M:%S")

        # For market orders, fetch LTP; for limit orders, use the provided price
        traded_price = price if price > 0 else self._get_last_traded_price(
            int(symbol.split("_")[0]) if "_" in symbol else 0
        )

        order = {
            "AppOrderID": app_order_id,
            "sessionId": self.session_id,
            "ClientID": self.client_id,
            "ExchangeSegment": self.exchange_segment,
            "OrderSide": side,
            "OrderType": order_type,
            "ProductType": "NRML",
            "TimeInForce": "DAY",
            "OrderPrice": price,
            "OrderQuantity": quantity,
            "OrderStopPrice": 0,
            "OrderStatus": "Filled",
            "OrderAverageTradedPrice": traded_price,
            "LeavesQuantity": 0,
            "CumulativeQuantity": quantity,
            "OrderDisclosedQuantity": 0,
            "OrderGeneratedDateTime": time_str,
            "ExchangeTransactTime": time_str,
            "LastUpdateDateTime": time_str,
            "CancelRejectReason": "",
            "OrderUniqueIdentifier": f"MOCK-{app_order_id}",
            "symbol": symbol,
        }

        self._collection.insert_one(order.copy())
        logger.info(f"[MOCK ORDER] {side} {quantity} {symbol} @ {traded_price} | ID: {app_order_id}")

        return {
            "order_id": str(app_order_id),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "type": order_type,
            "price": traded_price,
            "status": "FILLED",
            "timestamp": now,
        }

    def cancel_order(self, order_id: str) -> bool:
        result = self._collection.update_one(
            {"AppOrderID": int(order_id)},
            {"$set": {"OrderStatus": "Cancelled"}},
        )
        if result.modified_count > 0:
            logger.info(f"[MOCK ORDER] Cancelled: {order_id}")
            return True
        return False

    def get_order_status(self, order_id: str) -> dict:
        doc = self._collection.find_one({"AppOrderID": int(order_id)}, {"_id": 0})
        if doc:
            return {"status": doc.get("OrderStatus", "UNKNOWN"), **doc}
        return {"status": "UNKNOWN"}

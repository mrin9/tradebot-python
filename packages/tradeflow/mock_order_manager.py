import random
from datetime import datetime

from packages.settings import settings
from packages.tradeflow.order_manager import OrderManager
from packages.utils.date_utils import DateUtils
from packages.utils.mongo import MongoRepository

from packages.utils.log_utils import setup_logger

logger = setup_logger("MockOrderManager")

MOCK_API_COLLECTION = "mock_api"


class MockOrderManager(OrderManager):
    """
    Order manager that persists orders to MongoDB (mock_api collection)
    using the exact XTS API response structure. place_order returns only
    AppOrderID (like real XTS). Order state trail is stored as an array
    matching the get_order_history API response format.
    """

    def __init__(self, client_id: str = "MOCK", exchange_segment: str = "NSEFO"):
        self.client_id = client_id
        self.exchange_segment = exchange_segment
        self.session_id = None
        self._collection = MongoRepository.get_collection(MOCK_API_COLLECTION)
        self._used_margin = 0.0

    def _generate_app_order_id(self) -> int:
        return random.randint(1_000_000_000, 9_999_999_999)

    def _check_margin(self, price: float, quantity: int) -> bool:
        if not settings.MOCK_SIMULATE_MARGIN_REJECTION:
            return True
        required = price * quantity * settings.NIFTY_LOT_SIZE
        available = settings.MOCK_AVAILABLE_MARGIN - self._used_margin
        if required > available:
            logger.warning(f"[MOCK ORDER] ❌ MARGIN REJECTED | Required: ₹{required:,.2f} | Available: ₹{available:,.2f}")
            return False
        return True

    def _build_order_entry(self, app_order_id, symbol, side, quantity, order_type, price, time_str, status, traded_price, cumulative_qty, leaves_qty, reject_reason=""):
        """Builds a single XTS order history entry."""
        return {
            "LoginID": self.client_id,
            "ClientID": self.client_id,
            "AppOrderID": app_order_id,
            "OrderReferenceID": "",
            "GeneratedBy": "TWSAPI",
            "ExchangeOrderID": str(random.randint(1_000_000_000_000, 9_999_999_999_999)),
            "OrderCategoryType": "NORMAL",
            "ExchangeSegment": self.exchange_segment,
            "ExchangeInstrumentID": int(symbol) if str(symbol).isdigit() else 0,
            "OrderSide": side,
            "OrderType": order_type,
            "ProductType": "NRML",
            "TimeInForce": "DAY",
            "OrderPrice": price if order_type == "Limit" else 0,
            "OrderQuantity": quantity,
            "OrderStopPrice": 0,
            "OrderStatus": status,
            "OrderAverageTradedPrice": traded_price,
            "LeavesQuantity": leaves_qty,
            "CumulativeQuantity": cumulative_qty,
            "OrderDisclosedQuantity": 0,
            "OrderGeneratedDateTime": time_str,
            "ExchangeTransactTime": time_str,
            "LastUpdateDateTime": time_str,
            "OrderExpiryDate": "01-01-1980 00:00:00",
            "CancelRejectReason": reject_reason,
            "OrderUniqueIdentifier": f"MOCK-{app_order_id}",
            "OrderLegStatus": "SingleOrderLeg",
            "IsSpread": False,
            "MessageCode": 9004,
            "MessageVersion": 4,
            "TokenID": 0,
            "ApplicationType": 0,
            "SequenceNumber": 0,
        }

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
        traded_price = price

        # Log the API call
        logger.info(
            f"[MOCK API] place_order(symbol={symbol}, side={side}, qty={quantity}, "
            f"type={order_type}, price={traded_price}, time={time_str})"
        )

        # Build state trail: always starts with "New"
        new_entry = self._build_order_entry(
            app_order_id, symbol, side, quantity, order_type,
            price, time_str, "New", 0, 0, quantity,
        )

        # Determine final state
        if side == "BUY" and not self._check_margin(traded_price, quantity):
            final_entry = self._build_order_entry(
                app_order_id, symbol, side, quantity, order_type,
                price, time_str, "Rejected", 0, 0, quantity,
                reject_reason="Insufficient margin",
            )
        else:
            final_entry = self._build_order_entry(
                app_order_id, symbol, side, quantity, order_type,
                price, time_str, "Filled", traded_price, quantity, 0,
            )
            # Track margin
            margin_delta = traded_price * quantity * settings.NIFTY_LOT_SIZE
            if side == "BUY":
                self._used_margin += margin_delta
            else:
                self._used_margin = max(0, self._used_margin - margin_delta)

        # Store in MongoDB as XTS order_history structure
        doc = {
            "AppOrderID": app_order_id,
            "symbol": symbol,
            "sessionId": self.session_id,
            "result": [new_entry, final_entry],
        }
        self._collection.insert_one(doc)

        # Log XTS-style place_order response
        response = {
            "type": "success",
            "code": "s-orders-0001",
            "description": "Request sent",
            "result": {
                "AppOrderID": app_order_id,
                "OrderUniqueIdentifier": f"MOCK-{app_order_id}",
                "ClientID": self.client_id,
            },
        }
        logger.info(f"[MOCK API] Response: {response}")

        return {
            "order_id": str(app_order_id),
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "status": "PENDING",
            "timestamp": now,
        }

    def cancel_order(self, order_id: str) -> bool:
        doc = self._collection.find_one({"AppOrderID": int(order_id)})
        if not doc:
            return False
        time_str = datetime.now(DateUtils.MARKET_TZ).strftime("%d-%b-%Y %H:%M:%S")
        last = doc["result"][-1]
        cancelled_entry = {**last, "OrderStatus": "Cancelled", "LastUpdateDateTime": time_str}
        self._collection.update_one(
            {"AppOrderID": int(order_id)},
            {"$push": {"result": cancelled_entry}},
        )
        logger.info(f"[MOCK API] cancel_order(appOrderID={order_id}) → Cancelled")
        return True

    def get_order_status(self, order_id: str) -> dict:
        """
        Queries order history (GET /interactive/orders?appOrderID=...).
        Parses the XTS result array and returns normalized {status, price, quantity}.
        """
        logger.info(f"[MOCK API] get_order_history(appOrderID={order_id})")
        doc = self._collection.find_one({"AppOrderID": int(order_id)}, {"_id": 0})
        if not doc or not doc.get("result"):
            return {"status": "UNKNOWN", "price": 0, "quantity": 0}

        # Parse last element of the state trail — this is the current/final state
        trail = doc["result"]
        final = trail[-1]

        raw_status = final.get("OrderStatus", "Unknown")
        status = "FILLED" if raw_status == "Filled" else raw_status.upper()

        result = {
            "status": status,
            "price": final.get("OrderAverageTradedPrice", 0),
            "quantity": final.get("CumulativeQuantity", 0),
        }

        # Log the XTS-style response
        logger.info(
            f"[MOCK API] Response: {{type: \"success\", result: ["
            + ", ".join(f"{{OrderStatus: \"{e['OrderStatus']}\"}}" for e in trail)
            + f"], final: {{OrderStatus: \"{raw_status}\", "
            f"OrderAverageTradedPrice: {result['price']}, "
            f"CumulativeQuantity: {result['quantity']}}}}}"
        )

        return result

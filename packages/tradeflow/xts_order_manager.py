from datetime import datetime

from packages.settings import settings
from packages.tradeflow.order_manager import OrderManager
from packages.utils.date_utils import DateUtils
from packages.utils.log_utils import setup_logger
from packages.xts.xts_session_manager import XtsSessionManager

logger = setup_logger("XTSOrderManager")


class XTSOrderManager(OrderManager):
    """
    Executes actual orders via the XTS Interactive API.
    """

    def __init__(self, client_id: str | None = None, exchange_segment: str = "NSEFO"):
        self.client_id = client_id or settings.USER_ID
        self.exchange_segment = exchange_segment
        self.session_id = None

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
        time_str = now.strftime("%d-%b-%Y %H:%M:%S")

        logger.info(
            f"[LIVE API] place_order(symbol={symbol}, side={side}, qty={quantity}, "
            f"type={order_type}, limit_price={price}, time={time_str})"
        )

        try:
            # We map options symbol strictly (which is exchangeInstrumentID as an integer string)
            # In live XTS API, orderType can be "Market", "Limit", etc. XTS is case-sensitive for enums.
            xts_order_type = "Market" if order_type.upper() == "MARKET" else order_type.capitalize()
            xts_side = "Buy" if side.upper() == "BUY" else "Sell"

            # call_api automatically formats these into the JSON payload
            response = XtsSessionManager.call_api(
                "interactive",
                "place_order",
                exchangeSegment=self.exchange_segment,
                exchangeInstrumentID=int(symbol),
                productType="NRML",
                orderType=xts_order_type,
                orderSide=xts_side,
                timeInForce="DAY",
                disclosedQuantity=0,
                orderQuantity=quantity,
                limitPrice=price if xts_order_type != "Market" else 0,
                stopPrice=0,
                orderUniqueIdentifier="LIVE-TRADE"
            )

            if response and response.get("type") == "success":
                result = response.get("result", {})
                app_order_id = result.get("AppOrderID")
                logger.info(f"[LIVE API] Order successfully placed. AppOrderID: {app_order_id}")
                return {
                    "order_id": str(app_order_id),
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "status": "PENDING",
                    "timestamp": now,
                }
            else:
                logger.error(f"[LIVE API] Failed to place order. Response: {response}")
                return {
                    "order_id": "",
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "status": "REJECTED",
                    "timestamp": now,
                }
        except Exception as e:
            logger.error(f"[LIVE API] Exception placing order: {e}")
            return {
                "order_id": "",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": "REJECTED",
                "timestamp": now,
            }

    def cancel_order(self, order_id: str) -> bool:
        try:
            response = XtsSessionManager.call_api(
                "interactive",
                "cancel_order",
                appOrderID=int(order_id),
                orderUniqueIdentifier="LIVE-TRADE-CANCEL",
            )
            if response and response.get("type") == "success":
                logger.info(f"[LIVE API] cancel_order(appOrderID={order_id}) → Success")
                return True
            logger.warning(f"[LIVE API] Cancel order failed. Response: {response}")
            return False
        except Exception as e:
            logger.error(f"[LIVE API] Exception cancelling order {order_id}: {e}")
            return False

    def get_order_status(self, order_id: str) -> dict:
        """
        Queries order history via actual XTS API.
        Returns normalized {status, price, quantity}.
        """
        logger.info(f"[LIVE API] get_order_history(appOrderID={order_id})")
        if not order_id:
            return {"status": "UNKNOWN", "price": 0, "quantity": 0}

        try:
            response = XtsSessionManager.call_api(
                "interactive",
                "get_order_history",
                appOrderID=int(order_id)
            )

            if not response or response.get("type") != "success":
                logger.error(f"[LIVE API] Failed to fetch order history for {order_id}: {response}")
                return {"status": "UNKNOWN", "price": 0, "quantity": 0}

            trail = response.get("result", [])
            if not trail:
                return {"status": "UNKNOWN", "price": 0, "quantity": 0}

            # The final state is typically the last element in the trail
            final = trail[-1]
            raw_status = final.get("OrderStatus", "Unknown")
            status = "FILLED" if raw_status == "Filled" else raw_status.upper()

            result = {
                "status": status,
                "price": final.get("OrderAverageTradedPrice", 0),
                "quantity": final.get("CumulativeQuantity", 0),
            }

            logger.info(
                f"[LIVE API] Response parsed. Final Status: {raw_status}, "
                f"AvgPrice: {result['price']}, CumQty: {result['quantity']}"
            )

            return result

        except Exception as e:
            logger.error(f"[LIVE API] Exception fetching order status for {order_id}: {e}")
            return {"status": "UNKNOWN", "price": 0, "quantity": 0}

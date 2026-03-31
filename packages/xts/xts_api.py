"""
xts_api.py: API wrapper for XTS Connect REST APIs.
"""

import json
from typing import ClassVar, Any
from urllib import parse

import requests
import urllib3

from packages.settings import settings
from packages.utils.log_utils import setup_logger

from . import xts_exception as ex

# Suppress InsecureRequestWarning globally as SSL verification is often disabled for XTS
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = setup_logger(__name__)


class XtsCommon:
    """
    Base variables class
    """

    def __init__(self, token=None, user_id=None, is_investor_client=None):
        """Initialize the common variables."""
        self.token = token
        self.user_id = user_id
        self.is_investor_client = is_investor_client


class XtsApi(XtsCommon):
    """
    The XTS Connect API wrapper class.
    In production, you may initialise a single instance of this class per `api_key`.
    """

    # Get the configurations from settings
    _default_root_uri = settings.XTS_ROOT_URL
    _default_login_uri = _default_root_uri + "/user/session"
    _default_timeout = 7  # In seconds

    # SSL Flag
    _ssl_flag = bool(settings.XTS_DISABLE_SSL)

    # Constants
    # Products
    PRODUCT_MIS = "MIS"
    PRODUCT_NRML = "NRML"

    # Order types
    ORDER_TYPE_MARKET = "MARKET"
    ORDER_TYPE_LIMIT = "LIMIT"
    ORDER_TYPE_STOPMARKET = "STOPMARKET"
    ORDER_TYPE_STOPLIMIT = "STOPLIMIT"

    # Transaction type
    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"

    # Squareoff mode
    SQUAREOFF_DAYWISE = "DayWise"
    SQUAREOFF_NETWISE = "Netwise"

    # Squareoff position quantity types
    SQUAREOFFQUANTITY_EXACTQUANTITY = "ExactQty"
    SQUAREOFFQUANTITY_PERCENTAGE = "Percentage"

    # Validity
    VALIDITY_DAY = "DAY"

    # Exchange Segments
    EXCHANGE_NSECM = "NSECM"
    EXCHANGE_NSEFO = "NSEFO"
    EXCHANGE_NSECD = "NSECD"
    EXCHANGE_MCXFO = "MCXFO"
    EXCHANGE_BSECM = "BSECM"
    EXCHANGE_BSEFO = "BSEFO"

    # URIs to various calls
    _routes: ClassVar[dict[str, str]] = {
        # Interactive API endpoints
        "interactive.prefix": "interactive",
        "user.login": "/interactive/user/session",
        "user.logout": "/interactive/user/session",
        "user.profile": "/interactive/user/profile",
        "user.balance": "/interactive/user/balance",
        "orders": "/interactive/orders",
        "trades": "/interactive/orders/trades",
        "order.status": "/interactive/orders",
        "order.place": "/interactive/orders",
        "bracketorder.place": "/interactive/orders/bracket",
        "bracketorder.modify": "/interactive/orders/bracket",
        "bracketorder.cancel": "/interactive/orders/bracket",
        "order.place.cover": "/interactive/orders/cover",
        "order.exit.cover": "/interactive/orders/cover",
        "order.modify": "/interactive/orders",
        "order.cancel": "/interactive/orders",
        "order.cancelall": "/interactive/orders/cancelall",
        "order.history": "/interactive/orders",
        "portfolio.positions": "/interactive/portfolio/positions",
        "portfolio.holdings": "/interactive/portfolio/holdings",
        "portfolio.positions.convert": "/interactive/portfolio/positions/convert",
        "portfolio.squareoff": "/interactive/portfolio/squareoff",
        "portfolio.dealerpositions": "interactive/portfolio/dealerpositions",
        "order.dealer.status": "/interactive/orders/dealerorderbook",
        "dealer.trades": "/interactive/orders/dealertradebook",
        # Market API endpoints
        "marketdata.prefix": "apimarketdata",
        "market.login": "/apimarketdata/auth/login",
        "market.logout": "/apimarketdata/auth/logout",
        "market.config": "/apimarketdata/config/clientConfig",
        "market.instruments.master": "/apimarketdata/instruments/master",
        "market.instruments.subscription": "/apimarketdata/instruments/subscription",
        "market.instruments.unsubscription": "/apimarketdata/instruments/subscription",
        "market.instruments.ohlc": "/apimarketdata/instruments/ohlc",
        "market.instruments.indexlist": "/apimarketdata/instruments/indexlist",
        "market.instruments.quotes": "/apimarketdata/instruments/quotes",
        "market.search.instrumentsbyid": "/apimarketdata/search/instrumentsbyid",
        "market.search.instrumentsbystring": "/apimarketdata/search/instruments",
        "market.instruments.instrument.series": "/apimarketdata/instruments/instrument/series",
        "market.instruments.instrument.equitysymbol": "/apimarketdata/instruments/instrument/symbol",
        "market.instruments.instrument.futuresymbol": "/apimarketdata/instruments/instrument/futureSymbol",
        "market.instruments.instrument.optionsymbol": "/apimarketdata/instruments/instrument/optionsymbol",
        "market.instruments.instrument.optiontype": "/apimarketdata/instruments/instrument/optionType",
        "market.instruments.instrument.expirydate": "/apimarketdata/instruments/instrument/expiryDate",
    }

    def __init__(
        self, api_key, secret_key, source, root=None, debug=False, timeout=None, pool=None, disable_ssl=_ssl_flag
    ):
        """
        Initialise a new XTS Connect client instance.

        - `api_key` is the key issued to you
        - `token` is the token obtained after the login flow. Pre-login, this will default to None,
        but once you have obtained it, you should persist it in a database or session to pass
        to the XTS Connect class initialisation for subsequent requests.
        - `root` is the API end point root. Unless you explicitly
        want to send API requests to a non-default endpoint, this
        can be ignored.
        - `debug`, if set to True, will serialise and print requests
        and responses to stdout.
        - `timeout` is the time (seconds) for which the API client will wait for
        a request to complete before it fails. Defaults to 7 seconds
        - `pool` is manages request pools. It takes a dict of params accepted by HTTPAdapter
        - `disable_ssl` disables the SSL verification while making a request.
        If set requests won't throw SSLError if its set to custom `root` url without SSL.
        """
        self.debug = debug
        self.api_key = api_key
        self.secret_key = secret_key
        self.source = source
        self.disable_ssl = disable_ssl
        self.root = root or self._default_root_uri
        self.timeout = timeout or self._default_timeout

        super().__init__()

        # Create requests session only if pool exists. Reuse session
        # for every request. Otherwise create session for each request
        if pool:
            self.reqsession = requests.Session()
            reqadapter = requests.adapters.HTTPAdapter(**pool)
            self.reqsession.mount("https://", reqadapter)
        else:
            self.reqsession = requests

        # disable requests SSL warning
        requests.packages.urllib3.disable_warnings()

    def _set_common_variables(self, access_token, user_id, is_investor_client):
        """Set the `access_token` received after a successful authentication."""
        super().__init__(access_token, user_id, is_investor_client)

    def _login_url(self):
        """Get the remote login url to which a user should be redirected to initiate the login flow."""
        return self._default_login_uri

    def interactive_login(self) -> dict[str, Any] | str:
        """Send the login url to which a user should receive the token."""
        response = None
        try:
            params = {"appKey": self.api_key, "secretKey": self.secret_key, "source": self.source}
            response = self._post("user.login", json.dumps(params))

            if response and isinstance(response, dict) and "token" in response.get("result", {}):
                self._set_common_variables(
                    response["result"]["token"], response["result"]["userID"], response["result"]["isInvestorClient"]
                )
            return response
        except Exception as e:
            return response.get("description", str(e)) if isinstance(response, dict) else str(e)

    def get_order_book(self, client_id: str | None = None) -> dict[str, Any]:
        """Request Order book gives states of all the orders placed by an user"""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("order.status", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_dealer_orderbook(self, client_id=None):
        """Request Order book gives states of all the orders placed by an user"""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("order.dealer.status", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def place_order(
        self,
        exchange_segment: int | str,
        exchange_instrument_id: int | str,
        product_type: str,
        order_type: str,
        order_side: str,
        time_in_force: str,
        disclosed_quantity: int,
        order_quantity: int,
        limit_price: float,
        stop_price: float,
        order_unique_identifier: str,
        api_order_source: str,
        client_id: str | None = None,
    ) -> dict[str, Any]:
        """To place an order"""
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "productType": product_type,
                "orderType": order_type,
                "orderSide": order_side,
                "timeInForce": time_in_force,
                "disclosedQuantity": disclosed_quantity,
                "orderQuantity": order_quantity,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
                "apiOrderSource": api_order_source,
                "orderUniqueIdentifier": order_unique_identifier,
            }

            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._post("order.place", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def modify_order(
        self,
        app_order_id,
        modified_product_type,
        modified_order_type,
        modified_order_quantity,
        modified_disclosed_quantity,
        modified_limit_price,
        modified_stop_price,
        modified_time_in_force,
        order_unique_identifier,
        client_id=None,
    ):
        """The facility to modify your open orders by allowing you to change limit order to market or vice versa,
        change Price or Quantity of the limit open order, change disclosed quantity or stop-loss of any
        open stop loss order."""
        try:
            app_order_id = int(app_order_id)
            params = {
                "appOrderID": app_order_id,
                "modifiedProductType": modified_product_type,
                "modifiedOrderType": modified_order_type,
                "modifiedOrderQuantity": modified_order_quantity,
                "modifiedDisclosedQuantity": modified_disclosed_quantity,
                "modifiedLimitPrice": modified_limit_price,
                "modifiedStopPrice": modified_stop_price,
                "modifiedTimeInForce": modified_time_in_force,
                "orderUniqueIdentifier": order_unique_identifier,
            }

            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._put("order.modify", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def place_bracketorder(
        self,
        exchange_segment,
        exchange_instrument_id,
        order_type,
        order_side,
        disclosed_quantity,
        order_quantity,
        limit_price,
        square_off,
        stop_loss_price,
        trailing_stop_loss,
        is_pro_order,
        api_order_source,
        order_unique_identifier,
    ):
        """To place a bracketorder"""
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "orderType": order_type,
                "orderSide": order_side,
                "disclosedQuantity": disclosed_quantity,
                "orderQuantity": order_quantity,
                "limitPrice": limit_price,
                "squarOff": square_off,
                "stopLossPrice": stop_loss_price,
                "trailingStoploss": trailing_stop_loss,
                "isProOrder": is_pro_order,
                "apiOrderSource": api_order_source,
                "orderUniqueIdentifier": order_unique_identifier,
            }
            response = self._post("bracketorder.place", json.dumps(params))
            logger.info(response)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def bracketorder_cancel(self, app_order_id, client_id=None):
        """This API can be called to cancel any open order of the user by providing correct appOrderID matching with
        the chosen open order to cancel."""
        try:
            params = {"boEntryOrderId": int(app_order_id)}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._delete("bracketorder.cancel", params)
            return response
        except Exception:
            return response["description"]

    def modify_bracketorder(self, app_order_id, order_quantity, limit_price, stop_price, client_id=None):
        try:
            app_order_id = int(app_order_id)
            params = {
                "appOrderID": app_order_id,
                "bracketorder.modify": order_quantity,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
            }

            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._put("bracketorder.modify", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def place_cover_order(
        self,
        exchange_segment,
        exchange_instrument_id,
        order_side,
        order_type,
        order_quantity,
        disclosed_quantity,
        limit_price,
        stop_price,
        api_order_source,
        order_unique_identifier,
        client_id=None,
    ):
        """A Cover Order is an advance intraday order that is accompanied by a compulsory Stop Loss Order. This helps
        users to minimize their losses by safeguarding themselves from unexpected market movements. A Cover Order
        offers high leverage and is available in Equity Cash, Equity F&O, Commodity F&O and Currency F&O segments. It
        has 2 orders embedded in itself, they are Limit/Market Order Stop Loss Order"""
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "orderSide": order_side,
                "orderType": order_type,
                "orderQuantity": order_quantity,
                "disclosedQuantity": disclosed_quantity,
                "limitPrice": limit_price,
                "stopPrice": stop_price,
                "apiOrderSource": api_order_source,
                "orderUniqueIdentifier": order_unique_identifier,
            }
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._post("order.place.cover", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def exit_cover_order(self, app_order_id, client_id=None):
        """Exit Cover API is a functionality to enable user to easily exit an open stoploss order by converting it
        into Exit order."""
        try:
            params = {"appOrderID": app_order_id}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._put("order.exit.cover", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_profile(self, client_id=None):
        """Using session token user can access his profile stored with the broker, it's possible to retrieve it any
        point of time with the http: //ip:port/interactive/user/profile API."""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._get("user.profile", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_balance(self, client_id=None):
        """Get Balance API call grouped under this category information related to limits on equities, derivative,
        upfront margin, available exposure and other RMS related balances available to the user."""
        if self.is_investor_client:
            try:
                params = {}
                if not self.is_investor_client:
                    params["clientID"] = client_id
                response = self._get("user.balance", params)
                return response
            except Exception:
                return response["description"]
        else:
            logger.info(
                "Balance API available for retail API users only, dealers can watch the same on dealer terminal"
            )

    def get_trade(self, client_id=None):
        """Trade book returns a list of all trades executed on a particular day , that were placed by the user . The
        trade book will display all filled and partially filled orders."""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("trades", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_dealer_tradebook(self, client_id=None):
        """Trade book returns a list of all trades executed on a particular day , that were placed by the user . The
        trade book will display all filled and partially filled orders."""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("dealer.trades", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_holding(self, client_id=None):
        """Holdings API call enable users to check their long term holdings with the broker."""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._get("portfolio.holdings", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_dealerposition_netwise(self, client_id=None):
        """The positions API positions by net. Net is the actual, current net position portfolio."""
        try:
            params = {"dayOrNet": "NetWise"}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("portfolio.dealerpositions", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_dealerposition_daywise(self, client_id=None):
        """The positions API returns positions by day, which is a snapshot of the buying and selling activity for
        that particular day."""
        try:
            params = {"dayOrNet": "DayWise"}
            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._get("portfolio.dealerpositions", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_position_daywise(self, client_id=None):
        """The positions API returns positions by day, which is a snapshot of the buying and selling activity for
        that particular day."""
        try:
            params = {"dayOrNet": "DayWise"}
            if not self.is_investor_client:
                params["clientID"] = client_id

            response = self._get("portfolio.positions", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_position_netwise(self, client_id=None):
        """The positions API positions by net. Net is the actual, current net position portfolio."""
        try:
            params = {"dayOrNet": "NetWise"}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("portfolio.positions", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def convert_position(
        self,
        exchange_segment,
        exchange_instrument_id,
        target_qty,
        is_day_wise,
        old_product_type,
        new_product_type,
        client_id=None,
    ):
        """Convert position API, enable users to convert their open positions from NRML intra-day to Short term MIS or
        vice versa, provided that there is sufficient margin or funds in the account to effect such conversion"""
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "targetQty": target_qty,
                "isDayWise": is_day_wise,
                "oldProductType": old_product_type,
                "newProductType": new_product_type,
            }
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._put("portfolio.positions.convert", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def cancel_order(self, app_order_id: int | str, order_unique_identifier: str, client_id: str | None = None) -> dict[str, Any]:
        """This API can be called to cancel any open order of the user by providing correct appOrderID matching with
        the chosen open order to cancel."""
        try:
            params = {"appOrderID": int(app_order_id), "orderUniqueIdentifier": order_unique_identifier}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._delete("order.cancel", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def cancelall_order(self, exchange_segment, exchange_instrument_id):
        """This API can be called to cancel all open order of the user by providing exchange segment and exchange instrument ID"""
        try:
            params = {"exchangeSegment": exchange_segment, "exchangeInstrumentID": exchange_instrument_id}
            if not self.is_investor_client:
                params["clientID"] = self.user_id
            response = self._post("order.cancelall", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def squareoff_position(
        self,
        exchange_segment,
        exchange_instrument_id,
        product_type,
        square_off_mode,
        position_square_off_quantity_type,
        square_off_qty_value,
        block_order_sending,
        cancel_orders,
        client_id=None,
    ):
        """User can request square off to close all his positions in Equities, Futures and Option. Users are advised
        to use this request with caution if one has short term holdings."""
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "productType": product_type,
                "squareoffMode": square_off_mode,
                "positionSquareOffQuantityType": position_square_off_quantity_type,
                "squareOffQtyValue": square_off_qty_value,
                "blockOrderSending": block_order_sending,
                "cancelOrders": cancel_orders,
            }
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._put("portfolio.squareoff", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_order_history(self, app_order_id, client_id=None):
        """Order history will provide particular order trail chain. This indicate the particular order & its state
        changes. i.e.Pending New to New, New to PartiallyFilled, PartiallyFilled, PartiallyFilled & PartiallyFilled
        to Filled etc"""
        try:
            params = {"appOrderID": app_order_id}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._get("order.history", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def interactive_logout(self, client_id=None):
        """This call invalidates the session token and destroys the API session. After this, the user should go
        through login flow again and extract session token from login response before further activities."""
        try:
            params = {}
            if not self.is_investor_client:
                params["clientID"] = client_id
            response = self._delete("user.logout", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    ########################################################################################################
    # Market data API
    ########################################################################################################

    def marketdata_login(self) -> dict[str, Any] | str:
        response = None
        try:
            params = {"appKey": self.api_key, "secretKey": self.secret_key, "source": self.source}
            response = self._post("market.login", json.dumps(params))

            if response and isinstance(response, dict) and "token" in response.get("result", {}):
                self._set_common_variables(response["result"]["token"], response["result"]["userID"], False)
            return response
        except Exception as e:
            return response.get("description", str(e)) if isinstance(response, dict) else str(e)

    def get_config(self):
        try:
            params = {}
            response = self._get("market.config", params)
            return response
        except Exception as e:
            return str(e)

    def get_quote(self, instruments, xts_message_code, publish_format):
        try:
            params = {"instruments": instruments, "xtsMessageCode": xts_message_code, "publishFormat": publish_format}
            response = self._post("market.instruments.quotes", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def send_subscription(self, instruments: list[dict[str, Any]], xts_message_code: int) -> dict[str, Any]:
        try:
            params = {"instruments": instruments, "xtsMessageCode": xts_message_code}
            response = self._post("market.instruments.subscription", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def send_unsubscription(self, instruments, xts_message_code):
        try:
            params = {"instruments": instruments, "xtsMessageCode": xts_message_code}
            response = self._put("market.instruments.unsubscription", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_master(self, exchange_segment_list):
        try:
            params = {"exchangeSegmentList": exchange_segment_list}
            response = self._post("market.instruments.master", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_ohlc(self, exchange_segment: int | str, exchange_instrument_id: int | str, start_time: str, end_time: str, compression_value: int) -> dict[str, Any]:
        response: dict[str, Any] | None = None
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "exchangeInstrumentID": exchange_instrument_id,
                "startTime": start_time,
                "endTime": end_time,
                "compressionValue": compression_value,
            }
            response = self._get("market.instruments.ohlc", params)
            return response
        except Exception as e:
            return {"type": "error", "description": response["description"] if response else str(e)}

    def get_series(self, exchange_segment):
        try:
            params = {"exchangeSegment": exchange_segment}
            response = self._get("market.instruments.instrument.series", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_equity_symbol(self, exchange_segment, series, symbol):
        try:
            params = {"exchangeSegment": exchange_segment, "series": series, "symbol": symbol}
            response = self._get("market.instruments.instrument.equitysymbol", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_expiry_date(self, exchange_segment, series, symbol):
        try:
            params = {"exchangeSegment": exchange_segment, "series": series, "symbol": symbol}
            response = self._get("market.instruments.instrument.expirydate", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_future_symbol(self, exchange_segment, series, symbol, expiry_date):
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "series": series,
                "symbol": symbol,
                "expiryDate": expiry_date,
            }
            response = self._get("market.instruments.instrument.futuresymbol", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_option_symbol(self, exchange_segment, series, symbol, expiry_date, option_type, strike_price):
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "series": series,
                "symbol": symbol,
                "expiryDate": expiry_date,
                "optionType": option_type,
                "strikePrice": strike_price,
            }
            response = self._get("market.instruments.instrument.optionsymbol", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_option_type(self, exchange_segment, series, symbol, expiry_date):
        try:
            params = {
                "exchangeSegment": exchange_segment,
                "series": series,
                "symbol": symbol,
                "expiryDate": expiry_date,
            }
            response = self._get("market.instruments.instrument.optiontype", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def get_index_list(self, exchange_segment):
        try:
            params = {"exchangeSegment": exchange_segment}
            response = self._get("market.instruments.indexlist", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def search_by_instrumentid(self, instruments):
        try:
            params = {"source": self.source, "instruments": instruments}
            response = self._post("market.search.instrumentsbyid", json.dumps(params))
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def search_by_scriptname(self, search_string):
        try:
            params = {"searchString": search_string}
            response = self._get("market.search.instrumentsbystring", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    def marketdata_logout(self):
        try:
            params = {}
            response = self._delete("market.logout", params)
            return response
        except Exception as e:
            return {"type": "error", "description": str(e)}

    ########################################################################################################
    # Common Methods
    ########################################################################################################

    def _get(self, route, params=None):
        """Alias for sending a GET request."""
        return self._request(route, "GET", params)

    def _post(self, route, params=None):
        """Alias for sending a POST request."""
        return self._request(route, "POST", params)

    def _put(self, route, params=None):
        """Alias for sending a PUT request."""
        return self._request(route, "PUT", params)

    def _delete(self, route, params=None):
        """Alias for sending a DELETE request."""
        return self._request(route, "DELETE", params)

    def _request(self, route, method, parameters=None):
        """Make an HTTP request."""
        params = parameters if parameters else {}

        # Form a restful URL
        uri = self._routes[route].format(params)
        url = parse.urljoin(self.root, uri)
        headers = {}

        # Always set content-type for POST/PUT if data is provided
        if method in ["POST", "PUT"]:
            headers.update({"Content-Type": "application/json"})

        if self.token:
            # set authorization header
            headers.update({"Authorization": self.token})

        try:
            r = self.reqsession.request(
                method,
                url,
                data=params if method in ["POST", "PUT"] else None,
                params=params if method in ["GET", "DELETE"] else None,
                headers=headers,
                verify=not self.disable_ssl,
            )

        except Exception as e:
            raise e

        if self.debug:
            logger.debug(f"Response: {r.status_code} {r.content}")


        # Validate the content type.
        if "json" in r.headers["content-type"]:
            try:
                data = json.loads(r.content.decode("utf8"))
            except ValueError as e:
                raise ex.XTSDataException(
                    f"Couldn't parse the JSON response received from the server: {r.content}"
                ) from e


            # api error
            if data.get("type"):
                if r.status_code == 400 and data["type"] == "error" and data["description"] == "Invalid Token":
                    raise ex.XTSTokenException(data["description"])

                if r.status_code == 400 and data["type"] == "error" and data["description"] == "Bad Request":
                    message = "Description: " + data["description"] + " errors: " + str(data["result"]["errors"])
                    raise ex.XTSInputException(str(message))

            return data
        else:
            raise ex.XTSDataException(
                "Unknown Content-Type ({content_type}) with response: ({content})".format(
                    content_type=r.headers["content-type"], content=r.content
                )
            )

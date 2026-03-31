(
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """
                Here we have declared all the exception and responses
    If there is any exception occurred we have this code to convey the messages
"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
    """"""
)


class XtsException(Exception):
    """
    Base exception class representing a XTS client exception.

    Every specific XTS client exception is a subclass of this
    and  exposes two instance variables `.code` (HTTP error code)
    and `.message` (error text).
    """

    def __init__(self, message, code=500):
        """Initialize the exception."""
        super().__init__(message)
        self.code = code


class XtsGeneralException(XtsException):
    """An unclassified, general error. Default code is 500."""

    def __init__(self, message, code=500):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsTokenException(XtsException):
    """Represents all token and authentication related errors. Default code is 400."""

    def __init__(self, message, code=400):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsPermissionException(XtsException):
    """Represents permission denied exceptions for certain calls. Default code is 400."""

    def __init__(self, message, code=400):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsOrderException(XtsException):
    """Represents all order placement and manipulation errors. Default code is 500."""

    def __init__(self, message, code=400):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsInputException(XtsException):
    """Represents user input errors such as missing and invalid parameters. Default code is 400."""

    def __init__(self, message, code=400):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsDataException(XtsException):
    """Represents a bad response from the backend Order Management System (OMS). Default code is 500."""

    def __init__(self, message, code=500):
        """Initialize the exception."""
        super().__init__(message, code)


class XtsNetworkException(XtsException):
    """Represents a network issue between XTS and the backend Order Management System (OMS). Default code is 500."""

    def __init__(self, message, code=500):
        """Initialize the exception."""
        super().__init__(message, code)

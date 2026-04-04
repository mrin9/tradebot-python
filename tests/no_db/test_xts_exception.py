"""Unit tests for XTS exception hierarchy — pure logic, no DB."""

from packages.xts.xts_exception import (
    XtsException,
    XtsGeneralException,
    XtsTokenException,
    XtsPermissionException,
    XtsOrderException,
    XtsInputException,
    XtsDataException,
    XtsNetworkException,
)


class TestXtsExceptionHierarchy:
    def test_base_exception(self):
        """XtsException is the base with code 500."""
        ex = XtsException("test error")
        assert str(ex) == "test error"
        assert isinstance(ex, Exception)

    def test_all_subclasses(self):
        """All exception types are subclasses of XtsException."""
        for cls in [
            XtsGeneralException,
            XtsTokenException,
            XtsPermissionException,
            XtsOrderException,
            XtsInputException,
            XtsDataException,
            XtsNetworkException,
        ]:
            ex = cls("msg")
            assert isinstance(ex, XtsException)

    def test_token_exception_catchable_as_base(self):
        """XtsTokenException can be caught as XtsException."""
        try:
            raise XtsTokenException("invalid token")
        except XtsException as e:
            assert "invalid token" in str(e)

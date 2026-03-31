from datetime import datetime
from unittest.mock import MagicMock, patch

from packages.data.data_gaps import _generate_diagnostic_report


def test_diagnostic_report_no_data():
    """Verifies report generation when no data exists in DB."""
    mock_db = MagicMock()
    # Mock count_documents to return 0 for everything
    mock_db[MagicMock()].count_documents.return_value = 0
    # Mock aggregate for options
    mock_db[MagicMock()].aggregate.return_value = []

    with (
        patch("packages.utils.mongo.MongoRepository.get_db", return_value=mock_db),
        patch("packages.services.contract_discovery.ContractDiscoveryService.derive_target_contracts", return_value=[]),
    ):
        s_dt = datetime(2026, 3, 1)
        e_dt = datetime(2026, 3, 2)
        report = _generate_diagnostic_report(s_dt, e_dt, strike_count=0)

        assert len(report) == 2
        assert report[0]["status"] == "NO DATA"
        assert report[0]["nifty_count"] == 0


def test_diagnostic_report_partial_data():
    """Verifies report correctly identifies partial data."""
    mock_db = MagicMock()

    # NIFTY count 375 (full), but options missing
    def mock_count(filter_obj):
        if filter_obj.get("i") == "INDEX_ID":  # replace with actual if needed or mock selectively
            return 375
        return 0

    mock_db[MagicMock()].count_documents.side_effect = lambda f: 375 if "26000" in str(f) else 0

    # Mock specific return for options aggregate
    mock_db[MagicMock()].aggregate.return_value = [
        {"_id": 1001, "count": 200}  # partial count
    ]

    with (
        patch("packages.utils.mongo.MongoRepository.get_db", return_value=mock_db),
        patch("packages.services.contract_discovery.ContractDiscoveryService.derive_target_contracts") as m_derive,
    ):
        m_derive.return_value = [{"exchangeInstrumentID": 1001, "contractExpiration": "2026-03-12"}]

        s_dt = datetime(2026, 3, 1)
        report = _generate_diagnostic_report(s_dt, s_dt, strike_count=0)

        assert len(report) == 1
        assert report[0]["status"] == "PARTIAL"
        assert len(report[0]["missing_contracts"]) == 1

from datetime import datetime
from unittest.mock import MagicMock

from packages.utils.date_utils import DateUtils


def test_xts_epoch_baselines():
    """
    Verifies the discovery that XTS REST and Socket/Live use different baselines.
    1970 (Unix) vs 1980 (XTS Socket).
    """
    # 1. Standard Unix timestamp for Mar 05 2026 11:49:57 IST
    unix_2026 = 1772711099

    # 2. XTS Socket/Quote timestamp for the same moment (10 years earlier)
    # January 1, 1980 is 315,532,800 seconds after January 1, 1970
    xts_socket_2016 = 1457178299

    # --- TEST 1: REST API BASELINE ---
    # REST History API consumes 1970-base but our DateUtils.from_timestamp
    # should interpret it correctly without any offset.
    rest_dt = datetime.fromtimestamp(unix_2026)
    print(f"\nREST Baseline (1970): {rest_dt}")
    assert rest_dt.year == 2026

    # --- TEST 2: SOCKET/LIVE BASELINE ---
    # DateUtils.xts_epoch_to_utc should detect the 1980-base and boost it to 1970-base (2026)
    # XTS IST-shifted epoch usually also includes 19800s (5.5h) which xts_epoch_to_utc handles.

    # Let's test the raw adjustment logic in DateUtils
    normalized_utc = DateUtils.socket_timestamp_to_utc(xts_socket_2016)

    # Interpretation:
    # xts_socket_2016 + 315532800 (Epoch shift) - 19800 (IST to UTC shift)
    # 1457178299 + 315532800 - 19800 = 1772691299 (UTC)

    final_dt = datetime.fromtimestamp(normalized_utc + 19800)  # Add back IST for display check
    print(f"Socket Baseline (1980) Normalized: {final_dt}")

    assert final_dt.year == 2026
    assert final_dt.month == 3
    assert final_dt.day == 5


def test_socket_data_provider_emulation():
    """
    Verifies that our Simulator/SocketDataProvider correctly emulates the 1980 epoch
    offset by SUBTRACTING 10 years when emitting data.
    """
    # Create a mock for SocketIO server
    from packages.simulator.socket_data_provider import SocketDataProvider

    mock_sio = MagicMock()
    provider = SocketDataProvider(mock_sio)

    # Pure Unix 2026 timestamp
    unix_2026 = 1772711099

    # The provider should subtract 10 years (315532800) to mimic XTS production
    # and add 19800 if it was pure UTC (the provider receives pure UTC from DB)
    xts_ts = provider._get_xts_timestamp(unix_2026)

    # Calculation: unix_2026 + 19800 - 315532800
    expected_xts = unix_2026 + 19800 - 315532800

    assert xts_ts == expected_xts

    # If we interpret this result using standard Unix (1970), it must look like 2016
    interpreted_dt = datetime.fromtimestamp(xts_ts)
    print(f"Emulated Socket Timestamp (1980-base): {interpreted_dt}")
    assert interpreted_dt.year == 2016


if __name__ == "__main__":
    test_xts_epoch_baselines()
    test_socket_data_provider_emulation()
    print("\n✅ XTS Epoch Calibration Tests Passed!")

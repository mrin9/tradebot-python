import os
import sys

import pytest

from packages.settings import settings

# Ensure the project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

# Suppress noisy app logs during tests
os.environ["TESTING_ENV"] = "true"

# Standardize Default Test Database (Safety First)
settings.DB_NAME = "tradebot_test"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    """
    1. Sets up environment-specific isolation.
    2. Enforces NO-DB policy for 'tests/no_db/'.
    3. Prints a beautiful header with context-aware metadata.
    """
    from packages.utils.mongo import MongoRepository
    import packages.utils.mongo as mongo_module

    # 1. Default DB Setup
    settings.DB_NAME = "tradebot_test"
    MongoRepository.close()

    # 2. Save the REAL get_db once (before any patching)
    if not hasattr(mongo_module, "_original_get_db"):
        mongo_module._original_get_db = mongo_module.MongoRepository.get_db

    # 3. Isolation Enforcement (The 'Safety Net')
    test_path = str(item.fspath)
    is_no_db = "tests/no_db/" in test_path

    if is_no_db:
        def forbidden_get_db(*args, **kwargs):
            raise RuntimeError(
                f"❌ ACCESS DENIED: Test '{item.name}' is in 'tests/no_db/' "
                " but attempted to access MongoDB! Isolation breach detected."
            )

        mongo_module.MongoRepository.get_db = forbidden_get_db
        mongo_module.get_db = forbidden_get_db

    yield  # Execute fixtures and test

    # 4. Always restore the REAL get_db after no_db tests
    if is_no_db:
        mongo_module.MongoRepository.get_db = mongo_module._original_get_db
        mongo_module.get_db = mongo_module._original_get_db

    # 4. Reporting Header
    db_name = getattr(settings, "DB_NAME", "UNKNOWN")
    try:
        nifty_col = settings.NIFTY_CANDLE_COLLECTION
    except Exception:
        nifty_col = "UNKNOWN"

    # Context Logic
    if is_no_db:
        env_info = "🏢 ENV: NO-DB (Strict Isolation)"
    elif "tests/xts/" in test_path or "tests/read_db/" in test_path:
        env_info = f"⚡ SOURCE: XTS-LIVE/SOCKET | 🗄️ DB: {db_name}"
    else:
        env_info = f"🗄️ DATABASE: {db_name} | COLLECTION: {nifty_col}"

    # Docstring Extraction
    test_doc = item.obj.__doc__ or "No description provided"
    test_desc = test_doc.strip().split("\n")[0]

    print(f"\n{'=' * 80}")
    print(f"🔍 TESTING: {test_desc}")
    print(f"{env_info}")
    print(f"🆔 ID: {item.nodeid}")
    print(f"{'=' * 80}")


def pytest_runtest_teardown(item, nextitem):
    """Add a line gap after the test result for better readability."""
    print("\n")

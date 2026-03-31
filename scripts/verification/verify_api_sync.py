
import requests

BASE_URL = "http://localhost:8000"


def test_status():
    print("\n--- Testing /api/status ---")
    try:
        resp = requests.get(f"{BASE_URL}/api/status")
        print(f"Status: {resp.status_code}")
        print(resp.json())
    except Exception as e:
        print(f"Error: {e}")


def test_instruments():
    print("\n--- Testing /api/instruments ---")
    try:
        resp = requests.get(f"{BASE_URL}/api/instruments")
        print(f"Status: {resp.status_code}")
        data = resp.json()
        print(f"Count: {len(data)}")
        if data:
            print(f"First result keys: {list(data[0].keys())}")
            print(f"Reference Date Example: {data[0].get('referenceDate')}")
    except Exception as e:
        print(f"Error: {e}")


def test_ticks():
    print("\n--- Testing /api/ticks ---")
    try:
        # Assuming we have some data for nifty index 26000
        params = {"id": "26000", "candle-interval": "1m", "limit": 10}
        resp = requests.get(f"{BASE_URL}/api/ticks", params=params)
        print(f"Status: {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict):
            print(f"Keys: {list(data.keys())}")
            print(f"Ticks Count: {len(data.get('ticks', []))}")
            print(f"hasMoreOld: {data.get('hasMoreOld')}")
            print(f"hasMoreNew: {data.get('hasMoreNew')}")
        else:
            print(f"Unexpected response type: {type(data)}")
    except Exception as e:
        print(f"Error: {e}")


def test_ops():
    print("\n--- Testing /api/ops/indicators/update ---")
    try:
        resp = requests.post(f"{BASE_URL}/api/ops/indicators/update")
        print(f"Status: {resp.status_code}")
        print(resp.json())
    except Exception as e:
        print(f"Error: {e}")


def test_strategy_reset():
    print("\n--- Testing /api/strategy-rules/reset ---")
    try:
        resp = requests.post(f"{BASE_URL}/api/strategy-rules/reset")
        print(f"Status: {resp.status_code}")
        print(resp.json())
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_status()
    test_instruments()
    test_ticks()
    test_ops()
    test_strategy_reset()

from datetime import datetime, timezone

import requests

BASE_URL = "http://localhost:8000"


def test_auto_shift():
    print("\n--- Testing Auto-Window Shifting ---")
    # This range starts after Friday market close
    params = {
        "id": "26000",
        "start-dt": "2026-02-20T22:55:00.000Z",
        "end-dt": "2026-02-21T07:15:00.000Z",
        "candle-interval": "1m",
        "skip-metadata": "false",
    }
    try:
        resp = requests.get(f"{BASE_URL}/api/ticks", params=params)
        print(f"Status: {resp.status_code}")
        data = resp.json()
        if isinstance(data, dict):
            ticks = data.get("ticks", [])
            print(f"Ticks Count: {len(ticks)}")
            print(f"hasMoreOld: {data.get('hasMoreOld')}")
            print(f"hasMoreNew: {data.get('hasMoreNew')}")
            if ticks:
                first_t = ticks[0]["t"]
                last_t = ticks[-1]["t"]
                print(f"First Tick UTC: {datetime.fromtimestamp(first_t, timezone.utc)}")
                print(f"Last Tick UTC: {datetime.fromtimestamp(last_t, timezone.utc)}")
        else:
            print(f"Unexpected response type: {type(data)}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    test_auto_shift()

import os

import uvicorn

if __name__ == "__main__":
    # Ensure current directory is in path
    import sys

    sys.path.append(os.getcwd())

    print("Starting Trade Bot API...")
    uvicorn.run("apps.api.main:socket_app", host="0.0.0.0", port=8000, reload=True)

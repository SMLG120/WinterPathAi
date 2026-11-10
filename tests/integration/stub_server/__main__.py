"""Run the STUB API:  uv run python -m stub_server  (from tests/integration).

Binds 127.0.0.1:${STUB_PORT:-8105} (Platform's assigned API port). Logs JSON lines to stdout.
"""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "stub_server.app:app",
        host="127.0.0.1",
        port=int(os.environ.get("STUB_PORT", "8105")),
        access_log=False,  # uvicorn's access log would print raw query strings
        log_level="warning",
    )

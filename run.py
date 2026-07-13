"""Local dev server entrypoint.

On Windows, psycopg async requires SelectorEventLoop. Uvicorn must be started
through this module (not `uvicorn app.main:app` directly) so the policy is set
before the event loop is created.
"""
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=sys.platform != "win32",
    )

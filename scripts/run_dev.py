"""Dev server launcher for Windows.

Why this exists instead of `uvicorn src.main:app --reload ...`: AsyncPostgresSaver (the agent's
persistent memory - the project requires Postgres, no SQLite fallback) needs psycopg's async
mode, which cannot run on Windows' default ProactorEventLoop - it needs SelectorEventLoop.
uvicorn's CLI only takes `--loop auto|asyncio|uvloop`, and on win32 both `auto` and `asyncio`
resolve to ProactorEventLoop before our app even gets imported, so there's no CLI flag that fixes
this. Calling uvicorn.run() directly and passing the loop *class* (not one of those three
strings) sidesteps that: uvicorn only special-cases the string names and returns anything else -
including a class - unchanged.

Usage:
    python scripts/run_dev.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402
from src.config import get_settings  # noqa: E402

if __name__ == "__main__":
    settings = get_settings()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.SelectorEventLoop
    else:
        loop = "auto"
    uvicorn.run(
        "src.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
        loop=loop,
    )

"""Read-only analytics deadlines. Timeouts are unavailable results, never empty data."""
import asyncio
import logging
from contextvars import ContextVar
from fastapi import HTTPException
from pymongo.errors import PyMongoError

import os


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


# Interactive requests answer fast or say "unavailable"; background cache
# rebuilds (after a crawl or sync) may take as long as the data needs. On
# production (~1M snapshots) the rebuild used to run under the 20 s request
# budget, never finished, and every page fell back to a live compute that
# also timed out — the "Price analysis timed out" screen (10-11 Oct 2026).
SNAPSHOT_QUERY_MAX_MS = _env_int("SNAPSHOT_QUERY_MAX_MS", 15000)
REQUEST_TIMEOUT_SECONDS = _env_int("REQUEST_TIMEOUT_SECONDS", 20)
BACKGROUND_SNAPSHOT_QUERY_MAX_MS = _env_int("BACKGROUND_SNAPSHOT_QUERY_MAX_MS", 300000)
BACKGROUND_TIMEOUT_SECONDS = _env_int("BACKGROUND_TIMEOUT_SECONDS", 900)
logger = logging.getLogger(__name__)
_read_budgets = ContextVar("analytics_read_budgets", default=())
_background = ContextVar("analytics_background_read", default=False)


def in_background():
    return _background.get()


def query_max_ms():
    """Per-query maxTimeMS for the current context (request or background)."""
    return BACKGROUND_SNAPSHOT_QUERY_MAX_MS if _background.get() else SNAPSHOT_QUERY_MAX_MS


def read_budget_expired():
    return any(marker["expired"] for marker in _read_budgets.get())


async def close_read_cursor(cursor):
    """Cleanup must not turn a bounded read into another socket-length wait."""
    try:
        await asyncio.wait_for(cursor.close(), timeout=0.5)
    except (TimeoutError, PyMongoError):
        logger.warning("Snapshot cursor cleanup did not complete within its budget")


def unavailable(code):
    return HTTPException(503, detail={
        "code": code, "message": "Price results are temporarily unavailable. Please retry.",
        "retryable": True,
    }, headers={"Retry-After": "5"})


async def bounded_read(operation, background=False):
    """Run `operation` under the request budget, or the background budget when
    `background=True` (cache rebuilds). Nested reads inherit the outer mode."""
    marker = {"expired": False}
    token = _read_budgets.set(_read_budgets.get()+(marker,))
    mode_token = _background.set(background or _background.get())
    timeout = BACKGROUND_TIMEOUT_SECONDS if _background.get() else REQUEST_TIMEOUT_SECONDS
    timer = asyncio.get_running_loop().call_later(timeout, marker.__setitem__, "expired", True)
    try:
        return await asyncio.wait_for(operation, timeout=timeout)
    except (TimeoutError, PyMongoError) as exc:
        code = "price_query_timeout" if isinstance(exc, TimeoutError) or exc.timeout else "price_database_unavailable"
        logger.exception("Price analytics read failed: %s (budget %ss, background=%s)", code, timeout, _background.get())
        raise unavailable(code) from exc
    finally:
        timer.cancel()
        _background.reset(mode_token)
        _read_budgets.reset(token)
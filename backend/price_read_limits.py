"""Read-only analytics deadlines. Timeouts are unavailable results, never empty data."""
import asyncio
import logging
from contextvars import ContextVar
from fastapi import HTTPException
from pymongo.errors import PyMongoError

SNAPSHOT_QUERY_MAX_MS = 15000
REQUEST_TIMEOUT_SECONDS = 20
logger = logging.getLogger(__name__)
_read_budgets = ContextVar("analytics_read_budgets", default=())


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


async def bounded_read(operation):
    marker = {"expired": False}
    token = _read_budgets.set(_read_budgets.get()+(marker,))
    timer = asyncio.get_running_loop().call_later(
        REQUEST_TIMEOUT_SECONDS, marker.__setitem__, "expired", True)
    try:
        return await asyncio.wait_for(operation, timeout=REQUEST_TIMEOUT_SECONDS)
    except (TimeoutError, PyMongoError) as exc:
        code = "price_query_timeout" if isinstance(exc, TimeoutError) or exc.timeout else "price_database_unavailable"
        logger.exception("Price analytics read failed: %s", code)
        raise unavailable(code) from exc
    finally:
        timer.cancel()
        _read_budgets.reset(token)
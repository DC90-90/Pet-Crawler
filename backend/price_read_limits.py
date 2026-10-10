"""Read-only analytics deadlines. Timeouts are unavailable results, never empty data."""
import asyncio
import logging
from fastapi import HTTPException
from pymongo.errors import PyMongoError

SNAPSHOT_QUERY_MAX_MS = 15000
REQUEST_TIMEOUT_SECONDS = 20
logger = logging.getLogger(__name__)


def unavailable(code):
    return HTTPException(503, detail={
        "code": code, "message": "Price results are temporarily unavailable. Please retry.",
        "retryable": True,
    }, headers={"Retry-After": "5"})


async def bounded_read(operation):
    try:
        return await asyncio.wait_for(operation, timeout=REQUEST_TIMEOUT_SECONDS)
    except (TimeoutError, PyMongoError) as exc:
        code = "price_query_timeout" if isinstance(exc, TimeoutError) or exc.timeout else "price_database_unavailable"
        logger.exception("Price analytics read failed: %s", code)
        raise unavailable(code) from exc
"""Leases are short and renewed by a live holder; a holder that disappears
(a backend restart on every release) frees its lease within the TTL instead of
blocking rebuilds for an hour and crawls for three (12 Oct 2026)."""
import asyncio
import os
import sys
import uuid
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import job_control  # noqa: E402


def test_live_holder_renews_and_dead_holder_expires(monkeypatch):
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    monkeypatch.setattr(job_control, "LEASE_TTL", timedelta(seconds=1.5))
    monkeypatch.setattr(job_control, "LEASE_RENEW_SECS", 0.3)

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["lease_" + uuid.uuid4().hex]
        try:
            assert await job_control.acquire(db, "k", "alive", hours=1)
            await asyncio.sleep(2.5)                       # longer than the TTL
            assert not await job_control.acquire(db, "k", "other", hours=1)   # renewed, still held
            await job_control.release(db, "k", "alive")
            assert await job_control.acquire(db, "k", "other", hours=1)

            # A holder that dies: its renewal stops (simulated by cancelling it).
            assert await job_control.acquire(db, "dead-key", "dead", hours=3)
            job_control._renewals.pop(("dead-key", "dead")).cancel()
            assert not await job_control.acquire(db, "dead-key", "next", hours=3)
            await asyncio.sleep(2)
            assert await job_control.acquire(db, "dead-key", "next", hours=3)   # freed within the TTL

            # The caller's maximum still bounds a renewed lease.
            assert await job_control.acquire(db, "short", "x", hours=1 / 3600)  # one second
            await asyncio.sleep(2.2)
            assert await job_control.acquire(db, "short", "y", hours=1)
        finally:
            for task in list(job_control._renewals.values()):
                task.cancel()
            job_control._renewals.clear()
            await client.drop_database(db.name)
            client.close()
    asyncio.run(scenario())

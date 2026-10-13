"""Heartbeats record each process; a backfill whose process died is resumed
once per interruption, at most BACKFILL_MAX_RESUMES times (13 Oct 2026)."""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _server():
    os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
    os.environ.setdefault("DB_NAME", "test_process_watch")
    os.environ.setdefault("JWT_SECRET", "x" * 32)
    os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
    from cryptography.fernet import Fernet
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    import server
    return server


def _db():
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    client = AsyncIOMotorClient(_loopback_mongo_url())
    return client, client["pw_" + uuid.uuid4().hex]


def test_heartbeat_records_this_process(monkeypatch):
    import process_watch
    monkeypatch.setattr(process_watch, "HEARTBEAT_SECS", 0.05)
    monkeypatch.setattr(process_watch, "_task", None)

    async def scenario():
        client, db = _db()
        try:
            process_watch.start(db, lambda: {"rebuild_running": False})
            await asyncio.sleep(0.3)
            rows = await process_watch.history(db)
            alive = await process_watch.alive_boot_ids(db)
            return rows, alive
        finally:
            process_watch._task.cancel()
            await client.drop_database(db.name)
            client.close()
    rows, alive = asyncio.run(scenario())
    assert rows[0]["boot_id"] == process_watch.BOOT_ID and rows[0]["alive"] is True
    assert rows[0]["rebuild_running"] is False and "max_loop_lag_ms" in rows[0]
    assert process_watch.BOOT_ID in alive


def test_interrupted_backfill_resumes_remaining_stores(monkeypatch):
    server = _server()

    async def scenario():
        client, db = _db()
        monkeypatch.setattr(server, "db", db)
        started = []

        async def fake_start(stores, rematch, started_by, resumed_from=None, resume_count=0):
            started.append({"stores": [s["name"] for s in stores], "rematch": rematch,
                            "from": resumed_from, "count": resume_count, "by": started_by})
            return "new-run"
        monkeypatch.setattr(server, "_start_backfill_run", fake_start)
        try:
            now = datetime.now(timezone.utc)
            await db.stores.insert_many([{"id": f"s{i}", "name": f"Store{i}"} for i in range(4)])
            await db.process_heartbeats.insert_many([
                {"_id": "dead", "last_at": now - timedelta(minutes=30), "started_at": now - timedelta(hours=2)},
                {"_id": "alive", "last_at": now, "started_at": now - timedelta(hours=1)},
            ])
            stores = lambda *st: [{"store_id": f"s{i}", "name": f"Store{i}", "status": x} for i, x in st]  # noqa: E731
            await db.backfill_runs.insert_many([
                {"id": "dead-run", "status": "running", "boot_id": "dead", "rematch_requested": True,
                 "stores": stores((0, "done"), (1, "crawling"), (2, "queued"))},
                {"id": "alive-run", "status": "running", "boot_id": "alive", "stores": stores((3, "crawling"))},
                {"id": "legacy-run", "status": "running", "stores": stores((3, "crawling"))},
                {"id": "looping-run", "status": "running", "boot_id": "dead", "resume_count": 3,
                 "stores": stores((3, "crawling"))},
            ])
            await server._resume_interrupted_backfills(delay_secs=0)
            runs = {r["id"]: r async for r in db.backfill_runs.find({}, {"_id": 0})}
            return started, runs
        finally:
            await client.drop_database(db.name)
            client.close()
    started, runs = asyncio.run(scenario())
    assert started == [{"stores": ["Store1", "Store2"], "rematch": True, "from": "dead-run", "count": 1, "by": "auto-resume"}]
    assert runs["dead-run"]["status"] == "interrupted" and runs["dead-run"]["resumed_as"] == "new-run"
    assert runs["alive-run"]["status"] == "running"          # its process is alive
    assert runs["legacy-run"]["status"] == "running"         # no owner recorded: left alone
    assert runs["looping-run"]["status"] == "interrupted" and "resume_stopped" in runs["looping-run"]

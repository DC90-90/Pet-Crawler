"""An automatic category-map refresh neither repeats on every load nor bumps
the observation revision; an index build whose connection drops waits for the
server to finish (11 Oct 2026)."""
import asyncio
import os
import sys
import uuid

from pymongo.errors import NetworkTimeout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import index_builds  # noqa: E402


def test_category_map_refresh_runs_once_and_keeps_the_revision(monkeypatch):
    import category_map
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["catmap_" + uuid.uuid4().hex]
        try:
            await db.data_versions.insert_one({"_id": "observations", "revision": 5})
            calls = []
            real = category_map.rebuild

            async def counting(db_, **kw):
                calls.append(1)
                return await real(db_, **kw)
            monkeypatch.setattr(category_map, "rebuild", counting)
            await category_map.load(db)          # no categorised products → no rows, but a build marker
            await category_map.load(db)
            await category_map.load(db)
            rev = await db.data_versions.find_one({"_id": "observations"})
            marker = await db.data_versions.find_one({"_id": "category_map"})
            return len(calls), rev["revision"], marker is not None and marker.get("built_at") is not None
        finally:
            await client.drop_database(db.name)
            client.close()
    assert asyncio.run(scenario()) == (1, 5, True)


def test_dropped_connection_waits_for_the_server_side_build(monkeypatch):
    listed = {"n": 0}

    class _Coll:
        async def create_index(self, keys, **options):
            raise NetworkTimeout("The read operation timed out")

        async def index_information(self):
            listed["n"] += 1
            return {"_id_": {}, **({"event_id_1": {}} if listed["n"] >= 2 else {})}

    class _DB:
        def __getitem__(self, name):
            return _Coll()

    async def no_sleep(_):
        return None
    monkeypatch.setattr(index_builds.asyncio, "sleep", no_sleep)
    result = asyncio.run(index_builds.build_one(_DB(), "product_snapshots", [("event_id", 1)], {"unique": True}, disconnect_wait_s=60))
    assert result["status"] == "ok_after_disconnect" and result["name"] == "event_id_1"
    assert "connection dropped" in result["note"]

    class _Never(_Coll):
        async def index_information(self):
            return {"_id_": {}}

    class _DB2:
        def __getitem__(self, name):
            return _Never()
    # Without sleeping, the wait loop spins until the deadline; keep it tiny.
    result = asyncio.run(index_builds.build_one(_DB2(), "product_snapshots", [("event_id", 1)], {}, disconnect_wait_s=0.05))
    assert result["status"] == "failed" and "not listed" in result["error"]

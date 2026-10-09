"""Release safety rehearsal: random local databases only; no production backup claim."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
import pytest
import httpx

from test_acceptance_six_regressions import db as disposable_db, _run
from release_database import GuardedDatabase
import release_control as control
import release_runtime
import maintenance_operations
import release_api
import server
import job_control
import crawlers
import matcher
import zid_orders

db = disposable_db


@pytest.fixture
def release(monkeypatch):
    current = {"release_id": "sha256:rehearsal-A", "git_commit": "a"*40,
               "manifest_verified": True, "source_state": "isolated-test", "scheduler_protocol": "fenced-platform-cron-v1"}
    for module in (control, release_runtime, maintenance_operations):
        monkeypatch.setattr(module, "identity", lambda: dict(current))
    import release_identity
    monkeypatch.setattr(release_identity, "identity", lambda: dict(current))
    return current


async def configure(db, release, capabilities=None):
    import integrity_indexes
    await integrity_indexes.ensure(db)  # Explicit fixture setup, never application startup.
    wrapped = GuardedDatabase(db)
    s = await control.state(wrapped)
    await control.transition(wrapped, "freeze", s["revision"], "operator", "isolated rehearsal approval")
    s = await control.state(wrapped)
    await control.transition(wrapped, "activate", s["revision"], "operator", "isolated rehearsal activation", capabilities or {"manual_refresh": True}, release["release_id"])
    return wrapped


def test_startup_is_read_only_no_seed_migration_or_integration_probe(db, release, monkeypatch):
    async def go():
        wrapped = GuardedDatabase(db)
        monkeypatch.setattr(server, "db", wrapped)
        monkeypatch.setattr(server, "_wait_for_mongo", AsyncMock(return_value=True))
        spies = []
        for name in ("seed_super_admin", "seed_database", "ensure_all_indexes", "backfill_food_subcategories", "_maybe_backfill_store_metrics", "_retired_uncontrolled_boot_sequence"):
            spy = AsyncMock(side_effect=AssertionError("startup side effect"))
            monkeypatch.setattr(server, name, spy); spies.append(spy)
        await server._boot_sequence()
        assert await db.list_collection_names() == []
        for spy in spies: spy.assert_not_called()
    _run(go())


@pytest.mark.parametrize("operation", ["insert_one", "insert_many", "update_one", "delete_many", "create_index", "drop", "bulk_write", "find_one_and_update"])
def test_default_observer_rejects_direct_and_get_side_business_writes(db, release, operation):
    async def go():
        wrapped = GuardedDatabase(db)
        args = {"insert_one": ({"a": 1},), "insert_many": ([{"a": 1}],), "update_one": ({}, {"$set": {"a": 1}}),
                "delete_many": ({},), "create_index": ("a",), "drop": (), "bulk_write": ([],), "find_one_and_update": ({}, {"$set": {"a": 1}})}
        with pytest.raises(control.ReleaseBlocked):
            await getattr(wrapped.product_snapshots, operation)(*args[operation])
        assert await db.product_snapshots.count_documents({}) == 0
        assert await db.list_collection_names() == []
    _run(go())


def test_freeze_drains_admitted_writer_blocks_new_admission_then_proves_quiescence(db, release):
    async def go():
        wrapped = await configure(db, release)
        started, finish = asyncio.Event(), asyncio.Event()
        async def existing():
            async with control.writer(wrapped, "job:manual", "manual_refresh"):
                await wrapped.product_snapshots.insert_one({"id": "before"})
                started.set(); await finish.wait()
                await wrapped.product_snapshots.insert_one({"id": "finish-admitted-work"})
        task = asyncio.create_task(existing()); await started.wait()
        s = await control.state(wrapped)
        result = await control.transition(wrapped, "freeze", s["revision"], "operator", "freeze rehearsal")
        assert result["mode"] == "freezing" and len(result["active_writers"]) == 1
        with pytest.raises(control.ReleaseBlocked):
            async with control.writer(wrapped, "new-job", "manual_refresh"): pass
        finish.set(); await task
        s = await control.state(wrapped)
        assert s["mode"] == "frozen" and not s["active_writers"]
        with pytest.raises(control.ReleaseBlocked):
            await wrapped.product_snapshots.insert_one({"id": "late"})
        assert await db.product_snapshots.count_documents({}) == 2
    _run(go())


def test_crashed_writer_is_not_silently_expired_or_declared_frozen(db, release):
    async def go():
        wrapped = await configure(db, release)
        await db.release_control.update_one({"_id": control.KEY}, {"$push": {"active_writers": {"token": "abandoned", "release": release["release_id"], "purpose": "crashed", "started_at": "2000-01-01T00:00:00+00:00"}}})
        s = await control.state(wrapped)
        result = await control.transition(wrapped, "freeze", s["revision"], "operator", "freeze after crash")
        assert result["mode"] == "freezing"
        with pytest.raises(control.ReleaseBlocked):
            await control.transition(wrapped, "activate", result["revision"], "operator", "unsafe activation", {"manual_refresh": True}, release["release_id"])
    _run(go())


def test_controlled_index_operation_requires_frozen_claim_approval_and_unchanged_plan(db, release):
    async def go():
        wrapped = GuardedDatabase(db)
        p = await maintenance_operations.plan(wrapped, "integrity-indexes")
        assert await db.list_collection_names() == []
        with pytest.raises(control.ReleaseBlocked):
            await maintenance_operations.apply(wrapped, "integrity-indexes", p["plan_hash"], "index approval", "operator")
        await control.transition(wrapped, "freeze", 0, "operator", "prepare indexes")
        s = await control.state(wrapped)
        await control.transition(wrapped, "claim-maintenance", s["revision"], "operator", "claim isolated maintenance", expected_release=release["release_id"])
        p = await maintenance_operations.plan(wrapped, "integrity-indexes")
        with pytest.raises(control.ReleaseBlocked):
            await maintenance_operations.apply(wrapped, "integrity-indexes", "wrong", "index approval", "operator")
        result = await maintenance_operations.apply(wrapped, "integrity-indexes", p["plan_hash"], "approved isolated indexes", "operator")
        assert result["status"] == "completed"
        indexes = await db.products.index_information()
        assert any(i.get("unique") and i.get("key") == [("offer_id", 1)] for i in indexes.values())
        assert (await control.state(wrapped))["mode"] == "frozen"
        assert not (await control.state(wrapped))["active_writers"]
    _run(go())


def test_scheduler_generation_handoff_and_rollback_fences_stale_jobs(db, release):
    async def go():
        wrapped = await configure(db, release)
        async with control.writer(wrapped, "manual:queue", "manual_refresh"):
            old_run, _ = await job_control.queue(wrapped, "matching")
        before = await db.job_runs.find_one({"id": old_run}, {"_id": 0})
        for new_id in ("sha256:rehearsal-B", "sha256:rehearsal-A"):
            s = await control.state(wrapped)
            await control.transition(wrapped, "freeze", s["revision"], "operator", "rehearsal handoff freeze")
            release["release_id"] = new_id
            s = await control.state(wrapped)
            await control.transition(wrapped, "activate", s["revision"], "operator", "compatible protocol handoff", {"manual_refresh": True}, new_id)
            action = AsyncMock(return_value={"status": "ok"})
            with pytest.raises(control.ReleaseBlocked):
                await job_control.execute(wrapped, old_run, "matching", action)
            action.assert_not_called()
        assert await db.job_runs.find_one({"id": old_run}, {"_id": 0}) == before
        async with control.writer(wrapped, "manual:queue", "manual_refresh"):
            new_run, _ = await job_control.queue(wrapped, "matching")
        action = AsyncMock(return_value={"status": "ok"})
        await job_control.execute(wrapped, new_run, "matching", action)
        action.assert_awaited_once()
        assert (await db.job_runs.find_one({"id": new_run}, {"_id": 0}))["status"] == "completed"
    _run(go())


def test_unavailable_orders_and_refresh_helpers_exit_before_integration_calls(db, release, monkeypatch):
    async def go():
        wrapped = GuardedDatabase(db)
        get_creds = AsyncMock(side_effect=AssertionError("external credentials should not be read"))
        monkeypatch.setattr(zid_orders.zid_oauth, "credentials", get_creds)
        assert (await zid_orders.sync_own_store_orders(wrapped))["status"] == "skipped"
        get_creds.assert_not_called()
        with pytest.raises(control.ReleaseBlocked):
            await crawlers.crawl_store_waterfall(wrapped, {"id": "s", "name": "S", "domain": "example.invalid"})
        with pytest.raises(control.ReleaseBlocked):
            await crawlers.sync_own_store_prices(wrapped)
        with pytest.raises(control.ReleaseBlocked):
            await matcher.run_matching_for_all(wrapped)
        assert await db.list_collection_names() == []
    _run(go())


def test_unimplemented_delivery_cannot_be_enabled_and_unstamped_build_cannot_write(db, release):
    async def go():
        wrapped = GuardedDatabase(db)
        await control.transition(wrapped, "freeze", 0, "operator", "prepare activation")
        for cap in ("email", "digests"):
            s = await control.state(wrapped)
            with pytest.raises(control.ReleaseBlocked):
                await control.transition(wrapped, "activate", s["revision"], "operator", "reject fake delivery", {cap: True}, release["release_id"])
        release["manifest_verified"] = False
        s = await control.state(wrapped)
        with pytest.raises(control.ReleaseBlocked):
            await control.transition(wrapped, "activate", s["revision"], "operator", "reject unstamped code", {"manual_refresh": True}, release["release_id"])
    _run(go())


def test_http_auth_control_plane_and_disabled_cron_without_queued_work(db, release, monkeypatch):
    async def go():
        wrapped = GuardedDatabase(db)
        monkeypatch.setattr(server, "db", wrapped)
        monkeypatch.setenv("WEBHOOK_CRON_SECRET", "isolated-rehearsal-secret")
        ids = {}
        for role in ("super_admin", "user"):
            result = await db.users.insert_one({"email": role+"@release-test.invalid", "role": role, "is_active": True, "session_version": 0, "allowed_pages": ["my_products", "price_intel", "settings"]})
            ids[role] = str(result.inserted_id)
        admin = {"Authorization": "Bearer "+server.make_token(ids["super_admin"], "super_admin@release-test.invalid")}
        user = {"Authorization": "Bearer "+server.make_token(ids["user"], "user@release-test.invalid")}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://isolated.test") as client:
            public = await client.get("/api/release")
            assert public.status_code == 200 and not any(public.json()["capabilities"].values())
            body = {"action": "freeze", "expected_revision": 0, "approval": "HTTP isolated rehearsal"}
            assert (await client.post("/api/admin/release-control", json=body)).status_code == 401
            assert (await client.post("/api/admin/release-control", json=body, headers=user)).status_code == 403
            assert (await client.post("/api/import/sync-own-store", headers=admin)).status_code == 423
            assert (await client.post("/api/cron/own-sync", json={"event": "schedule.triggered"}, headers={"Authorization": "Bearer wrong"})).status_code == 401
            response = await client.post("/api/cron/own-sync", json={"event": "schedule.triggered", "run_id": "off-run"}, headers={"Authorization": "Bearer isolated-rehearsal-secret"})
            assert response.status_code == 200 and response.json()["status"] == "disabled" and response.json()["accepted"] is False
            assert await db.job_runs.count_documents({}) == 0
            frozen = await client.post("/api/admin/release-control", json=body, headers=admin)
            assert frozen.status_code == 200 and frozen.json()["control"]["mode"] == "frozen"
            assert (await client.post("/api/admin/release-control", json=body, headers=admin)).status_code == 409
            assert (await client.get("/api/my-products", headers=admin)).status_code == 200
        assert not (await control.state(wrapped))["active_writers"]
        assert await db.product_snapshots.count_documents({}) == 0
    _run(go())


def test_http_manual_write_permit_is_drained_and_freeze_prevents_next_mutation(db, release, monkeypatch):
    async def go():
        wrapped = await configure(db, release)
        monkeypatch.setattr(server, "db", wrapped)
        user = await db.users.insert_one({"email": "operator@release-test.invalid", "role": "super_admin", "is_active": True})
        headers = {"Authorization": "Bearer "+server.make_token(str(user.inserted_id), "operator@release-test.invalid")}
        match = {"my_sku": "OWN", "competitor_sku": "C", "competitor_store_id": "S", "competitor_offer_id": "O"}
        await db.product_matches.insert_one(dict(match))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://isolated.test") as client:
            r = await client.post("/api/price-intel/reject-match", json=match, headers=headers)
            assert r.status_code == 200, r.text
            assert await db.product_matches.count_documents({}) == 0
            assert not (await control.state(wrapped))["active_writers"]
            await db.product_matches.insert_one(dict(match))
            s = await control.state(wrapped)
            await control.transition(wrapped, "freeze", s["revision"], "operator", "manual mutation freeze")
            r = await client.post("/api/price-intel/reject-match", json=match, headers=headers)
            assert r.status_code == 423
            assert await db.product_matches.count_documents({}) == 1
    _run(go())


def test_activation_requires_explicit_schema_preparation(db, release):
    async def go():
        wrapped = GuardedDatabase(db)
        await control.transition(wrapped, "freeze", 0, "operator", "freeze new database")
        s = await control.state(wrapped)
        with pytest.raises(control.ReleaseBlocked) as exc:
            await control.transition(wrapped, "activate", s["revision"], "operator", "attempt before schema", {"manual_refresh": True}, release["release_id"])
        assert exc.value.detail["reason"] == "explicit_integrity_index_operation_required"
        assert await db.products.index_information() == {}
    _run(go())


def test_uncommitted_candidate_is_not_production_ready(db, release, monkeypatch):
    async def go():
        monkeypatch.setattr(server, "db", GuardedDatabase(db))
        monkeypatch.setattr(server, "BOOT_STATE", {"status": "done", "errors": []})
        release["git_commit"] = None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://isolated.test") as client:
            r = await client.get("/api/ready")
            assert r.status_code == 503 and r.json()["ready"] is False
    _run(go())
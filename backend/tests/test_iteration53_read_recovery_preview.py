"""iteration53 read-recovery verification on preview + local policy guards.

Modules/features:
- /api/admin/analytics-read-plan authorization + contract checks
- read_plan_policy sanitization/forbidden-stage safeguards
- release_database explain guard default-deny behavior
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

from _auth import base_url, login_response
from read_plan_policy import summarize_plan, validate_pipeline
from release_control import ReleaseBlocked
from release_database import GuardedDatabase


BASE = base_url().rstrip("/")
API = f"{BASE}/api"
SUPER_EMAIL = "a.disi@taqueen.sa"
NORMAL_EMAIL = "test_iter73y_normal@example.com"
NORMAL_PASSWORD = "NormalUser#123"


def _must_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    assert value, f"Missing required env: {name}"
    return value


@pytest.fixture(scope="module")
def super_headers() -> dict[str, str]:
    password = _must_env("DALEEL_TEST_PASSWORD")
    resp = login_response(SUPER_EMAIL, password)
    assert resp is not None, "super admin login had no response"
    assert resp.status_code == 200, f"super admin login failed: {resp.status_code} {resp.text[:300]}"
    token = resp.json().get("token")
    assert token, "super admin login missing token"
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture(scope="module")
def normal_headers() -> dict[str, str]:
    resp = login_response(NORMAL_EMAIL, NORMAL_PASSWORD)
    if resp is None or resp.status_code != 200:
        pytest.skip("normal test credentials unavailable in this preview environment")
    token = resp.json().get("token")
    if not token:
        pytest.skip("normal test credentials returned no token")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _all_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _all_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _all_keys(nested)


def test_read_plan_endpoint_unauth_returns_401():
    r = requests.get(f"{API}/admin/analytics-read-plan", timeout=30)
    assert r.status_code == 401


def test_read_plan_endpoint_non_super_admin_returns_403(normal_headers):
    r = requests.get(f"{API}/admin/analytics-read-plan", headers=normal_headers, timeout=30)
    assert r.status_code == 403


def test_read_plan_endpoint_super_admin_ok_and_sanitized(super_headers):
    started = datetime.now(timezone.utc)
    r = requests.get(f"{API}/admin/analytics-read-plan", headers=super_headers, params={"pipeline": "cohort"}, timeout=45)
    elapsed_ms = r.elapsed.total_seconds() * 1000.0
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("query") == "cohort"
    assert body.get("mode") == "queryPlanner"
    assert body.get("trigger") == "manual"
    assert body.get("status") in ("available", "unavailable")
    assert body.get("observed_at")
    assert datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00")) >= started

    # Metadata contract: no raw query/filter/index bounds/server internals leak
    leaked = {"indexBounds", "filter", "parsedQuery", "serverInfo", "rejectedPlans", "namespace", "uri"}
    keys = set(_all_keys(body))
    assert leaked.isdisjoint(keys), f"sensitive fields leaked: {sorted(leaked.intersection(keys))}"

    text = r.text
    assert "ObjectId(" not in text
    assert "$oid" not in text

    if body.get("plan"):
        assert isinstance(body["plan"].get("indexes", []), list)
    assert isinstance(body.get("installed_indexes", []), list)
    for item in body.get("installed_indexes", []):
        assert isinstance(item.get("name"), str)
        for key in item.get("keys", []):
            assert "field" in key and "direction" in key

    # Bound remains finite (best-effort envelope, diagnostics has 5s internal cap).
    assert elapsed_ms < 12000


def test_read_plan_endpoint_validation_errors(super_headers):
    invalid = requests.get(
        f"{API}/admin/analytics-read-plan",
        headers=super_headers,
        params={"pipeline": "not-real"},
        timeout=30,
    )
    assert invalid.status_code == 422

    unknown = requests.get(
        f"{API}/admin/analytics-read-plan",
        headers=super_headers,
        params={"pipeline": "cohort", "verbosity": "executionStats"},
        timeout=30,
    )
    assert unknown.status_code == 400

    duplicate = requests.get(
        f"{API}/admin/analytics-read-plan?pipeline=cohort&pipeline=latest",
        headers=super_headers,
        timeout=30,
    )
    assert duplicate.status_code == 400

    method = requests.post(
        f"{API}/admin/analytics-read-plan",
        headers=super_headers,
        json={"pipeline": "cohort"},
        timeout=30,
    )
    assert method.status_code == 405


def test_validate_pipeline_forbidden_stages_and_nested_expressions_rejected():
    validate_pipeline([
        {"$match": {"store_id": {"$in": ["s1", "s2"]}}},
        {"$sort": {"crawled_at": -1}},
    ])

    bad_pipelines = [
        [{"$facet": {"x": []}}],
        [{"$lookup": {"from": "x", "localField": "a", "foreignField": "b", "as": "j"}}],
        [{"$match": {"$where": "this.price > 0"}}],
        [{"$project": {"x": {"$function": {"body": "return 1", "args": [], "lang": "js"}}}}],
        [{"$merge": {"into": "x"}}],
        [{"$out": "x"}],
        [{"$unionWith": "other"}],
    ]
    for pipeline in bad_pipelines:
        with pytest.raises(ReleaseBlocked):
            validate_pipeline(pipeline)


def test_summarize_plan_accepts_winning_collscan_and_ignores_rejected_plans():
    raw = {
        "queryPlanner": {
            "winningPlan": {
                "stage": "SORT_MERGE",
                "inputStages": [
                    {"stage": "COLLSCAN"},
                    {"stage": "IXSCAN", "indexName": "store_idx", "keyPattern": {"store_id": 1, "crawled_at": -1}},
                ],
            },
            "rejectedPlans": [
                {"stage": "COLLSCAN", "filter": {"price": {"$gt": 10}}},
            ],
        },
        "serverInfo": {"host": "forbidden-leak"},
    }
    out = summarize_plan(raw)
    assert "SORT_MERGE" in out.stages
    assert out.collection_scan is True
    assert out.blocking_sort is False
    names = [idx.name for idx in out.indexes]
    assert "store_idx" in names


@pytest.mark.anyio
async def test_guarded_database_general_explain_blocked_without_permit():
    mongo_url = _must_env("MONGO_URL")
    db_name = _must_env("DB_NAME")
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=4000)
    try:
        guarded = GuardedDatabase(client[db_name])
        with pytest.raises(ReleaseBlocked):
            await guarded.command({"explain": {"aggregate": "product_snapshots", "pipeline": [], "cursor": {}}})
    finally:
        client.close()


@pytest.mark.anyio
async def test_guarded_database_explain_snapshot_read_allows_queryplanner_only():
    mongo_url = _must_env("MONGO_URL")
    db_name = _must_env("DB_NAME")
    client = AsyncIOMotorClient(mongo_url, serverSelectionTimeoutMS=4000)
    try:
        guarded = GuardedDatabase(client[db_name])
        pipeline = [{"$match": {"observation_version": 2}}, {"$sort": {"crawled_at": -1}}]
        result = await guarded.explain_snapshot_read(pipeline)
        assert isinstance(result, dict)
        assert "queryPlanner" in result

        with pytest.raises(ReleaseBlocked):
            await guarded.explain_snapshot_read(pipeline, hint={"store_id": 1})
    finally:
        client.close()

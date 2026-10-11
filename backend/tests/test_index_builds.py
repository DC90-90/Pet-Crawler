"""Operator index builds: independent per index, duplicates fall back to a
non-unique index, every outcome is recorded (11 Oct 2026)."""
import asyncio
import os
import sys

from pymongo.errors import DuplicateKeyError, OperationFailure

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import index_builds  # noqa: E402


class _Coll:
    def __init__(self, behaviour):
        self.behaviour, self.calls = behaviour, []

    async def create_index(self, keys, **options):
        self.calls.append((keys, options))
        b = self.behaviour
        if b == "dup" and options.get("unique"):
            raise DuplicateKeyError("E11000 duplicate key")
        if b == "dup_code" and options.get("unique"):
            raise OperationFailure("dup", code=11000)
        if b == "boom":
            raise OperationFailure("Index build aborted", code=276)
        return "_".join(f"{k}_{d}" for k, d in keys)


class _DB:
    def __init__(self, colls):
        self.colls = colls

    def __getitem__(self, name):
        return self.colls[name]


def test_unique_index_falls_back_when_duplicates_exist():
    for behaviour in ("dup", "dup_code"):
        coll = _Coll(behaviour)
        result = asyncio.run(index_builds.build_one(_DB({"product_snapshots": coll}), "product_snapshots",
                                                    [("event_id", 1)], {"unique": True, "partialFilterExpression": {"event_id": {"$type": "string"}}}))
        assert result["status"] == "ok_non_unique" and result["name"] == "event_id_1"
        assert coll.calls[1][1] == {"partialFilterExpression": {"event_id": {"$type": "string"}}}


def test_failures_are_reported_and_do_not_stop_the_registry():
    colls = {"a": _Coll("boom"), "b": _Coll("ok")}
    registry = [("a", [("x", 1)], {}), ("b", [("y", 1)], {})]
    recorded = []

    async def record(key, result):
        recorded.append((key, result["status"]))
    results = asyncio.run(index_builds.run(_DB(colls), registry=registry, record=record))
    assert results["a:x_1"]["status"] == "failed" and "276" in results["a:x_1"]["error"]
    assert results["b:y_1"] == {"status": "ok", "name": "y_1", "secs": results["b:y_1"]["secs"]}
    assert recorded == [("a:x_1", "failed"), ("b:y_1", "ok")]
    assert index_builds.STATE["status"] == "done"


def test_registry_covers_the_write_path():
    labels = [index_builds.label(c, k) for c, k, _ in index_builds.REGISTRY]
    assert labels[0] == "product_snapshots:event_id_1"
    assert index_builds.REGISTRY[0][2]["unique"] is True
    assert "observation_events:offer_id_1_observed_at_-1" in labels
    assert "crawl_checkpoints:store_id_1_state_1_observed_at_1" in labels

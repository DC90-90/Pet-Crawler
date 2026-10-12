"""A replayed capture refused only by a sealed ledger day stays explicitly
`recovery_required` (sealed history changes only through reconciliation, see
test_four_correctness_regressions), but is not replayed again on every crawl;
any other unresolved capture is still retried (12 Oct 2026)."""
import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import crawl_persistence as cp  # noqa: E402
from ledger_receipts import LedgerIncomplete  # noqa: E402


def _sealed_result(n=3):
    return {"day": "2026-10-11", "written": 0, "duplicate": 0, "rejected_sealed": n, "first_seen": 0,
            "skipped": 0, "complete": False,
            "errors": [{"event_id": f"e{i}", "reason": cp.SEALED_REASON} for i in range(n)]}


def test_sealed_only_classification():
    assert cp.sealed_ledger_only(LedgerIncomplete(_sealed_result()))
    mixed = _sealed_result()
    mixed["errors"].append({"event_id": "x", "reason": "something_else"})
    assert not cp.sealed_ledger_only(LedgerIncomplete(mixed))
    assert not cp.sealed_ledger_only(LedgerIncomplete({**_sealed_result(), "skipped": 2}))
    assert not cp.sealed_ledger_only(RuntimeError("boom"))
    assert cp.awaiting_reconciliation({"state": "recovery_required",
                                       "recovery_error": {"type": "LedgerIncomplete", "detail": _sealed_result()}})
    assert not cp.awaiting_reconciliation({"state": "recovery_required",
                                           "recovery_error": {"type": "NetworkTimeout", "detail": None}})
    assert not cp.awaiting_reconciliation({"state": "captured"})


def test_known_sealed_captures_are_skipped_others_retried(monkeypatch):
    class _Cursor:
        def __init__(self, docs):
            self.docs = docs

        def sort(self, *a):
            return self

        def __aiter__(self):
            self._it = iter(self.docs)
            return self

        async def __anext__(self):
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration

    now = datetime.now(timezone.utc)

    class _Checkpoints:
        def __init__(self):
            base = {"store_id": "s", "observed_at": now, "tier": 1, "confidence": 95}
            self.docs = {
                "sealed": {**base, "_id": "sealed", "state": "recovery_required", "raw_rows": [{"sku": "sealed"}],
                           "recovery_error": {"type": "LedgerIncomplete", "detail": _sealed_result()}},
                "timeout": {**base, "_id": "timeout", "state": "recovery_required", "raw_rows": [{"sku": "timeout"}],
                            "recovery_error": {"type": "NetworkTimeout", "detail": None}},
            }

        def find(self, q):
            return _Cursor([d for d in self.docs.values() if d["state"] in q["state"]["$in"]])

        async def update_one(self, q, update):
            doc = self.docs[q["_id"]]
            doc.update(update.get("$set", {}))
            for k in update.get("$unset", {}):
                doc.pop(k, None)

    class _DB:
        crawl_checkpoints = _Checkpoints()

    replayed = []

    async def process(db, store, rows, observed_at, tier=1, confidence=95):
        replayed.append(rows[0]["sku"])
        return 1, 1
    import crawlers
    monkeypatch.setattr(crawlers, "process_crawled_products", process)
    db = _DB()
    assert asyncio.run(cp.recover(db, {"id": "s", "name": "S"})) == 1
    assert replayed == ["timeout"]
    assert db.crawl_checkpoints.docs["sealed"]["state"] == "recovery_required"
    assert db.crawl_checkpoints.docs["timeout"]["state"] == "persisted"

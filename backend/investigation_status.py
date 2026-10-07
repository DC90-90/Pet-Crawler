"""Read-only, bounded migration diagnostics. Never silently bless historical observations."""
import hashlib
from functools import lru_cache
from pathlib import Path
from price_cohort import POLICY_VERSION


@lru_cache(maxsize=1)
def build_identity():
    files = sorted(Path(__file__).parent.glob("*.py")) + sorted((Path(__file__).parent/"core").glob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode()+path.read_bytes())
    return {"code_digest": digest.hexdigest(), "observation_contract": 2, "price_policy": POLICY_VERSION,
            "sales_algorithm": 2, "scheduler": "platform_cron", "public_registration_default": False}


async def status(db):
    return {"build": build_identity(), "observations": {
        "verified": await db.product_snapshots.count_documents({"observation_version": 2, "is_synthetic": False}),
        "legacy_unverified": await db.product_snapshots.count_documents({"observation_version": {"$ne": 2}}),
        "explicit_synthetic": await db.product_snapshots.count_documents({"is_synthetic": True}),
        "quarantined": await db.observation_quarantine.count_documents({}),
        "immutable_events": await db.observation_events.count_documents({}),
        "versioned_intervals": await db.sales_facts_v2.count_documents({}),
    }, "orders_coverage": await db.orders_sync_coverage.find({}, {"_id": 0}).sort("synced_at", -1).limit(5).to_list(5),
       "recent_jobs": await db.job_runs.find({}, {"_id": 0, "result": 0}).sort("created_at", -1).limit(20).to_list(20),
       "history_policy": "Legacy observations remain archived and are excluded from actionable comparisons. Recrawl required; never fabricate missing variant evidence."}
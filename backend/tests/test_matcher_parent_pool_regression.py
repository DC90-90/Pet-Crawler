"""Parent-only candidate pools must abort before automatic-match deletion."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from test_acceptance_six_regressions import db as acceptance_db, _run, _store
import matcher
import verified_matching
import job_control
from price_cohort import exclusion

db = acceptance_db


def test_parent_registry_only_pool_aborts_and_preserves_unrelated_automatic_matches(db):
    async def go():
        now = datetime.now(timezone.utc)
        await db.stores.insert_many([_store("own", True), _store("competitor")])
        own = {"sku": "OWN", "store_id": "own", "is_own_store": True,
               "barcode": "8699245859829", "name_en": "Beso 20kg", "price": 90}
        await db.my_products.insert_one(dict(own))
        root = {"offer_id": "formerly-valid-root", "listing_id": "listing", "variant_id": "root",
                "store_id": "competitor", "store_name": "competitor", "sku": "ROOT",
                "barcode": "8699245859829", "name_en": "Beso 20kg", "price": 85,
                "currency": "SAR", "price_basis": "storefront_inc_vat", "in_stock": True,
                "confidence_score": 99, "comparable": True, "observation_version": 2,
                "is_synthetic": False, "crawled_at": now}
        await db.product_snapshots.insert_one(dict(root))
        for offer in ("formerly-valid-root", "unrelated-automatic-offer"):
            await db.product_matches.insert_one({"my_sku": "OWN", "competitor_sku": offer,
                "competitor_store_id": "competitor", "competitor_offer_id": offer,
                "manually_confirmed": False, "identity_version": 2, "matched_at": now.isoformat()})
        await db.listing_identities.insert_one({"store_id": "competitor", "listing_id": "listing",
            "known_variant_parent": True, "parent_skus": ["ROOT"], "reasons": ["resolved_children"]})

        before = await db.product_matches.find({}, {"_id": 0}).sort("competitor_offer_id", 1).to_list(None)
        snapshots_before = await db.product_snapshots.find({}, {"_id": 0}).to_list(None)
        candidates, _ = await matcher._build_competitor_lookups(db, "own")
        assert len(candidates) == 1 and exclusion(candidates[0]) is None
        assert candidates[0]["variant_id"] == "root"  # No eligible child offers remain.
        assert await verified_matching.match(db, own, candidates, "own") == []

        message = ("Refusing to rebuild product_matches: 0 current verified competitor offers "
                   "(missing, stale, quarantined, hidden or out of stock). Existing matches left untouched.")
        progress = AsyncMock()
        with patch.object(matcher, "match_my_product", wraps=matcher.match_my_product) as match_call:
            with pytest.raises(RuntimeError) as error:
                await matcher.run_matching_for_all(db, progress_callback=progress)
            assert str(error.value) == message
            match_call.assert_not_called()
            progress.assert_not_called()
        assert await db.product_matches.find({}, {"_id": 0}).sort("competitor_offer_id", 1).to_list(None) == before

        # The durable job must also fail rather than publish successful matching stats.
        run_id, _ = await job_control.queue(db, "matching")
        await job_control.execute(db, run_id, "matching", lambda: matcher.run_matching_for_all(db))
        job = await db.job_runs.find_one({"id": run_id}, {"_id": 0})
        assert job["status"] == "failed" and job["error"] == "RuntimeError"
        assert "result" not in job
        assert await db.product_matches.find({}, {"_id": 0}).sort("competitor_offer_id", 1).to_list(None) == before
        assert await db.product_snapshots.find({}, {"_id": 0}).to_list(None) == snapshots_before
    _run(go())
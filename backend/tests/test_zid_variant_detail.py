"""Zid option parents are resolved from the product-detail route (10 Oct 2026).

The Zid list feed returns `has_options: true` with an empty `variants` array
for roughly 30 % of listings; the detail route carries the variants. Without
the detail call every such listing is quarantined as an unresolved parent.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "test_zid_variant_detail")
os.environ.setdefault("ENCRYPTION_KEY", "")

import crawlers  # noqa: E402
from observation_contract import expand_variants  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


def _fake_fetch(answers):
    calls = []

    async def fetch(http, url, headers=None, **_):
        calls.append((url, headers))
        key = url.rsplit("/", 1)[-1].strip("/") or url.rstrip("/").rsplit("/", 1)[-1]
        answer = answers.get(key)
        if answer is None:
            return None
        return _Resp(*answer)
    fetch.calls = calls
    return fetch


def test_needs_detail_only_for_declared_parents_without_variants():
    assert crawlers._zid_needs_variant_detail({"id": "a", "has_options": True, "variants": []})
    assert crawlers._zid_needs_variant_detail({"id": "a", "has_options": True})
    assert not crawlers._zid_needs_variant_detail({"id": "a", "has_options": False})
    assert not crawlers._zid_needs_variant_detail({"id": "a", "has_options": True, "variants": [{"id": "v1"}]})
    assert not crawlers._zid_needs_variant_detail({"has_options": True})  # no id → cannot fetch


def test_detail_variants_are_attached_and_expanded_per_variant():
    items = [
        {"id": "p1", "sku": "PARENT", "name": "Royal Canin", "price": 9.55, "quantity": 205, "has_options": True, "variants": []},
        {"id": "p2", "sku": "5410340223154", "name": "Single", "price": 20.0, "quantity": 27, "has_options": False},
    ]
    detail = {"id": "p1", "sold_products_count": 181, "variants": [
        {"id": "v1", "sku": "9003579308936", "price": 9.55, "sale_price": None, "quantity": 202, "is_infinite": False},
        {"id": "v2", "sku": "9003579308936carton", "price": 114.54, "sale_price": 108.81, "quantity": 3, "is_infinite": False},
    ]}
    fetch = _fake_fetch({"p1": (200, detail)})
    log = {}
    stats = asyncio.run(crawlers._resolve_zid_variant_parents(None, "https://x.test", items, log, fetch=fetch))
    assert stats == {"candidates": 1, "fetched": 1, "resolved": 1, "failed": 0, "skipped_cap": 0, "aborted": None}
    assert log["variant_detail"] is stats
    assert [u for u, _ in fetch.calls] == ["https://x.test/api/v1/products/p1"]
    assert items[0]["sold_products_count"] == 181
    offers = [o for it in items for o in expand_variants(it)]
    skus = sorted(o["sku"] for o in offers)
    assert skus == ["5410340223154", "9003579308936", "9003579308936carton"]
    carton = next(o for o in offers if o["sku"].endswith("carton"))
    assert carton["price"] == 114.54 and carton["quantity"] == 3 and carton["_resolved_child"] is True
    assert not any(o.get("_unresolved_parent") for o in offers)


def test_detail_without_children_clears_the_option_flag():
    items = [{"id": "p1", "sku": "S", "has_options": True, "variants": []}]
    fetch = _fake_fetch({"p1": (200, {"id": "p1", "variants": []})})
    stats = asyncio.run(crawlers._resolve_zid_variant_parents(None, "https://x.test", items, {}, fetch=fetch))
    assert stats["resolved"] == 1 and items[0]["has_options"] is False
    offers = list(expand_variants(items[0]))
    assert len(offers) == 1 and not offers[0]["_unresolved_parent"]


def test_failures_count_and_circuit_breaker_aborts():
    items = [{"id": f"p{i}", "sku": f"S{i}", "has_options": True, "variants": []} for i in range(40)]
    fetch = _fake_fetch({})  # every call returns None (timeout)
    stats = asyncio.run(crawlers._resolve_zid_variant_parents(None, "https://x.test", items, {}, fetch=fetch))
    assert stats["failed"] == crawlers.ZID_VARIANT_DETAIL_MAX_CONSECUTIVE_FAILURES
    assert stats["aborted"].startswith("30_consecutive_failures")
    assert all(it.get("has_options") is True and not it.get("variants") for it in items)  # untouched → quarantined later, never guessed


def test_cap_limits_detail_calls():
    items = [{"id": f"p{i}", "sku": f"S{i}", "has_options": True, "variants": []} for i in range(5)]
    fetch = _fake_fetch({f"p{i}": (200, {"variants": [{"id": f"v{i}", "sku": f"E{i}", "price": 1}]}) for i in range(5)})
    stats = asyncio.run(crawlers._resolve_zid_variant_parents(None, "https://x.test", items, {}, fetch=fetch, cap=2))
    assert stats["fetched"] == 2 and stats["skipped_cap"] == 3


def test_merchant_sold_counter_reads_sold_products_count():
    assert crawlers._extract_zid_sold_count({"sold_products_count": 181}) == 181
    assert crawlers._extract_zid_sold_count({"sold_quantity": 7, "sold_products_count": 181}) == 7
    assert crawlers._extract_zid_sold_count({}) is None

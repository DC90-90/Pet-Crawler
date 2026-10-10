"""Zid has_options listings are resolved through the detail route before persistence."""
import asyncio
import time

import crawlers
import fetch_policy


def _run(coro):
    return asyncio.run(coro)


def _listing(i, has_options=True, variants=None):
    return {"id": f"p{i}", "sku": f"Z.{i}", "has_options": has_options, "variants": variants or [],
            "name": {"ar": f"منتج {i}", "en": f"Product {i}"}, "price": 10.0, "is_taxable": True,
            "html_url": f"https://example.invalid/p{i}", "images": [{"origin": "img"}]}


def _variant(vid, sku, price, qty, sold=None):
    return {"id": vid, "sku": sku, "barcode": "", "price": price, "sale_price": None, "quantity": qty,
            "is_infinite": False, "is_taxable": True, "sold_products_count": sold,
            "attributes": [{"name": "amount", "value": sku}]}


def test_unresolved_listing_filter_only_targets_has_options_without_variants():
    items = [_listing(1), _listing(2, has_options=False), _listing(3, variants=[_variant("v", "s", 1, 1)]),
             {"has_options": True, "variants": []}]  # no id → cannot be fetched
    assert [it["id"] for it in crawlers._zid_unresolved_listings(items)] == ["p1"]


def test_supplement_grafts_variants_and_records_counts():
    items = [_listing(1), _listing(2), _listing(3, has_options=False)]
    detail = {"variants": [_variant("v1", "6001", 5.0, 3, 7), _variant("v2", "6002", 50.0, 1, 2)],
              "default_variant_id": "v1", "sold_products_count": 9}

    async def fetch(listing):
        return (200, detail) if listing["id"] == "p1" else (200, {"variants": []})

    log = {"endpoints_tried": []}
    fetched, failed = _run(crawlers._zid_variant_detail_supplement(fetch, items, log, "public"))
    assert (fetched, failed) == (1, 1)
    assert items[0]["variants"] == detail["variants"] and items[0]["default_variant_id"] == "v1"
    assert items[1]["variants"] == []
    assert log["variant_detail_candidates"] == 2 and log["variant_detail_fetched"] == 1 and log["variant_detail_failed"] == 1
    entry = log["endpoints_tried"][-1]
    assert entry["endpoint"] == "zid_variant_detail_public" and entry["status"] == "ran" and "no_variants=1" in entry["error"]


def test_supplement_breaker_trips_on_consecutive_failures_but_not_on_empty_200s():
    items = [_listing(i) for i in range(50)]
    calls = []

    async def failing(listing):
        calls.append(listing["id"])
        return 429, None

    log = {"endpoints_tried": []}
    _run(crawlers._zid_variant_detail_supplement(failing, items, log, "public"))
    assert len(calls) == fetch_policy.SUPPLEMENT_ABORT_AFTER
    assert log["endpoints_tried"][-1]["error"].count("aborted_after_consecutive") == 1

    calls.clear()

    async def empty(listing):
        calls.append(listing["id"])
        return 200, {"variants": []}

    log = {"endpoints_tried": []}
    _run(crawlers._zid_variant_detail_supplement(empty, [_listing(i) for i in range(50)], log, "public"))
    assert len(calls) == 50  # a 200 with no variants is an answer, not a transport failure


def test_supplement_respects_cap():
    items = [_listing(i) for i in range(5)]

    async def fetch(listing):
        return 200, {"variants": [_variant("v", "s", 1.0, 1)]}

    log = {"endpoints_tried": []}
    _run(crawlers._zid_variant_detail_supplement(fetch, items, log, "public", cap=2))
    assert log["variant_detail_fetched"] == 2 and log["variant_detail_skipped_cap"] == 3


def test_merchant_rows_expand_variants_with_their_own_price_stock_and_sold_counter():
    parent = _listing(1, variants=[_variant("v1", "9003579308936", 8.3, 202, 61),
                                   _variant("v2", "9003579308936carton", 99.6, 3, 43)])
    parent["sold_products_count"] = 1961
    rows = crawlers._zid_merchant_rows([parent, _listing(2, has_options=False)])
    assert [r["sku"] for r in rows] == ["9003579308936", "9003579308936carton", "Z.2"]
    v1, v2, single = rows
    assert v1["price"] == 8.3 and v1["qty_available"] == 202 and v1["sold_count"] == 61 and v1["_resolved_child"] is True
    assert v2["price"] == 99.6 and v2["qty_available"] == 3 and v2["sold_count"] == 43
    assert v1["_parent_sku"] == "Z.1" and v1["listing_id"] == "p1" and v1["variant_id"] == "v1"
    assert v1["is_taxable"] is True  # inherited from the listing
    assert single["_resolved_child"] is None and single["variant_id"] == "root"


def test_unresolved_merchant_parent_still_flagged_when_detail_is_missing():
    rows = crawlers._zid_merchant_rows([_listing(1)])
    assert len(rows) == 1 and rows[0]["_unresolved_parent"] is True and rows[0]["has_options"] is True


def test_extract_zid_sold_count_reads_sold_products_count():
    assert crawlers._extract_zid_sold_count({"sold_products_count": 5}) == 5
    assert crawlers._extract_zid_sold_count({"sold_products_count": None}) is None
    assert crawlers._extract_zid_sold_count({"sold_quantity": 2, "sold_products_count": 5}) == 2


def test_salla_pacing_floor_spaces_requests_between_1_5_and_3_seconds():
    fetch_policy.reset_hosts()
    fetch_policy.set_host_floor("https://cutepets.com.sa/en/api/v1/products", fetch_policy.SALLA_PACING_FLOOR)
    _, state = fetch_policy._host("https://cutepets.com.sa/x")
    assert state["floor"] == fetch_policy.SALLA_PACING_FLOOR == 2.25
    spacings = []
    for _ in range(200):
        state["next_at"] = 0.0
        _run(fetch_policy._pace(state))
        spacings.append(state["next_at"] - time.monotonic())
    assert 1.4 <= min(spacings) and max(spacings) <= 3.1
    # Zid hosts keep the fast default.
    _, zid = fetch_policy._host("https://mowkly.com/api/v1/products")
    zid["next_at"] = 0.0
    _run(fetch_policy._pace(zid))
    assert zid["next_at"] - time.monotonic() < 0.3
    fetch_policy.reset_hosts()

"""Price recommendations and approved Zid price changes (17 Oct 2026)."""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pricing_advisor as pa  # noqa: E402
import zid_prices  # noqa: E402

ROW = {"sku": "A", "price": 115.0, "cost": 50.0, "price_basis": "storefront_inc_vat", "competitor_min_price": 100.0,
       "market_median_price": 105.0, "in_stock": True, "my_units_sold": 10, "identity_check": None}


def test_margin_uses_net_of_vat_price():
    assert pa.margin_pct(115.0, 50.0, 1.15) == 50.0                   # net 100, cost 50
    assert pa.margin_pct(100.0, 50.0, 1.0) == 50.0                    # non-taxable
    assert pa.floor_price(50.0, 1.15, 15.0) == round(50 * 1.15 / 0.85, 2)


def test_lower_matches_cheapest_and_reports_breakeven():
    r = pa.recommend(ROW)
    assert r["action"] == "lower" and r["recommended_price"] == 100.0 and r["rank_after"] == 1
    assert r["margin_after_pct"] == round((100 / 1.15 - 50) / (100 / 1.15) * 100, 1)
    assert r["profit_change_30d"] == round(-15 / 1.15 * 10, 2)
    assert r["breakeven_extra_sales_pct"] == round(((115 / 1.15 - 50) / (100 / 1.15 - 50) - 1) * 100, 1)


def test_margin_floor_stops_or_limits_a_cut():
    held = pa.recommend({**ROW, "cost": 95.0, "price": 125.0}, {"min_margin_pct": 15})
    assert held["action"] == "hold" and "margin floor" in held["reason"]       # floor 128.53 > price
    part = pa.recommend({**ROW, "cost": 80.0}, {"min_margin_pct": 15})      # floor 108.24: between
    assert part["action"] == "lower" and part["recommended_price"] == 108.25 and part["recommended_price"] >= part["floor_price"]


def test_raise_when_clearly_cheapest_and_stay_cheapest():
    r = pa.recommend({**ROW, "price": 80.0})
    assert r["action"] == "raise" and 80 < r["recommended_price"] < 100 and r["rank_after"] == 1
    assert pa.recommend({**ROW, "price": 99.0})["action"] == "hold"           # 1% gap: not worth moving


def test_guards_before_any_price_move():
    assert pa.recommend({**ROW, "in_stock": False})["action"] == "restock"
    assert pa.recommend({**ROW, "identity_check": "own_price_far_above_market"})["action"] == "check_identity"
    assert pa.recommend({**ROW, "cost": 200.0})["action"] == "check_cost"
    assert pa.recommend({**ROW, "competitor_min_price": None})["action"] == "no_market"
    assert pa.recommend({**ROW, "cost": None})["action"] == "lower"           # no cost: no floor, still a match


def test_suggestion_names_the_stores_it_rests_on():
    offers = [{"store_id": "z", "store_name": "Zarafa", "price": 100.0, "used": True},
              {"store_id": "l", "store_name": "Lana", "price": 100.0, "used": True},
              {"store_id": "h", "store_name": "Hobba", "price": 112.0, "used": True},
              {"store_id": "p", "store_name": "Petsy", "price": 90.0, "used": False, "reason": "out_of_stock"}]
    r = pa.recommend({**ROW, "competitor_offers": offers})
    assert [o["store_name"] for o in r["based_on"]] == ["Zarafa", "Lana"]    # out-of-stock Petsy never sets it
    assert len(r["competitors"]) == 4 and "Zarafa / Lana at 100.0" in r["reason"]
    assert pa.recommend({**ROW, "price": 80.0, "competitor_offers": offers})["based_on"][0]["store_name"] == "Zarafa"
    assert pa.recommend({**ROW, "competitor_min_price": None, "competitor_offers": offers[3:]})["based_on"] == []


def test_zid_plan_divides_vat_and_keeps_list_price_on_sale():
    mp = {"sku": "A", "listing_id": "L1", "variant_id": "V1", "price": 115.0, "price_basis": "storefront_inc_vat"}
    p = zid_prices.plan(mp, 103.5)
    assert p["ok"] and p["product_id"] == "V1" and p["body"] == {"price": 90.0, "sale_price": None}
    on_sale = {**mp, "variant_id": "root", "original_price": 115.0, "sale_price": 110.0}
    p = zid_prices.plan(on_sale, 103.5)
    assert p["product_id"] == "L1" and p["body"] == {"sale_price": 90.0}
    assert zid_prices.plan(mp, 50.0)["ok"] is False                          # > 40 % in one step
    assert zid_prices.plan({**mp, "listing_id": None, "variant_id": None}, 110.0)["ok"] is False


class _Resp:
    def __init__(self, code, body=None, text=""):
        self.status_code, self._body, self.text = code, body or {}, text

    def json(self):
        return self._body


class _Http:
    def __init__(self, patch_code=200, after=90.0):
        self.calls, self.patch_code, self.after = [], patch_code, after

    async def patch(self, url, json=None, headers=None):
        self.calls.append(("PATCH", url, json))
        return _Resp(self.patch_code, text="Unauthenticated" if self.patch_code == 401 else "")

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, None))
        return _Resp(200, {"price": self.after})


def test_apply_confirms_records_and_reports_refusals(monkeypatch):
    from motor.motor_asyncio import AsyncIOMotorClient
    from test_p0_my_products_baseline import _loopback_mongo_url
    monkeypatch.setenv("ZID_API_TOKEN", "t")
    monkeypatch.setenv("ZID_STORE_ID", "s")

    async def scenario():
        client = AsyncIOMotorClient(_loopback_mongo_url())
        db = client["zp_" + uuid.uuid4().hex]
        try:
            await db.my_products.insert_one({"sku": "A", "listing_id": "L1", "variant_id": "root", "price": 115.0,
                                             "price_basis": "storefront_inc_vat"})
            ok = await zid_prices.apply(db, "A", 103.5, "owner@x", http=_Http())
            refused = await zid_prices.apply(db, "A", 103.5, "owner@x", http=_Http(patch_code=401))
            local = await zid_prices.apply(db, "A", 10.0, "owner@x", http=_Http())
            log = await zid_prices.history(db)
            return ok, refused, local, log
        finally:
            await client.drop_database(db.name)
            client.close()
    ok, refused, local, log = asyncio.run(scenario())
    assert ok["ok"] and ok["status"] == "confirmed" and ok["merchant_price"] == 90.0
    assert refused["status"] == "refused_by_zid" and "write permission" in refused["reason"]
    assert local["status"] == "refused"
    assert [r["status"] for r in log] == ["refused_locally", "refused_by_zid", "confirmed"]
    assert all(r["approved_by"] == "owner@x" for r in log)

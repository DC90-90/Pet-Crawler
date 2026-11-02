"""The client's two tables (2 Nov 2026).

The client found the analysis pages hard to use and asked for two plain
tables, one row per product of his store:

* sales: product, brand, category, his units sold, and the units sold by
  every tracked store including his;
* prices: product, brand, category, his price, and each competitor's price
  in its own column.

Both read the Market Share dataset (the same rows, matches and units the
Market pages show), so the two can never disagree. Units are measured per
store from stock movement or sold counters; a store with no reading for the
period counts as unknown (None), never as zero.
"""


def _store_price(sellers):
    """One price per store, as [price, out_of_stock]: the cheapest in-stock
    offer; else the last price seen before the store ran out. A price
    withheld for any other reason (stale, a different pack) is not shown."""
    in_stock = [s["price"] for s in sellers if s.get("price")]
    if in_stock:
        return [min(in_stock), False]
    oos = [s["historical_price"] for s in sellers
           if s.get("price_excluded_reason") == "out_of_stock" and s.get("historical_price")]
    if oos:
        return [round(float(min(oos)), 2), True]
    return None


def build(ds):
    stores = ds.get("stores") or []
    own = next((s for s in stores if s.get("is_own")), None)
    competitors = [{"store_id": s["store_id"], "store_name": s["store_name"]}
                   for s in stores if not s.get("is_own")]
    column = {c["store_id"]: i for i, c in enumerate(competitors)}
    rows = []
    for r in ds.get("my_products") or []:
        by_store = {}
        own_offer = None
        for s in r.get("sellers") or []:
            if s.get("is_own"):
                own_offer = s
            else:
                by_store.setdefault(s["store_id"], []).append(s)
        # Keyed by the store's position in `competitors`: 2,700 rows x 11
        # stores of full store ids tripled the answer.
        prices = {str(column[sid]): p for sid, offers in by_store.items()
                  if sid in column and (p := _store_price(offers))}
        rows.append({
            "key": r.get("canonical_key") or r.get("sku"),
            "sku": r.get("sku"),
            "barcode": r.get("barcode") or "",
            "name_ar": r.get("name_ar") or "",
            "name_en": r.get("name_en") or "",
            "brand": r.get("brand") or "",
            "category": r.get("category") or "",
            "my_units": r.get("my_units"),
            # 1,434 of the 1,473 products without own units on 2 Nov 2026 had
            # no stock: nothing moved to measure. Shown as out of stock, not
            # as a missing number.
            "my_out_of_stock": bool(own_offer) and (own_offer.get("in_stock") is False
                                                    or own_offer.get("qty_available") == 0),
            "market_units": r.get("market_units"),
            "stores_with_units": r.get("sellers_with_sales") or 0,
            "stores_selling": r.get("sellers_total") or 0,
            "my_price": r.get("my_price"),
            "prices": prices,
        })
    return {
        "window": ds.get("window"),
        "own_store": {"store_id": own["store_id"], "store_name": own["store_name"]} if own else None,
        "competitors": competitors,
        "rows": rows,
    }

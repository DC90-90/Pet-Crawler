"""Price recommendations (17 Oct 2026): what to charge for each own product,
from the same verified competitor cohort as every price figure, the product's
cost and a minimum margin the owner sets.

Prices are shelf prices including VAT (15%) unless the product is non-taxable;
costs are purchase costs excluding VAT. Margin is (net price - cost) / net
price, where net price = shelf price / 1.15 for a taxable product.

Each product gets one action:
  lower        a competitor is cheaper: match the cheapest in-stock seller,
               never below the margin floor
  raise        I am the cheapest by a clear gap: move up to just under the
               next seller, still the cheapest
  hold         already well placed, or the margin floor stops any move
  check_cost   the cost looks wrong (above the price, or under a tenth of it)
  check_identity  my price is far from every seller of this barcode
  restock      out of stock: price later
  no_market    no competitor sells it now
Profit change is at the current sales volume (no demand model): a real
estimate of what the price alone changes, labelled as such. A price cut also
reports the extra sales it needs to keep the same profit (break-even).
"""
from datetime import datetime, timezone

VAT = 0.15
DEFAULTS = {"min_margin_pct": 15.0, "raise_gap_pct": 3.0, "undercut_sar": 0.0}
NON_TAXABLE_BASES = ("merchant_non_taxable",)


def vat_factor(row):
    return 1.0 if str(row.get("price_basis") or "") in NON_TAXABLE_BASES else 1 + VAT


def margin_pct(shelf_price, cost, factor):
    if not shelf_price or not cost:
        return None
    net = shelf_price / factor
    return round((net - cost) / net * 100, 1)


def floor_price(cost, factor, min_margin_pct):
    """Lowest shelf price that keeps min_margin_pct."""
    if not cost:
        return None
    return round(cost * factor / (1 - min_margin_pct / 100), 2)


def _round_down(value, step=0.05):
    return round(int(value / step + 1e-9) * step, 2)


def _round_up(value, step=0.05):
    import math
    return round(math.ceil(value / step - 1e-9) * step, 2)


def recommend(row, settings=None):
    """One recommendation for a My Products dataset row."""
    s = {**DEFAULTS, **(settings or {})}
    price = row.get("price")
    cost = row.get("cost") if (row.get("cost") or 0) > 0 else None
    factor = vat_factor(row)
    lowest = row.get("competitor_min_price")
    out = {"sku": row.get("sku"), "name_ar": row.get("name_ar"), "name_en": row.get("name_en"),
           "image_url": row.get("image_url"), "barcode": row.get("barcode"), "product_url": row.get("product_url"),
           "price": price, "cost": cost, "vat_included": factor > 1,
           "competitor_min_price": lowest, "market_median_price": row.get("market_median_price"),
           "num_sellers": row.get("num_priced_competitors"), "price_rank": row.get("price_rank"),
           "price_rank_of": row.get("price_rank_of"), "units_30d": row.get("my_units_sold"),
           "in_stock": row.get("in_stock"), "quantity": row.get("my_quantity"),
           "margin_now_pct": margin_pct(price, cost, factor),
           "floor_price": floor_price(cost, factor, s["min_margin_pct"]) if cost else None}

    def done(action, target=None, reason=""):
        out.update(action=action, recommended_price=target, reason=reason)
        if target and price:
            out.update(change_sar=round(target - price, 2), change_pct=round((target - price) / price * 100, 1),
                       margin_after_pct=margin_pct(target, cost, factor),
                       rank_after=1 if lowest and target <= lowest else None)
            units = out["units_30d"]
            out["profit_change_30d"] = round((target - price) / factor * units, 2) if units is not None else None
            if cost and target < price:
                # A cut pays off only if volume grows: the extra sales needed
                # for the same profit at the new unit margin.
                unit_now, unit_after = price / factor - cost, target / factor - cost
                out["breakeven_extra_sales_pct"] = (round((unit_now / unit_after - 1) * 100, 1)
                                                    if unit_after > 0 else None)
        return out

    if not price:
        return done("hold", reason="no current price")
    if row.get("in_stock") is False:
        return done("restock", reason="out of stock in my store")
    if row.get("identity_check"):
        return done("check_identity", reason=row["identity_check"])
    if cost and (cost * factor > price * 1.0 or cost * factor < price * 0.1):
        return done("check_cost", reason="cost above the price" if cost * factor > price else "cost under a tenth of the price")
    if not lowest:
        return done("no_market", reason="no competitor sells it in stock")
    floor = out["floor_price"]
    if price > lowest:
        target = _round_down(lowest - s["undercut_sar"]) if s["undercut_sar"] else lowest
        if floor and target < floor:
            if floor >= price:
                return done("hold", reason=f"matching {lowest} would go below the {s['min_margin_pct']:g}% margin floor")
            return done("lower", _round_up(floor),
                        reason=f"closer to the cheapest ({lowest}) without going below the {s['min_margin_pct']:g}% margin")
        return done("lower", target, reason=f"match the cheapest in-stock seller ({lowest})")
    gap_pct = (lowest - price) / price * 100
    if gap_pct >= s["raise_gap_pct"]:
        target = _round_down(lowest * 0.99)
        if target > price:
            return done("raise", target, reason=f"you are {gap_pct:.1f}% under the next seller ({lowest}); stay cheapest at a higher price")
    return done("hold", reason="already the cheapest or tied")


def summarize(recs):
    by = {}
    for r in recs:
        by[r["action"]] = by.get(r["action"], 0) + 1
    gain = sum(r.get("profit_change_30d") or 0 for r in recs if r["action"] == "raise")
    cost_missing = sum(1 for r in recs if r["price"] and not r["cost"])
    return {"by_action": by, "raise_profit_30d": round(gain, 2), "products": len(recs),
            "without_cost": cost_missing, "computed_at": datetime.now(timezone.utc).isoformat()}

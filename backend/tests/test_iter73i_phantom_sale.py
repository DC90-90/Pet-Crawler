"""iter73i — Phantom Zid sale_price fix (Aug 3 2026).

Client-reported bug (screenshot Aug 3): SKU 8595602540877 shows 180.17 SAR in
Daleel's "My Store" (Price Intel → My Advantage) while the actual shopper-
facing shelf price on tqween.com is 237.02 SAR. Neither number is "without
VAT" per se — 180.17 IS the merchant `sale_price` × 1.15 — but the merchant's
`sale_price` is a PHANTOM: it does not appear on the public storefront, and
the shopper never sees it. The shopper pays 237.02 = list_price × 1.15.

Root cause: when the storefront overlay ran successfully for OTHER SKUs but
did not carry this SKU, `resolve_own_price` fell into the merchant path and
grossed up `merchant_sale_price` — the exact phantom the storefront proves
doesn't exist.

Fix: pass `storefront_authoritative=True` from the sync loop when the
storefront index has at least one entry. When authoritative AND no `sf_hit`
for a given row, `resolve_own_price` anchors on the LIST price only, drops
the merchant sale, and tags basis `merchant_hidden_from_storefront_inc_vat`
(or `merchant_hidden_non_taxable` when is_taxable=False).

Result: SKU 8595602540877's my_products.price becomes 237.02 (= 206.10 ×
1.15), matching the website exactly.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import crawlers as _cr
from crawlers import resolve_own_price, KSA_VAT_RATE


# ── canonical repro of the client-reported case ────────────────────────────
def test_iter73i_repro_sku_8595602540877_phantom_sale():
    """Client screenshot Aug 3: storefront shows 237.02 SAR, Daleel shows
    180.17 SAR. After iter73i, when the storefront ran (authoritative=True)
    but this SKU is missing from it, we ignore the phantom merchant sale
    (156.67) and gross the merchant list (206.10) — reconciling to 237.02.
    """
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,                   # storefront didn't carry this SKU
        merchant_price=156.67,         # phantom "sale" price (ex-VAT)
        merchant_sale_price=156.67,    # phantom sale (ex-VAT)
        merchant_list_price=206.10,    # actual list price (ex-VAT)
        is_taxable=None,               # tristate unknown, Saudi retail default
        storefront_authoritative=True, # NEW iter73i flag
    )
    # 206.10 × 1.15 = 236.99, rounds to 237.01 or 237.02 depending on
    # accumulation. Assert 236.99 ≤ price ≤ 237.02 to keep the test tight
    # without being brittle on the last cent.
    assert 236.99 <= price <= 237.02, f"got {price!r}, expected ~237.02"
    assert orig == price, "list-anchored branch must set original_price == price"
    assert sale is None, "phantom sale must be dropped"
    assert basis == "merchant_hidden_from_storefront_inc_vat"


# ── authoritative branch: no sf_hit, list wins over phantom sale ───────────
def test_authoritative_no_sf_hit_uses_list_not_sale():
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,
        merchant_price=80.0,           # would be raw price (sale OR list)
        merchant_sale_price=80.0,      # phantom sale
        merchant_list_price=100.0,     # real list price
        is_taxable=None,
        storefront_authoritative=True,
    )
    assert price == round(100.0 * (1 + KSA_VAT_RATE), 2), \
        "authoritative branch must gross LIST price, not sale price"
    assert sale is None
    assert orig == price
    assert basis == "merchant_hidden_from_storefront_inc_vat"


def test_authoritative_no_list_falls_back_to_price():
    """When merchant_list_price is None/0, effective anchors on merchant_price
    (backwards compat: pre-list-price callers still work)."""
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,
        merchant_price=90.0,
        merchant_sale_price=None,
        merchant_list_price=None,      # not supplied
        is_taxable=None,
        storefront_authoritative=True,
    )
    assert price == round(90.0 * (1 + KSA_VAT_RATE), 2)
    assert basis == "merchant_hidden_from_storefront_inc_vat"


def test_authoritative_non_taxable_keeps_ex_vat():
    """Explicit is_taxable=False on an authoritative-hidden row must NOT
    gross up — the tag is different so operators can audit both branches."""
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,
        merchant_price=50.0,
        merchant_sale_price=45.0,      # phantom sale
        merchant_list_price=60.0,
        is_taxable=False,
        storefront_authoritative=True,
    )
    assert price == 60.0                # LIST, un-VAT-inflated
    assert sale is None
    assert orig == 60.0
    assert basis == "merchant_hidden_non_taxable"


# ── non-authoritative fallback (storefront empty / didn't run) ─────────────
def test_non_authoritative_preserves_merchant_sale_semantics():
    """When storefront_authoritative=False (default), the OLD iter73d
    behaviour is preserved: merchant sale_price × 1.15 is honoured. We only
    tighten when the storefront is authoritative — never regress the
    small-store / storefront-fetch-failure case."""
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,
        merchant_price=156.67,
        merchant_sale_price=156.67,
        merchant_list_price=206.10,
        is_taxable=None,
        storefront_authoritative=False,   # storefront couldn't be fetched
    )
    assert price == round(156.67 * (1 + KSA_VAT_RATE), 2)   # 180.17
    assert sale == round(156.67 * (1 + KSA_VAT_RATE), 2)
    assert orig == round(206.10 * (1 + KSA_VAT_RATE), 2)    # 236.99
    assert basis == "merchant_assumed_inc_vat"


def test_non_authoritative_default_flag_is_false():
    """Default value of storefront_authoritative is False — pre-iter73i
    callers keep working."""
    price, sale, orig, basis = resolve_own_price(
        sf_hit=None,
        merchant_price=100.0,
        merchant_sale_price=90.0,
        merchant_list_price=100.0,
        is_taxable=None,
        # storefront_authoritative NOT passed
    )
    # Must NOT be the hidden branch
    assert basis != "merchant_hidden_from_storefront_inc_vat"
    assert basis == "merchant_assumed_inc_vat"


# ── sf_hit always wins ─────────────────────────────────────────────────────
def test_sf_hit_beats_authoritative_flag():
    """When the storefront DID carry this SKU, use its shelf price. The
    authoritative flag doesn't matter — the sf_hit branch takes precedence."""
    price, sale, orig, basis = resolve_own_price(
        sf_hit=(237.02, 279.00),        # shelf=237.02, list=279.00
        merchant_price=156.67,
        merchant_sale_price=156.67,
        merchant_list_price=206.10,
        is_taxable=None,
        storefront_authoritative=True,
    )
    assert price == 237.02
    assert sale == 237.02              # on-sale: shelf < list
    assert orig == 279.00
    assert basis == "storefront_inc_vat"


# ── call-site plumbing: sync_own_store_prices ──────────────────────────────
def test_sync_passes_storefront_authoritative_flag():
    """Static shape check: `sync_own_store_prices` must pass
    `storefront_authoritative=` to `resolve_own_price` so the phantom-sale
    fix actually fires at run time."""
    src = (BACKEND / "crawlers.py").read_text()
    # find the sync's call to resolve_own_price
    a = src.index("async def sync_own_store_prices")
    b = src.index("# ── Write through to db.products", a)
    body = src[a:b]
    assert "storefront_authoritative=" in body, \
        "sync loop must plumb storefront_authoritative to resolve_own_price"
    # and the flag must derive from the sf_index (not hardcoded True/False)
    assert "sf_index.get(\"by_sku\")" in body or "sf_index.get('by_sku')" in body, \
        "storefront_authoritative must derive from sf_index emptiness"


# ── call-site plumbing: own_store_vat_backfill ─────────────────────────────
def test_backfill_passes_storefront_authoritative_flag():
    """The admin backfill endpoint is only reachable AFTER a successful
    storefront fetch (see the 502 guard), so it must pass
    `storefront_authoritative=True` unconditionally — same fix, applied to
    the migration path."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def own_store_vat_backfill")
    b = src.index("basis_counts[basis] = basis_counts.get", a)
    body = src[a:b]
    assert "storefront_authoritative=True" in body, \
        "backfill must pass storefront_authoritative=True (storefront is proven " \
        "authoritative by the fetch guard above)"


# ── basis_counts registry is updated ───────────────────────────────────────
def test_basis_counts_registry_has_new_basis_keys():
    """`sync_own_store_prices` initialises `basis_counts` with a fixed set of
    keys so the reporting dashboard renders zeroes rather than blanks. The
    two new iter73i bases must be present so ops can spot phantom-sale
    corrections at a glance."""
    src = (BACKEND / "crawlers.py").read_text()
    a = src.index("basis_counts = {\"storefront_inc_vat\"")
    b = src.index("}", a)
    block = src[a:b]
    assert "merchant_hidden_from_storefront_inc_vat" in block
    assert "merchant_hidden_non_taxable" in block

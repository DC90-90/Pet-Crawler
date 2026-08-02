"""iter73d — "my prices should be with VAT in all tabs and in all products".

Client observation (Feb 2026): my-store prices on some tabs displayed
inc-VAT while others displayed ex-VAT. Root cause: `resolve_own_price` used
to leave rows at ex-VAT when Zid's `is_taxable` field was `None`, and it
threw away the LIST price on on-sale items — so the strikethrough / original
price could never render inc-VAT for those products either.

Fix policy (Saudi retail default):
  1. is_taxable None  → gross up (basis `merchant_assumed_inc_vat`)
     — never leave a Saudi retail price ex-VAT on a guess.
  2. Preserve the merchant's LIST price through the pipeline via a new
     `merchant_list_price` argument to the resolver, so `original_price` is
     always the pre-sale reference at the SAME VAT basis as `price`.
  3. Resolver returns a 4-tuple `(price, sale, original, basis)` so callers
     never have to reconstruct the strikethrough after the fact.

These tests lock in the write-side invariants; the read-side stays as-is
because the fields it reads (my_products.price / product_snapshots.price)
are now guaranteed inc-VAT by construction.
"""
import pytest
import crawlers


R = crawlers.resolve_own_price
V = crawlers.KSA_VAT_RATE


# ── the resolver: 4-tuple contract ─────────────────────────────────────────
def test_signature_is_now_four_tuple():
    r = R((100.0, 100.0))
    assert isinstance(r, tuple) and len(r) == 4
    assert r == (100.0, None, 100.0, "storefront_inc_vat")


def test_storefront_sale_carries_list_as_original():
    """A shelf price BELOW the list price = a genuine sale. `original`
    carries the LIST so the strikethrough renders truthfully."""
    r = R((80.0, 100.0))
    assert r == (80.0, 80.0, 100.0, "storefront_inc_vat")


def test_merchant_taxable_grosses_price_sale_and_list():
    """A taxable on-sale merchant row: caller passes list explicitly so
    original is the LIST × 1.15 (not the sale × 1.15)."""
    r = R(None, merchant_price=80, merchant_sale_price=80,
          merchant_list_price=100, is_taxable=True)
    assert r == (92.0, 92.0, 115.0, "merchant_computed_inc_vat")


def test_merchant_taxable_without_list_defaults_to_effective_price():
    """Backwards-compatible: pre-iter73d callers didn't pass merchant_list_
    price. Original defaults to `price` (same as the pre-iter73d behaviour
    where original was never distinct from price — no regression)."""
    r = R(None, merchant_price=100, is_taxable=True)
    assert r == (115.0, None, 115.0, "merchant_computed_inc_vat")


def test_unknown_tax_grosses_up_with_new_basis():
    """iter73d Saudi default — is_taxable=None now grosses up. The tag
    switches to `merchant_assumed_inc_vat` so operators can find these
    rows in the VAT-audit surface."""
    r = R(None, merchant_price=30, is_taxable=None)
    assert r == (34.5, None, 34.5, "merchant_assumed_inc_vat")


def test_non_taxable_still_flat():
    """Explicit is_taxable=False stays FLAT — no auto-inflation for the
    genuinely exempt subset (books, some medical supplies, etc.). The
    basis tag remains `merchant_non_taxable`."""
    r = R(None, merchant_price=40, is_taxable=False)
    assert r == (40.0, None, 40.0, "merchant_non_taxable")


def test_no_ex_vat_basis_ever_reaches_the_caller_for_taxable_paths():
    """The old `merchant_unknown_tax` basis DIVIDES prices into VAT-honest
    and VAT-dishonest buckets on the read side. It's retired for taxable /
    unknown-tax paths — only the explicit `merchant_non_taxable` bucket may
    now carry an ex-VAT price. Guard against a future refactor accidentally
    reintroducing it."""
    known = set()
    for is_tax in (True, False, None):
        for sf in [None, (10.0, 12.0)]:
            for m_p, m_s, m_l in [(100, None, None), (80, 80, 100), (0, 0, 0)]:
                r = R(sf, merchant_price=m_p, merchant_sale_price=m_s,
                      merchant_list_price=m_l, is_taxable=is_tax)
                known.add(r[3])
    assert "merchant_unknown_tax" not in known, \
        f"legacy basis leaked back in: {known}"
    assert known <= {"storefront_inc_vat", "merchant_computed_inc_vat",
                     "merchant_non_taxable", "merchant_assumed_inc_vat"}


# ── merchant catalog: LIST price preserved ─────────────────────────────────
def test_fetch_zid_catalog_preserves_list_price_field():
    """The Merchant-API adapter must set `list_price` on every raw row so
    the resolver's `merchant_list_price` argument has real data to gross up.
    Regression guard against the pre-iter73d shape that collapsed
    `raw.price = sale_price or price` and lost the list."""
    from pathlib import Path
    src = Path(crawlers.__file__).read_text()
    a = src.index("async def _fetch_zid_api_catalog")
    b = src.index("\nasync def ", a + 1)
    body = src[a:b]
    assert '"list_price": _list' in body, \
        "merchant catalog must carry list_price separately from the effective price"
    # AND the effective price is `_sale if _sale else _list`, not a wildcard
    assert "_eff = _sale if _sale and _sale > 0 else _list" in body


# ── sync loop / snapshot writer: 4-tuple wired end-to-end ─────────────────
def test_sync_loop_uses_four_tuple_and_forwards_list_price():
    from pathlib import Path
    src = Path(crawlers.__file__).read_text()
    # `_zid_id` branch — the merchant-API fast-path
    a = src.index('if raw.get("_zid_id"):')
    b = src.index("basis_counts[price_basis]", a)
    body = src[a:b]
    assert "merchant_list_price=raw.get(\"list_price\")" in body, \
        "merchant_list_price argument must be forwarded from the raw row"
    assert "price_v, sale_v, orig_v, price_basis = resolve_own_price(" in body, \
        "sync must consume the new 4-tuple"


def test_own_resolved_price_is_four_tuple():
    """`own_resolved_price` is the shared queue the snapshot writer reads
    from — must carry the LIST price so snapshots can emit
    `original_price` at the same VAT basis."""
    from pathlib import Path
    src = Path(crawlers.__file__).read_text()
    a = src.index("own_resolved_price[_resolved_sku] = (")
    body = src[a:a + 200]
    # 4 tuple elements: price, sale_price, original_price, price_basis
    assert 'norm.get("price")' in body
    assert 'norm.get("sale_price")' in body
    assert 'norm.get("original_price")' in body
    assert "price_basis" in body


def test_snapshot_writer_uses_list_price_for_original():
    """The iter73c snapshot writer used `price` for both effective and
    original when there was no sale — losing the LIST on merchant rows that
    HAD one. iter73d unpacks the 4-tuple and preserves list separately."""
    from pathlib import Path
    src = Path(crawlers.__file__).read_text()
    a = src.index("_res = own_resolved_price.get(sku)")
    b = src.index("snap_docs.append({", a)
    body = src[a:b]
    assert "list_price_v = _res[2] if _res else None" in body, \
        "writer must unpack the list_price element (index 2) of the 4-tuple"
    assert "price_basis_v = _res[3]" in body, \
        "writer must unpack basis from index 3 (was 2 pre-iter73d)"
    # and the discount arithmetic uses LIST, not effective
    assert "_snap_original = round(_list_v, 2)" in body


# ── invariant: no display path can show ex-VAT for is_taxable=None ───────
def test_default_saudi_policy_never_yields_ex_vat_for_unknown_tax():
    """For any merchant price with is_taxable=None, the returned `price`
    must equal input × 1.15 (within rounding). This is the guarantee behind
    "my prices should be with VAT in all tabs"."""
    for raw_price in [10, 39.99, 100, 147.83, 999.5]:
        got = R(None, merchant_price=raw_price, is_taxable=None)
        expected = round(raw_price * (1 + V), 2)
        assert got[0] == expected, f"raw={raw_price}: got {got[0]}, expected {expected}"
        assert got[3] == "merchant_assumed_inc_vat"


def test_backfill_endpoint_persists_original_price():
    """The vat-backfill endpoint must ALSO write the newly-preserved
    original_price into my_products so downstream reads pick it up
    without waiting for the next sync cycle."""
    from pathlib import Path
    src = Path("/app/backend/server.py").read_text()
    a = src.index("async def own_store_vat_backfill(")
    b = src.index("\n# ── iter54", a)
    body = src[a:b]
    assert '"original_price": c["after_original_price"]' in body, \
        "backfill must persist after_original_price into my_products"
    assert "new_original" in body and "after_original_price" in body, \
        "backfill must capture new_original from resolve_own_price 4-tuple"

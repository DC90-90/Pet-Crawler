"""iter73p — Legacy-basis defensive gross-up + diagnostic endpoint
(Aug 3 2026).

Client (very frustrated) re-reported that "still showing my prices without
VAT" for SKU 8595602540877 and 6 other Zid own-store SKUs even after the
previous iter73i/l heal fixes were deployed.

Diagnosis: the iter73i read-side heal only fires when
`original_price > price × 1.005`. It does NOT fire on legacy rows written
BEFORE iter73d guaranteed inc-VAT — those rows carry `price_basis =
"merchant_unknown_tax"` (or empty/None) with an ex-VAT `price` and no
distinct `original_price`. The heal fell through to the "trust as-written"
branch and returned the ex-VAT number.

iter73p fix in `_effective_own_price`:
  1. Whitelist of KNOWN inc-VAT / explicitly-non-taxable basis tags.
  2. Any row whose basis is NOT in that whitelist AND has a positive
     effective price is treated as legacy ex-VAT and grossed by 1.15.
  3. Storefront and phantom-sale branches unchanged (still take
     precedence).

Also NEW: `/api/admin/own-sku-diagnose?sku=<sku>` — read-only endpoint
that returns the raw my_products row, latest own snapshot, and the
branch `_effective_own_price` took, so future "wrong price" reports can
be triaged in one HTTP call.
"""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import server  # noqa: E402


eop = server._effective_own_price


# ── legacy basis heals ─────────────────────────────────────────────────────
def test_legacy_empty_basis_grosses_by_115():
    """A my_products row with an empty basis (pre-iter73d import, no VAT
    tag) MUST be grossed by 1.15. This is the root cause of the client's
    re-reported bug."""
    mp = {"sku": "X", "price": 180.17, "sale_price": 0, "price_basis": ""}
    got = eop(mp)
    assert got == round(180.17 * 1.15, 2) == 207.20, got


def test_legacy_none_basis_grosses_by_115():
    mp = {"sku": "X", "price": 100.0, "sale_price": 0, "price_basis": None}
    assert eop(mp) == round(100.0 * 1.15, 2) == 115.0


def test_legacy_missing_basis_grosses_by_115():
    """Row missing the `price_basis` field entirely (very old shape)."""
    mp = {"sku": "X", "price": 100.0}
    assert eop(mp) == 115.0


def test_legacy_merchant_unknown_tax_basis_grosses():
    """The retired basis `merchant_unknown_tax` MUST be treated as ex-VAT
    and grossed. Its whole reason for retirement was the ambiguity — the
    Saudi retail default is taxable."""
    mp = {"sku": "X", "price": 156.67, "sale_price": 0,
          "price_basis": "merchant_unknown_tax"}
    assert eop(mp) == round(156.67 * 1.15, 2) == 180.17


def test_legacy_with_sale_price_uses_sale_grossed():
    """When both `price` and `sale_price` are set on a legacy row, the
    effective (sale_price) is what's grossed."""
    mp = {"sku": "X", "price": 200.0, "sale_price": 150.0, "price_basis": ""}
    assert eop(mp) == round(150.0 * 1.15, 2) == 172.5


# ── known-basis rows are trusted as-written ────────────────────────────────
def test_known_inc_vat_basis_not_double_grossed():
    """iter73d-tagged inc-VAT row already has VAT applied. This branch
    MUST NOT gross a second time — that would produce 180.17 × 1.15 = 207.2
    on a row that's already 180.17 inc-VAT."""
    mp = {"sku": "X", "price": 207.20, "sale_price": 0,
          "price_basis": "merchant_assumed_inc_vat"}
    assert eop(mp) == 207.20


def test_known_computed_inc_vat_basis_not_touched():
    mp = {"sku": "X", "price": 115.0, "sale_price": 0,
          "price_basis": "merchant_computed_inc_vat"}
    assert eop(mp) == 115.0


def test_known_hidden_from_storefront_not_touched():
    mp = {"sku": "X", "price": 237.02, "sale_price": 0,
          "price_basis": "merchant_hidden_from_storefront_inc_vat"}
    assert eop(mp) == 237.02


def test_known_non_taxable_kept_ex_vat():
    """`merchant_non_taxable` is EXPLICITLY ex-VAT (operator flagged the
    product with is_taxable=False in Zid). iter73p must respect that."""
    mp = {"sku": "X", "price": 100.0, "sale_price": 0,
          "price_basis": "merchant_non_taxable"}
    assert eop(mp) == 100.0


def test_known_hidden_non_taxable_kept_ex_vat():
    mp = {"sku": "X", "price": 60.0, "sale_price": 0,
          "price_basis": "merchant_hidden_non_taxable"}
    assert eop(mp) == 60.0


def test_storefront_basis_trusted_as_written():
    """Storefront IS the shopper's view — never touched by the heal."""
    mp = {"sku": "X", "price": 237.02, "sale_price": 0,
          "price_basis": "storefront_inc_vat"}
    assert eop(mp) == 237.02


# ── phantom-sale heal still takes precedence ───────────────────────────────
def test_phantom_sale_still_returns_original():
    """The iter73i phantom-sale heal fires BEFORE the legacy gross-up so
    a row with original > price is not double-processed."""
    mp = {"sku": "8595602540877", "price": 180.17, "sale_price": 180.17,
          "original_price": 237.02, "price_basis": "merchant_assumed_inc_vat"}
    assert eop(mp) == 237.02


# ── inc-VAT basis whitelist is closed & correct ────────────────────────────
def test_inc_vat_basis_whitelist_composition():
    """The whitelist is the SINGLE SOURCE OF TRUTH for which basis values
    escape the legacy gross-up. It must contain EXACTLY the tags iter73
    d/i emit (any addition needs an explicit review — regression fence)."""
    assert server._INC_VAT_TAGS == {
        "storefront_inc_vat",
        "merchant_computed_inc_vat",
        "merchant_assumed_inc_vat",
        "merchant_hidden_from_storefront_inc_vat",
        "merchant_non_taxable",
        "merchant_hidden_non_taxable",
    }, f"whitelist drifted: {server._INC_VAT_TAGS}"


# ── defensive edges ────────────────────────────────────────────────────────
def test_zero_price_row_untouched():
    mp = {"sku": "X", "price": 0, "sale_price": 0, "price_basis": ""}
    assert eop(mp) == 0


def test_none_row_returns_zero():
    assert eop(None) == 0.0


def test_empty_row_returns_zero():
    assert eop({}) == 0.0


# ── diagnostic endpoint contract ───────────────────────────────────────────
def test_diagnostic_endpoint_registered():
    src = (BACKEND / "server.py").read_text()
    assert '@router.get("/admin/own-sku-diagnose")' in src, \
        "diagnostic endpoint must be registered under /api/admin/own-sku-diagnose"
    assert "async def own_sku_diagnose(sku: str = Query" in src


def test_diagnostic_endpoint_super_admin_only():
    """The endpoint returns raw internal data — must be gated to super
    admin only."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def own_sku_diagnose(")
    b = src.index("\n\n\n", a) if "\n\n\n" in src[a:] else len(src)
    body = src[a:b]
    assert 'raise HTTPException(403, "super_admin only")' in body


def test_diagnostic_reports_branch_taken():
    """The endpoint MUST tell operators which of the four `_effective_own
    _price` branches ran for the row — that is the whole point of the
    diagnostic."""
    src = (BACKEND / "server.py").read_text()
    a = src.index("async def own_sku_diagnose(")
    b = src.index("\n\n@router.get", a)
    body = src[a:b]
    # 4 mutually-exclusive branch tags
    for tag in ("storefront_trust_as_written",
                "phantom_sale_heal_returns_original_price",
                "iter73p_legacy_basis_gross_up_by_1.15",
                "known_basis_trust_as_written",
                "no_my_products_row"):
        assert f'"{tag}"' in body or f"'{tag}'" in body or tag in body, \
            f"branch tag '{tag}' missing from diagnostic endpoint"

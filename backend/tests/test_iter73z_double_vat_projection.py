"""iter73z (Aug 10 2026) — double-VAT on the My Products page.

Client screenshots, SKU 3182550702362 (Royal Canin FHN Sensible 15kg):
  * pets-houses.com storefront: **563.50 SAR**
  * product-detail panel (Daleel): 563.5 SAR  ✅
  * My Products table row (Daleel): **648.02 SAR**  ❌  (= 563.50 × 1.15)

Root cause — a PROJECTION bug, not a pricing-rule bug. `_effective_own_price`
decides whether a my_products row is already inc-VAT by reading its
`price_basis` tag: a row tagged `storefront_inc_vat` is trusted as-written,
while a row with NO tag is assumed legacy ex-VAT and grossed by 1.15
(iter73p). Two read paths fetched the my_products rows with a projection that
OMITTED `price_basis` (and `original_price`):

  * `_my_products_rows_compute` (My Products page + its market-position block)
  * `_compute_market_position_summary` (Insights market-position KPI)

so every row arrived with `price_basis == ""` and got grossed a second time.
The product-detail endpoints projected both fields, which is exactly why the
panel and the table disagreed by 15% on the same SKU.

Fence: any `db.my_products.find(...)` projection that selects `price` MUST
also select `price_basis` and `original_price`.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server  # noqa: E402

SRC = Path(server.__file__).read_text()


def _projections():
    """(line_no, projection_text, enclosing_fn_body) per my_products read."""
    out = []
    for m in re.finditer(r"my_products\.find(?:_one)?\(", SRC):
        i = m.end() - 1
        depth, j = 0, i
        while j < len(SRC):
            if SRC[j] == "(":
                depth += 1
            elif SRC[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        head = SRC[:m.start()]
        fn_start = max(head.rfind("\nasync def "), head.rfind("\ndef "))
        nxt = SRC.find("\nasync def ", j)
        nxt2 = SRC.find("\ndef ", j)
        fn_end = min([x for x in (nxt, nxt2) if x != -1] or [len(SRC)])
        out.append((head.count("\n") + 1, SRC[i:j + 1], SRC[fn_start:fn_end]))
    return out


def test_every_price_projection_feeding_the_heal_projects_the_vat_basis():
    """If the enclosing read path calls `_effective_own_price`, its projection
    MUST carry `price_basis` AND `original_price` — otherwise the heal sees a
    tagless row and grosses an already-inc-VAT price by 1.15 again."""
    offenders = []
    for line_no, text, fn_body in _projections():
        if '"price": 1' not in text:
            continue                      # full-document reads are always safe
        if "_effective_own_price(" not in fn_body:
            continue
        if '"price_basis": 1' not in text or '"original_price": 1' not in text:
            offenders.append(line_no)
    assert not offenders, (
        "my_products projections at lines "
        f"{offenders} select `price` without `price_basis`/`original_price` — "
        "_effective_own_price will double-gross those rows by 1.15")


def test_my_products_page_projection_carries_the_basis():
    line = SRC.split("my_products_docs = await db.my_products.find(", 1)[1][:1400]
    assert '"price_basis": 1' in line
    assert '"original_price": 1' in line


def test_market_position_summary_projection_carries_the_basis():
    block = SRC.split("async def _compute_market_position_summary(", 1)[1][:1200]
    assert '"price_basis": 1' in block
    assert '"original_price": 1' in block


# ── the pricing rule itself, on the client's exact numbers ─────────────────
def test_storefront_row_is_never_grossed():
    """The reported case: a storefront-confirmed 563.50 must stay 563.50."""
    row = {"sku": "3182550702362", "price": 563.5, "sale_price": None,
           "original_price": 563.5, "price_basis": "storefront_inc_vat"}
    assert server._effective_own_price(row) == 563.5


def test_dropping_the_basis_is_what_produced_648_02():
    """Documents the defect so nobody 'optimises' the projection again."""
    row = {"sku": "3182550702362", "price": 563.5}      # basis projected away
    assert server._effective_own_price(row) == 648.02


def test_genuine_legacy_row_still_grosses():
    """iter73p behaviour must be preserved for real untagged ex-VAT rows."""
    row = {"sku": "X", "price": 100.0, "price_basis": ""}
    assert server._effective_own_price(row) == 115.0


def test_storefront_sale_price_wins_over_list():
    row = {"price": 600.0, "sale_price": 563.5, "original_price": 600.0,
           "price_basis": "storefront_inc_vat"}
    assert server._effective_own_price(row) == 563.5

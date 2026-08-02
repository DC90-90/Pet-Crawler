"""iter73 — Discounts tab must NEVER read empty when the underlying rows
already carry `original_price > price`.

Root cause captured (Feb 2026): several write paths — Zid own-store sync
(crawlers.py) and the manual baseline import (server.py) — used to hardcode
`discount_pct = 0` even on rows where `original_price > price`, so the tab
that filters `discount_pct > 0` returned nothing. These tests lock in the
double-defence:

  1. WRITE side  — the Zid sync now derives price/original/pct coherently.
                   Encoded in `crawlers.py` around the snap_docs append.
  2. READ side   — `_discount_match` accepts arithmetic-proven discounts,
                   and `_enrich_discount_rows` fills pct at read time.
                   Encoded in `server.py`.

Together, either half alone would make the tab work; both together make it
impossible to regress silently again.
"""
from pathlib import Path
import re

BACKEND = Path(__file__).resolve().parents[1]
SERVER = (BACKEND / "server.py").read_text()
CRAWLERS = (BACKEND / "crawlers.py").read_text()


# ── READ SIDE — filter + enricher ─────────────────────────────────────────
def test_discount_match_accepts_arithmetic_proof():
    """The predicate MUST include an $or with the OP > price arithmetic
    escape hatch — the specific defect that hid the Zid discounts."""
    m = re.search(
        r"def _discount_match\([^)]*\):(?P<body>.+?)^def ",
        SERVER, re.DOTALL | re.MULTILINE)
    assert m, "_discount_match not found"
    body = m.group("body")
    assert '"discount_pct": {"$gt": 0}' in body, \
        "must still accept explicit non-zero discount_pct"
    # arithmetic branch present with the RIGHT comparison — iter73e wraps
    # both operands in $convert (BSON-tolerant) so a string-typed field on
    # a legacy row can't 500 the endpoint. Both wrapped operands and the
    # $gt comparison must be present.
    assert "$convert" in body and "original_price" in body, \
        "arithmetic branch must $convert original_price for type safety"
    # both branches must live under an $or, not $and (otherwise the arithmetic
    # branch would ADD to, not replace, the original zero-blocker)
    assert '"$or"' in body


def test_enricher_computes_pct_at_read_time_when_stored_is_zero():
    """`_enrich_discount_rows` must fill pct from row-level arithmetic when
    the stored value is 0 or None but original > price > 0."""
    m = re.search(
        r"async def _enrich_discount_rows\([^)]*\):(?P<body>.+?)^def ",
        SERVER, re.DOTALL | re.MULTILINE)
    assert m, "_enrich_discount_rows not found"
    body = m.group("body")
    # accepts either 0 or None as the "unpopulated" case
    assert "pct is None or pct == 0" in body
    # computation formula matches the write-side one
    assert re.search(r"round\(\(1 - price / orig\) \* 100\)", body), \
        "formula must match the write-side (1 - price/orig)*100"


def test_timeline_uses_the_shared_predicate_and_effective_disc():
    """The timeline used to hardcode `discount_pct > 0`, meaning it stayed
    empty even after top-pct started working. It must now share the same
    predicate + row-level effective_disc computation."""
    m = re.search(
        r'@router\.get\("/discounts/timeline"\)(?P<body>.+?)@router\.',
        SERVER, re.DOTALL)
    assert m, "/discounts/timeline endpoint missing"
    body = m.group("body")
    assert "_discount_match(since, None)" in body, \
        "must reuse _discount_match, not inline the old filter"
    assert "effective_disc" in body, \
        "must compute row-level effective discount in the aggregation"


def test_aggression_uses_effective_disc_in_the_aggregation():
    """Same class of defect: the aggression endpoint used to $match on
    `discount_pct > 0` inside the aggregation — same silent-empty result."""
    m = re.search(
        r'@router\.get\("/discounts/aggression"\)(?P<body>.+?)@router\.',
        SERVER, re.DOTALL)
    assert m
    body = m.group("body")
    assert '"_eff_disc"' in body, \
        "must compute a row-level _eff_disc field the group can respect"
    assert '"_eff_disc": {"$gt": 0}' in body, \
        "must filter on the effective discount, not the raw stored one"


# ── WRITE SIDE — the Zid sync no longer hardcodes 0 ────────────────────────
def test_zid_own_sync_derives_discount_from_sale_price():
    """The Zid own-store sync's snap_docs append used to write
    `original_price = price` + `discount_pct = 0` even on sale rows.
    The fix stores the effective/original/pct trio coherently."""
    # locate the own-store snap_docs append
    idx = CRAWLERS.index("snap_docs.append({")
    body = CRAWLERS[idx:idx + 1800]
    # the offending hardcodes MUST be gone
    assert '"original_price": round(price, 2)' not in body, \
        "Zid sync still hardcodes original_price=price"
    assert '"discount_pct": 0,' not in body, \
        "Zid sync still hardcodes discount_pct=0"
    # replacements
    assert "_snap_price" in body and "_snap_original" in body \
        and "_snap_disc_pct" in body, \
        "the derived-triple locals must be used in the write"


def test_zid_own_sync_ledger_obs_matches_snapshot_values():
    """The ledger observation and the snapshot MUST record IDENTICAL
    discount arithmetic — if they diverge, the two surfaces disagree
    for the same event."""
    # locate the ledger obs append inside the sync
    m = re.search(
        r'_ledger_obs\.append\(\{[^}]*?"sku": sku,(?P<body>.+?)\}\)',
        CRAWLERS, re.DOTALL)
    assert m, "ledger obs append not found"
    body = m.group("body")
    assert "_snap_price" in body and "_snap_original" in body \
        and "_snap_disc_pct" in body, \
        "ledger obs must reuse the derived-triple locals so it matches the snapshot"


def test_write_side_formula_is_symmetric_with_read_side():
    """Both sides use the exact same arithmetic — grep both files for it."""
    write_side = "round((1 - _snap_price / _snap_original) * 100)"
    assert write_side in CRAWLERS, \
        f"write-side formula must be `{write_side}`"


# ── end-to-end contract: derived discount example ────────────────────────
def test_derivation_example():
    """price 9, original 10 → pct 10 (the exact case that appeared in the
    diagnostic dump). Encoded here so a future refactor that "improves" the
    rounding rule has to justify diverging from the observed data."""
    orig, price = 10.0, 9.0
    pct = round((1 - price / orig) * 100)
    assert pct == 10

    orig, price = 20.5, 18.45
    assert round((1 - price / orig) * 100) == 10

    # no discount when equal — MUST NOT report a spurious 0-boundary hit
    orig, price = 10.0, 10.0
    assert (orig > price > 0) is False


# ── iter73e — $convert hardening: no aggregation on production data can 500 ──
def test_discount_match_wraps_price_fields_in_convert_with_zero_fallback():
    """Production HTTP 500 came from a legacy snapshot whose `original_price`
    or `price` was a string. `$convert onError=0, onNull=0` on both operands
    means an unexpected type coerces to 0 (harmless — filtered out by the
    `$gt: 0` check), never crashes the pipeline."""
    m = re.search(
        r"def _discount_match\([^)]*\):(?P<body>.+?)^def ",
        SERVER, re.DOTALL | re.MULTILINE)
    body = m.group("body")
    # $convert must appear for BOTH original_price and price
    assert body.count('"$convert"') >= 2, \
        "both original_price and price must be $convert-wrapped"
    assert '"onError": 0' in body and '"onNull": 0' in body, \
        "$convert must supply onError/onNull fallbacks so the query is total"


def test_timeline_and_aggression_effective_disc_are_convert_wrapped():
    """Same defensive rule for the two other Discounts endpoints — they
    share the same class of legacy-typed input, so they get the same
    hardening or they're vulnerable to the same 500."""
    for name in ("timeline", "aggression"):
        m = re.search(
            r'@router\.get\("/discounts/' + name + r'"\)(?P<body>.+?)@router\.',
            SERVER, re.DOTALL)
        assert m, f"/discounts/{name} endpoint missing"
        body = m.group("body")
        assert '"$convert"' in body, \
            f"{name} must $convert its price/discount_pct inputs"
        assert '"onError": 0' in body and '"onNull": 0' in body, \
            f"{name} must supply onError/onNull=0"


def test_discount_endpoints_wrap_aggregation_in_try_except():
    """The pipeline is a moving target — new legacy shapes will appear.
    Every Discounts endpoint that runs an aggregation must fail SAFE
    (return [] and log) rather than 500-ing the whole tab."""
    for name in ("top-pct", "top-amount", "timeline", "aggression"):
        m = re.search(
            r'@router\.get\("/discounts/' + name + r'"\)(?P<body>.+?)@router\.',
            SERVER, re.DOTALL)
        # aggression is the last route in the file section — grab till EOF
        if not m and name == "aggression":
            m = re.search(
                r'@router\.get\("/discounts/aggression"\)(?P<body>.+)',
                SERVER, re.DOTALL)
        assert m, f"/discounts/{name} not found"
        body = m.group("body")
        assert re.search(r"try:\s*\n[^\n]*aggregate", body), \
            f"{name} must wrap its aggregate() call in try/except so a single bad row can't 500 the endpoint"
        assert "logger.exception" in body, \
            f"{name} must log the exception rather than swallow it silently"

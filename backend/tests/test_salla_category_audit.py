"""iter73 — Salla Theme Coverage Audit tool contract.

Zarafa's silent invisibility (0 categories discovered on the homepage → 0
products → whole catalogue dark) had no monitoring behind it. `tools_
salla_category_audit.py` is the operator-facing health probe that would have
caught that class of failure before a client asked. These tests lock in:

  * the tool exists and is importable / runnable,
  * `audit_store` records the essential columns operators need,
  * the "at risk" flag correctly identifies stores below the healthy floor,
  * the admin endpoint contract (GET /api/admin/salla-category-audit) exists
    and reads from the expected collection.

The tests do NOT hit the live network — no Playwright, no Salla — so they
run in every environment.
"""
import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio

BACKEND = Path(__file__).resolve().parents[1]


def test_audit_tool_module_exists_and_parses():
    """The tool script is present and syntactically valid Python."""
    p = BACKEND / "tools_salla_category_audit.py"
    assert p.exists(), "tools_salla_category_audit.py missing"
    src = p.read_text()
    ast.parse(src)                             # raises on SyntaxError
    assert "MIN_HEALTHY_CATS" in src
    assert "salla_category_audits_latest" in src, \
        "must persist a 'latest' pointer for the admin endpoint"


def test_min_healthy_threshold_matches_the_reported_bar():
    """5 is the smallest healthy pet-store menu we've observed. If someone
    tightens this floor without also updating the endpoint / docs, this
    test forces the change to be intentional."""
    import importlib
    import sys
    sys.path.insert(0, str(BACKEND))
    mod = importlib.import_module("tools_salla_category_audit")
    assert mod.MIN_HEALTHY_CATS == 5


def test_admin_endpoint_registered_in_server():
    src = (BACKEND / "server.py").read_text()
    # exact route path & method as documented in the audit tool docstring
    assert '@router.get("/admin/salla-category-audit")' in src
    # reads from the 'latest' convenience doc, not the full audit collection
    assert "salla_category_audits_latest" in src


def test_admin_endpoint_returns_404_when_no_audit_exists():
    """Contract: rather than returning an empty payload the endpoint tells
    the operator to actually run the tool."""
    src = (BACKEND / "server.py").read_text()
    a = src.index('@router.get("/admin/salla-category-audit")')
    b = src.index("\n@router.", a + 1)
    body = src[a:b]
    assert "HTTPException(" in body and "404" in body, \
        "endpoint must raise 404 when no audit has been persisted"
    assert "tools_salla_category_audit.py" in body, \
        "operator must be pointed at the tool to run"


def test_at_risk_flag_reflects_threshold_correctly():
    """`audit_store` sets flagged_at_risk = (categories_discovered <
    MIN_HEALTHY_CATS). Boundary: EXACTLY 5 is OK (>=), 4 is at risk."""
    import importlib, sys
    sys.path.insert(0, str(BACKEND))
    mod = importlib.import_module("tools_salla_category_audit")
    # We can't run audit_store live, but we can lock in the meaning: patch
    # the two helpers to return crafted ids and check the flag & count.
    async def _run(ids):
        with patch.object(mod, "_capture_salla_store_identifier", AsyncMock(return_value="sid-x")), \
             patch.object(mod, "_discover_salla_category_ids", AsyncMock(return_value=ids)):
            # Fake Playwright object with the minimal shape the tool uses
            pw = MagicMock()
            browser = AsyncMock()
            browser.close = AsyncMock()
            browser.new_context = AsyncMock(return_value=AsyncMock(
                new_page=AsyncMock(return_value=MagicMock())))
            pw.chromium.launch = AsyncMock(return_value=browser)
            return await mod.audit_store(pw, {
                "id": "s1", "name": "Zarafa (fake)", "domain": "zarafaksa.com",
                "platform": "salla", "is_active": True,
            })

    # 0 cats — the Zarafa-era bug
    r = asyncio.run(_run([]))
    assert r["categories_discovered"] == 0
    assert r["flagged_at_risk"] is True

    # 4 — still under floor
    r = asyncio.run(_run(["1", "2", "3", "4"]))
    assert r["categories_discovered"] == 4
    assert r["flagged_at_risk"] is True

    # 5 — exactly the floor, healthy
    r = asyncio.run(_run(["1", "2", "3", "4", "5"]))
    assert r["categories_discovered"] == 5
    assert r["flagged_at_risk"] is False

    # 88 — Zarafa post-fix
    r = asyncio.run(_run([str(i) for i in range(88)]))
    assert r["categories_discovered"] == 88
    assert r["flagged_at_risk"] is False


def test_audit_report_records_sample_ids_capped_at_ten():
    """The persisted report should carry a small sample of ids for spot-check
    — not the full list, so a 400-cat store doesn't bloat the audit doc."""
    import importlib, sys
    sys.path.insert(0, str(BACKEND))
    mod = importlib.import_module("tools_salla_category_audit")
    ids = [str(1000 + i) for i in range(50)]

    async def _run():
        with patch.object(mod, "_capture_salla_store_identifier", AsyncMock(return_value="sid")), \
             patch.object(mod, "_discover_salla_category_ids", AsyncMock(return_value=ids)):
            pw = MagicMock()
            browser = AsyncMock(); browser.close = AsyncMock()
            browser.new_context = AsyncMock(return_value=AsyncMock(
                new_page=AsyncMock(return_value=MagicMock())))
            pw.chromium.launch = AsyncMock(return_value=browser)
            return await mod.audit_store(pw, {
                "id": "s2", "name": "Big Store", "domain": "big.example.com",
                "platform": "salla", "is_active": True,
            })

    r = asyncio.run(_run())
    assert r["categories_discovered"] == 50
    assert len(r["sample_ids"]) == 10          # capped so the audit doc stays lean
    assert r["sample_ids"] == ids[:10]


def test_exceptions_are_captured_not_raised():
    """A store that throws (network dead, Playwright crashed) must NOT abort
    the whole audit — the report captures the error and flags at_risk so
    the operator sees it in the summary."""
    import importlib, sys
    sys.path.insert(0, str(BACKEND))
    mod = importlib.import_module("tools_salla_category_audit")

    async def _run():
        pw = MagicMock()
        pw.chromium.launch = AsyncMock(side_effect=RuntimeError("browser crashed"))
        return await mod.audit_store(pw, {
            "id": "s3", "name": "Broken", "domain": "broken.example.com",
            "platform": "salla", "is_active": True,
        })

    r = asyncio.run(_run())
    assert r["error"] and "browser crashed" in r["error"]
    assert r["flagged_at_risk"] is True
    assert r["categories_discovered"] == 0

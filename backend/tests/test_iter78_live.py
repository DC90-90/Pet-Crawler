"""iter78 — live preview verification: pack guard on /scanner/opportunities
+ /admin/archive/* contracts and auth. Runs against the deployed preview URL.
"""
import gzip
import io
import json
import os
import re
import time

import pytest
import requests

BASE = "https://price-intel-dev.preview.emergentagent.com"
EMAIL = "a.disi@taqueen.sa"
PASSWORD = os.environ.get("DALEEL_TEST_PASSWORD", "")
DAY = "2026-08-25"


@pytest.fixture(scope="module")
def token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(EMAIL, PASSWORD)


@pytest.fixture(scope="module")
def H(token):
    return {"Authorization": f"Bearer {token}"}


# ── PACK GUARD ────────────────────────────────────────────────────────────────
def test_scanner_opportunities_returns_pack_guard_summary(H):
    r = requests.get(f"{BASE}/api/scanner/opportunities?days=14", headers=H, timeout=90)
    assert r.status_code == 200, r.text
    data = r.json()
    s = data.get("summary", {})
    for k in ("slug_pack_mismatch", "low_outliers_excluded",
              "slug_pack_mismatch_sample", "low_outliers_excluded_sample"):
        assert k in s, f"summary missing {k}: keys={list(s.keys())}"
    assert isinstance(s["slug_pack_mismatch_sample"], list)
    assert isinstance(s["low_outliers_excluded_sample"], list)

    # every row: market_lowest == min(seller prices)
    for row in data.get("opportunities", []):
        sellers = row.get("sellers") or []
        if not sellers:
            continue
        low = min(x["price"] for x in sellers)
        assert row["market_lowest"] == pytest.approx(low, rel=1e-3), (
            f"SKU {row.get('sku')} market_lowest={row['market_lowest']} vs sellers min={low}")

    # excluded samples must not appear in that SKU's seller list
    ex_map = {}
    for x in s["slug_pack_mismatch_sample"] + s["low_outliers_excluded_sample"]:
        ex_map.setdefault(x["sku"], set()).add(x.get("store_id") or x.get("store_name"))
    for row in data.get("opportunities", []):
        excluded_here = ex_map.get(row.get("sku"), set())
        for seller in row.get("sellers", []):
            sid = seller.get("store_id") or seller.get("store_name")
            assert sid not in excluded_here, (
                f"excluded seller {sid} still in sellers for SKU {row.get('sku')}")


def test_reported_skus_are_now_honest(H):
    r = requests.get(f"{BASE}/api/scanner/opportunities?days=14", headers=H, timeout=90)
    assert r.status_code == 200
    data = r.json()
    opps = {row["sku"]: row for row in data.get("opportunities", [])}
    # SKU 6928485301495 (45g toothpaste) must NOT appear
    assert "6928485301495" not in opps, (
        f"toothpaste still overpriced: {opps.get('6928485301495')}")
    # SKU 780348005638 (Kit Cat 15g sticks): market_lowest 10.0, gap_pct ~40.0
    kit = opps.get("780348005638")
    # Kit Cat may or may not be present depending on data; if present verify honest
    if kit is not None:
        assert kit["market_lowest"] == pytest.approx(10.0, abs=0.5), kit
        assert kit["gap_pct"] == pytest.approx(40.0, abs=2.0), kit


# ── ARCHIVE contract ─────────────────────────────────────────────────────────
def test_archive_status(H):
    r = requests.get(f"{BASE}/api/admin/archive/status", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    st = r.json()
    for k in ("configured", "days", "total_files", "total_rows", "total_bytes"):
        assert k in st, f"missing {k}: {list(st.keys())}"
    assert st["configured"] is True


def test_archive_files_for_target_day(H):
    r = requests.get(f"{BASE}/api/admin/archive/files?date={DAY}", headers=H, timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    files = body.get("files", body) if isinstance(body, dict) else body
    assert isinstance(files, list) and len(files) > 0, body
    kinds = {f.get("kind") for f in files}
    assert "snapshots" in kinds
    assert "manifest" in kinds or any("manifest" in (f.get("path") or "") for f in files)
    for f in files:
        assert "path" in f and "rows" in f and "bytes" in f, f


def test_archive_download_is_gz_jsonl(H):
    r = requests.get(f"{BASE}/api/admin/archive/files?date={DAY}", headers=H, timeout=30)
    files = r.json().get("files", r.json()) if isinstance(r.json(), dict) else r.json()
    snap = next((f for f in files if f.get("kind") == "snapshots"), None)
    assert snap is not None, files
    d = requests.get(f"{BASE}/api/admin/archive/download",
                     params={"path": snap["path"]}, headers=H, timeout=60)
    assert d.status_code == 200, d.text[:300]
    assert d.headers.get("content-type", "").startswith("application/gzip"), d.headers
    cd = d.headers.get("content-disposition", "")
    assert re.search(rf'{DAY}_[^"]+\.jsonl\.gz', cd), cd
    decompressed = gzip.decompress(d.content).decode()
    lines = [json.loads(l) for l in decompressed.splitlines() if l.strip()]
    assert lines, "empty archive"
    row = lines[0]
    # required fields per spec
    for k in ("sku", "price"):
        assert k in row, row
    # at least SOME row should carry the optional fields
    has_optional = any(any(k in r for k in ("sale_price", "discount_pct",
                                            "qty_available", "in_stock", "product_url"))
                       for r in lines)
    assert has_optional, "no snapshot carried the extended fields"


def test_archive_run_is_idempotent(H):
    # count files before
    files_before = requests.get(f"{BASE}/api/admin/archive/files?date={DAY}",
                                headers=H, timeout=30).json()
    fb = files_before.get("files", files_before) if isinstance(files_before, dict) else files_before
    count_before = len(fb)

    r = requests.post(f"{BASE}/api/admin/archive/run",
                      json={"date": DAY}, headers=H, timeout=60)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True
    assert body.get("status") == "started"
    time.sleep(3)

    files_after = requests.get(f"{BASE}/api/admin/archive/files?date={DAY}",
                               headers=H, timeout=30).json()
    fa = files_after.get("files", files_after) if isinstance(files_after, dict) else files_after
    assert len(fa) == count_before, f"idempotency broken: {count_before} -> {len(fa)}"


# ── AUTH ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,method,params", [
    ("/api/admin/archive/status", "GET", None),
    ("/api/admin/archive/files", "GET", {"date": DAY}),
    ("/api/admin/archive/download", "GET", {"path": "x"}),
    ("/api/admin/archive/run", "POST", None),
])
def test_archive_rejects_unauth(path, method, params):
    if method == "GET":
        r = requests.get(f"{BASE}{path}", params=params, timeout=15)
    else:
        r = requests.post(f"{BASE}{path}", json={"date": DAY}, timeout=15)
    assert r.status_code in (401, 403), f"{path} returned {r.status_code}"

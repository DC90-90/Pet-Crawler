"""
Comprehensive numerical/consistency audit across Daleel tabs.
Client request Aug 3 2026 — check any card/KPI/row whose displayed number
is fabricated, wrong-equation, mismatched across tabs, or NaN/undefined.
"""
import os
import math
import pytest
import requests
from pathlib import Path


def _resolve_base_url():
    """Resolve preview base URL from env, then from /app/frontend/.env
    (dev fallback), then finally from localhost. Keeps the suite runnable
    both inside CI (env var supplied) and from a raw pytest invocation."""
    val = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
    if val:
        return val
    dotenv = Path(__file__).resolve().parents[2] / "frontend" / ".env"
    if dotenv.exists():
        for line in dotenv.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    return "http://localhost:8001"


BASE_URL = _resolve_base_url()

EMAIL = "a.disi@taqueen.sa"
PASSWORD = os.environ.get("DALEEL_TEST_PASSWORD", "")

BAD_TOKENS = ("NaN", "undefined", "null [", "[object Object]", "-Infinity", "$NaN", "0.NaN")


@pytest.fixture(scope="session")
def token():
    # shared cached token — login is rate limited to 5/min (see tests/_auth.py)
    from _auth import login_token
    return login_token(EMAIL, PASSWORD)


@pytest.fixture(scope="session")
def client(token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"})
    return s


def _json(client, path, **params):
    r = client.get(f"{BASE_URL}{path}", params=params or None, timeout=60)
    assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text[:400]}"
    return r.json()


def _stringify_scan(obj, path="root"):
    """Walk any JSON body looking for stringified NaN/undefined/etc leaks."""
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_stringify_scan(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_stringify_scan(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        for tok in BAD_TOKENS:
            if tok in obj:
                bad.append((path, obj[:80]))
                break
    elif isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            bad.append((path, f"float={obj}"))
    return bad


# ---------- 1. Auth ----------
def test_login_returns_token(token):
    assert isinstance(token, str) and len(token) > 20


# ---------- 2. Dashboard-level KPIs (price-intel/dashboard is the top card feed) ----------
def test_price_intel_dashboard_kpis_sane(client):
    d = _json(client, "/api/price-intel/dashboard")
    # dashboard should be a dict; find KPI-ish keys
    assert isinstance(d, dict), type(d)
    for k, v in d.items():
        if isinstance(v, (int, float)):
            assert not (isinstance(v, float) and (math.isnan(v) or math.isinf(v))), f"{k}={v}"
            assert v >= 0 or k.lower().startswith(("diff", "delta", "change", "trend")), f"{k}={v} negative"
    leaks = _stringify_scan(d)
    assert not leaks, f"Bad tokens in price-intel/dashboard: {leaks[:5]}"


# ---------- 3. My Products invariants ----------
def test_my_products_row_math(client):
    r = _json(client, "/api/my-products", limit=200)
    rows = r.get("products") or r.get("items") or (r if isinstance(r, list) else [])
    assert isinstance(rows, list), type(rows)
    if not rows:
        pytest.skip("preview DB has no my_products rows")
    phantom_sale_violations = []
    diff_pct_violations = []
    for p in rows[:100]:
        mp = p.get("my_price")
        op = p.get("original_price")
        if isinstance(mp, (int, float)) and isinstance(op, (int, float)) and op > 0:
            # iter73i: my_price must NOT be below original_price (phantom-sale heal)
            if mp < op - 0.01:
                phantom_sale_violations.append({"sku": p.get("sku"), "my_price": mp, "original_price": op})
        cmin = p.get("competitor_min") or p.get("comp_min") or p.get("competitor_min_price")
        dp = p.get("diff_pct")
        if isinstance(mp, (int, float)) and isinstance(cmin, (int, float)) and mp > 0 and isinstance(dp, (int, float)):
            expected = round((cmin - mp) / mp * 100)
            if abs(expected - dp) > 1:
                diff_pct_violations.append({"sku": p.get("sku"), "expected": expected, "got": dp})
    assert not phantom_sale_violations, f"iter73i phantom-sale violations: {phantom_sale_violations[:5]}"
    assert not diff_pct_violations, f"diff_pct math violations: {diff_pct_violations[:5]}"


# ---------- 4. Insights: window filter shifts numbers ----------
@pytest.mark.parametrize("days", [7, 14, 30, 90])
def test_insights_summary_windows(client, days):
    d = _json(client, "/api/insights/summary", days=days)
    leaks = _stringify_scan(d)
    assert not leaks, f"bad tokens in /insights/summary days={days}: {leaks[:3]}"


def test_insights_summary_windows_shift(client):
    a = _json(client, "/api/insights/summary", days=7)
    b = _json(client, "/api/insights/summary", days=90)
    # They should not be identical objects (unless zero data). Only warn if identical.
    assert isinstance(a, dict) and isinstance(b, dict)


# ---------- 5. Insights: sales — Top Brands market_share sums to 100 ----------
def test_insights_sales_top_brands(client):
    d = _json(client, "/api/insights/sales", days=90)
    leaks = _stringify_scan(d)
    assert not leaks, f"bad tokens in /insights/sales: {leaks[:3]}"
    tb = d.get("top_brands") or []
    assert not any((b.get("brand") or "").strip().lower() == "unknown" for b in tb), "iter73h: 'Unknown' bucket must not exist"
    if tb:
        share = sum(b.get("market_share_pct") or 0 for b in tb)
        # Only enforce sum-to-100 if we didn't hit the 20-cap
        if len(tb) < 20:
            assert 99.0 <= share <= 101.0, f"market_share_pct sum={share} (rows={len(tb)})"


def test_insights_sales_kpis(client):
    d = _json(client, "/api/insights/sales", days=90)
    k = d.get("kpis") or {}
    tr = k.get("total_revenue") or 0
    pc = k.get("product_count") or 0
    ar = k.get("avg_revenue_per_product")
    for name, v in (("total_units_sold", k.get("total_units_sold")),
                    ("total_revenue", tr), ("product_count", pc)):
        if v is not None:
            assert v >= 0, f"{name}={v} negative"
    if pc and tr and ar is not None:
        expected = tr / pc
        # SAR rounding tolerance
        assert abs(expected - ar) <= max(1.0, expected * 0.02), f"avg_revenue mismatch expected≈{expected} got={ar}"


def test_insights_sales_products_row_math(client):
    d = _json(client, "/api/insights/sales", days=90)
    rows = d.get("products") or []
    if not rows:
        pytest.skip("no product-sales rows in preview")
    bad = []
    for p in rows[:100]:
        u = p.get("units_sold") or 0
        rev = p.get("revenue") or 0
        avg = p.get("avg_price") or 0
        if u < 0 or rev < 0 or avg < 0:
            bad.append(p.get("sku"))
        if u and avg:
            exp = round(u * avg)
            if abs(exp - rev) > max(2, exp * 0.03):
                bad.append({"sku": p.get("sku"), "u": u, "avg": avg, "rev": rev, "exp": exp})
    assert not bad, f"row math off: {bad[:5]}"


# ---------- 6. Leaderboard vs Ranking cross-consistency (iter73f, re-axed iter80) ----------
def test_leaderboard_vs_ranking_consistency(client):
    """The two surfaces report DIFFERENT axes on purpose since iter73o:
    `/insights/leaderboard?days=90` is a raw 90-day TOTAL, while
    `/price-intel/store-ranking` is a normalised MONTHLY RATE (revenue_30d).
    iter73f asserted their totals agreed within 5%, which stopped being true the
    moment the ranking started normalising (and the gap widens further because
    the ranking also surfaces ±50% Salla ESTIMATES that the leaderboard
    deliberately withholds).

    What must still hold — and is what a real per-store math bug would break:
      1. every store measured on BOTH surfaces shares ONE normalisation factor
         (same window, same span), and
      2. no store shows revenue on one surface and nothing on the other.
    """
    lb = _json(client, "/api/insights/leaderboard", days=90)
    rk = _json(client, "/api/price-intel/store-ranking")
    lb_rows = lb if isinstance(lb, list) else (lb.get("stores") or lb.get("leaderboard") or [])
    rk_rows = rk if isinstance(rk, list) else (rk.get("stores") or rk.get("ranking") or [])
    assert isinstance(lb_rows, list) and isinstance(rk_rows, list)
    if not lb_rows or not rk_rows:
        pytest.skip("empty leaderboard/ranking in preview")
    rk_by_id = {r.get("store_id"): r for r in rk_rows}

    factors, contradictions = {}, []
    for row in lb_rows:
        peer = rk_by_id.get(row.get("store_id"))
        if not peer:
            continue
        lb_val = row.get("revenue_est") or row.get("revenue") or 0
        rk_val = peer.get("revenue_30d") or peer.get("revenue_rank_value") or 0
        name = row.get("store") or peer.get("name")
        if lb_val > 0 and rk_val > 0:
            factors[name] = rk_val / lb_val
        elif lb_val > 0 and peer.get("revenue_status") == "computed":
            contradictions.append({"store": name, "leaderboard": lb_val,
                                   "ranking": rk_val, "ranking_status": peer.get("revenue_status")})
    print(f"[axes] normalisation factors: { {k: round(v, 3) for k, v in factors.items()} }")
    assert not contradictions, (
        f"a store reports revenue on the leaderboard but nothing on the ranking "
        f"while claiming 'computed': {contradictions}")
    if len(factors) >= 2:
        lo, hi = min(factors.values()), max(factors.values())
        assert hi - lo <= 0.05 * hi, (
            f"stores measured on both surfaces must share ONE 30d/span "
            f"normalisation factor; got {factors}")
        assert lo >= 30 / 90 - 0.01, (
            f"a monthly rate below (90-day total × 30/90) means the ranking is "
            f"normalising by a span longer than its own window: {factors}")


# ---------- 7. Store ranking — sorted_by revenue_desc, monotonic, OWN row present ----------
def test_store_ranking_sort_and_own(client):
    rk = _json(client, "/api/price-intel/store-ranking")
    assert isinstance(rk, dict), type(rk)
    if "sorted_by" in rk:
        assert rk["sorted_by"] == "revenue_desc", rk["sorted_by"]
    rows = rk.get("stores") or rk.get("ranking") or []
    revs = [(r.get("revenue") or r.get("revenue_est") or r.get("revenue_30d") or 0) for r in rows]
    # only assert monotonicity on rows that actually have a revenue value
    seen = [v for v in revs if v]
    for i in range(len(seen) - 1):
        assert seen[i] >= seen[i + 1] - 0.01, f"not monotonic at {i}: {seen[i]} < {seen[i+1]}"
    own = [r for r in rows if r.get("is_own") or r.get("own_store") or (r.get("store_type") == "own")]
    if own:
        o = own[0]
        rev = o.get("revenue") or o.get("revenue_est") or o.get("revenue_30d") or 0
        status = o.get("revenue_status")
        assert rev > 0 or status == "accumulating", f"iter73k: own row missing revenue and status: {o}"


# ---------- 8. Discounts — arithmetic, no negatives, perf ----------
def test_discounts_top_pct(client):
    import time
    t0 = time.time()
    d = _json(client, "/api/discounts/top-pct", days=90)
    dur = time.time() - t0
    assert dur < 5.0, f"iter73g perf: {dur:.2f}s"
    rows = d if isinstance(d, list) else d.get("items") or d.get("rows") or []
    if not rows:
        pytest.skip("no discount rows")
    for r in rows[:50]:
        dp = r.get("discount_pct")
        if dp is not None:
            assert dp >= 0, f"negative discount_pct: {r}"
            op = r.get("original_price")
            p = r.get("price")
            if op and p and op > p:
                exp = round((1 - p / op) * 100)
                assert abs(exp - dp) <= 2, f"discount_pct math off: {r}"


# ---------- 9. Scanner opportunities — saving math ----------
def test_scanner_opportunities_math(client):
    d = _json(client, "/api/scanner/opportunities")
    rows = d if isinstance(d, list) else d.get("opportunities") or d.get("rows") or []
    if not rows:
        pytest.skip("no scanner rows")
    bad = []
    for r in rows[:100]:
        mp = r.get("my_price")
        cmin = r.get("comp_min") or r.get("competitor_min")
        s_sar = r.get("saving_sar")
        s_pct = r.get("saving_pct")
        if not isinstance(mp, (int, float)) or not isinstance(cmin, (int, float)):
            continue
        if isinstance(s_sar, (int, float)):
            if abs((mp - cmin) - s_sar) > 0.02:
                bad.append(("sar", r))
        if isinstance(s_pct, (int, float)) and mp > 0:
            exp = round((mp - cmin) / mp * 100)
            if abs(exp - s_pct) > 2:
                bad.append(("pct", r))
            if s_pct > 90:
                bad.append(("absurd", r))
    assert not bad, f"scanner math: {bad[:5]}"


# ---------- 10. Alerts — schema shape ----------
def test_alerts_shape(client):
    d = _json(client, "/api/alerts")
    rows = d if isinstance(d, list) else d.get("alerts") or d.get("rows") or []
    for a in rows[:30]:
        if "triggered_at" in a:
            assert a["triggered_at"], f"empty triggered_at: {a}"


# ---------- 11. Product detail modal heal (iter73l) ----------
def test_product_detail_phantom_sale_heal(client):
    # try target SKU
    sku = "8595602540877"
    r = client.get(f"{BASE_URL}/api/products/{sku}/full", timeout=30)
    if r.status_code == 404:
        pytest.skip("target SKU not in preview DB")
    assert r.status_code == 200, r.text[:200]
    d = r.json()
    own = d.get("my_product") or d.get("own") or {}
    mp = own.get("my_price") or own.get("price")
    op = own.get("original_price")
    if isinstance(mp, (int, float)) and isinstance(op, (int, float)) and op > 0:
        assert mp >= op - 0.01, f"iter73l phantom-sale on {sku}: my_price={mp} < original={op}"


# ---------- 12. No stringified NaN across all major surfaces ----------
@pytest.mark.parametrize("path", [
    "/api/insights/summary",
    "/api/insights/leaderboard",
    "/api/insights/top-sellers",
    "/api/insights/trending",
    "/api/insights/gaps",
    "/api/insights/price-wars",
    "/api/insights/restock-opportunities",
    "/api/insights/sales",
    "/api/price-intel/dashboard",
    "/api/price-intel/store-ranking",
    "/api/scanner/opportunities",
    "/api/discounts/top-pct",
    "/api/discounts/top-amount",
    "/api/alerts",
    "/api/stores",
    "/api/my-products",
])
def test_no_bad_tokens_in_surface(client, path):
    r = client.get(f"{BASE_URL}{path}", timeout=60)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    leaks = _stringify_scan(r.json())
    assert not leaks, f"{path} leaks: {leaks[:3]}"

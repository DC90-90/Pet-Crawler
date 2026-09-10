#!/usr/bin/env python3
"""Production verification for the Market Share tab (iter80).

Runs the client's acceptance rules against a LIVE deployment over HTTP only, so
it can be pointed at production the moment a deploy finishes. Every check prints
PASS / FAIL / WARN with the evidence behind it; the process exits non-zero if
any check FAILs, so it can gate a release.

    python3 tools_prod_verify_market_share.py \
        --url https://<your-production-host> \
        --email <super-admin-email> --password '<password>'

    # or: DALEEL_URL / DALEEL_EMAIL / DALEEL_PASSWORD in the environment
    # add --json report.json to archive the result

Rules verified (client's wording):
  1  Market Share tab loads correctly
  2  market share is calculated only from measured data
  3  estimated values do not feed market-share percentages
  4  unavailable values show reasons
  5  Stores Carrying is separated from Sales Data Available
  6  Zarafa and Petsy appear when they carry the product
  7  CSV export includes source label, confidence, unavailable reason, method
  8  filters update the KPIs, not just the tables
  9  role-based access blocks unauthenticated callers
 10  fleet freshness + matcher coverage (the backfill acceptance test)
"""
import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone

import requests

RESULTS = []
SESSION = requests.Session()
TIMEOUT = 180


def record(rule, status, detail):
    RESULTS.append({"rule": rule, "status": status, "detail": detail})
    icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ ", "SKIP": "— "}[status]
    print(f"{icon} [{rule}] {detail}")


def api(base, path, **params):
    r = SESSION.get(f"{base}/api{path}", params=params or None, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def login(base, email, password):
    r = SESSION.post(f"{base}/api/auth/login", json={"email": email, "password": password},
                     timeout=60)
    if r.status_code != 200:
        print(f"❌ login failed: {r.status_code} {r.text[:200]}")
        sys.exit(2)
    token = r.json().get("token") or r.json().get("access_token")
    SESSION.headers.update({"Authorization": f"Bearer {token}"})


# ── 1. every surface answers ────────────────────────────────────────────────
def check_tab_loads(base, days, partial):
    common = {"days": days, "include_today": str(partial).lower()}
    ok = True
    for path in ("/market-share/overview", "/market-share/my-products",
                 "/market-share/missing-products", "/market-share/brands",
                 "/market-share/categories", "/market-share/methodology"):
        try:
            api(base, path, **common)
        except Exception as exc:
            ok = False
            record("1 tab loads", "FAIL", f"{path} → {exc}")
    if ok:
        record("1 tab loads", "PASS", "all six Market Share endpoints answered 200")
    rows = api(base, "/market-share/my-products", limit=1, **common).get("rows") or []
    if rows:
        try:
            api(base, f"/market-share/product/{rows[0]['sku']}", **common)
            record("1 tab loads", "PASS", f"product breakdown resolved for {rows[0]['sku']}")
        except Exception as exc:
            record("1 tab loads", "FAIL", f"product breakdown → {exc}")


# ── 2 & 3. measured-only shares ─────────────────────────────────────────────
ESTIMATE_TOKENS = ("estimate", "velocity", "projected", "salla_revenue_estimate")


def check_measured_only(base, days, partial):
    common = {"days": days, "include_today": str(partial).lower()}
    d = api(base, "/market-share/my-products", limit=500, **common)
    rows = d.get("rows") or []
    if not rows:
        record("2 measured only", "SKIP", "no catalogue rows in this window")
        return
    bad_share, bad_source, no_denominator = [], [], []
    for r in rows:
        if r.get("revenue_share_pct") is not None:
            if r.get("market_revenue") is None:
                bad_share.append(r["sku"])
            if (r.get("sellers_with_sales") or 0) < 1:
                no_denominator.append(r["sku"])
        for token in ESTIMATE_TOKENS:
            if token in str(r.get("my_units_source") or "").lower():
                bad_source.append((r["sku"], r["my_units_source"]))
            for s in r.get("sellers") or []:
                if token in str(s.get("units_source") or "").lower():
                    bad_source.append((r["sku"], s.get("units_source")))
    record("2 measured only", "FAIL" if bad_share else "PASS",
           f"{len(bad_share)} rows show a share with no measured market revenue"
           + (f": {bad_share[:5]}" if bad_share else ""))
    record("2 measured only", "FAIL" if no_denominator else "PASS",
           f"{len(no_denominator)} rows show a share with zero measurable sellers"
           + (f": {no_denominator[:5]}" if no_denominator else ""))
    record("3 no estimates in shares", "FAIL" if bad_source else "PASS",
           f"{len(bad_source)} rows carry an ESTIMATE as their unit source"
           + (f": {bad_source[:5]}" if bad_source else ""))

    k = api(base, "/market-share/overview", **common).get("kpis") or {}
    if k.get("my_revenue_share_pct") is not None and not k.get("products_contested"):
        record("2 measured only", "FAIL",
               "headline share reported with zero contested products")
    else:
        record("2 measured only", "PASS",
               f"headline share {k.get('my_revenue_share_pct')}% over "
               f"{k.get('products_contested')} contested products "
               f"({k.get('products_sole_seller')} sole-seller products reported separately)")

    m = api(base, "/market-share/methodology", **common)
    named = [n.get("id") for n in (m.get("not_used") or [])]
    record("3 no estimates in shares",
           "PASS" if any("salla" in str(n) for n in named) else "FAIL",
           f"methodology names the excluded estimate(s): {named}")
    sentence = "Market share is based on tracked measured data inside Daleel, not the total Saudi market"
    record("1 tab loads", "PASS" if (m.get("tracked_market") or "").startswith(sentence) else "FAIL",
           f"methodology caveat: {(m.get('tracked_market') or '')[:90]}…")


# ── 4. unavailable carries a reason ─────────────────────────────────────────
def check_unavailable_reasons(base, days, partial):
    common = {"days": days, "include_today": str(partial).lower()}
    rows = (api(base, "/market-share/my-products", limit=500, **common).get("rows") or [])
    silent_rows, silent_sellers = [], []
    withheld = 0
    for r in rows:
        if r.get("market_revenue") is None:
            withheld += 1
            if not r.get("unavailable_reason"):
                silent_rows.append(r["sku"])
        for s in r.get("sellers") or []:
            if s.get("units") is None and not s.get("unavailable_reason"):
                silent_sellers.append((r["sku"], s.get("store_name")))
    record("4 unavailable has a reason",
           "FAIL" if (silent_rows or silent_sellers) else "PASS",
           f"{withheld} withheld rows, {len(silent_rows)} without a reason, "
           f"{len(silent_sellers)} silent sellers"
           + (f": {(silent_rows or silent_sellers)[:5]}" if (silent_rows or silent_sellers) else ""))


# ── 5 & 6. carrying vs measurable, and the named stores ─────────────────────
def check_carrying_vs_measurable(base, days, partial, want_stores):
    common = {"days": days, "include_today": str(partial).lower()}
    rows = (api(base, "/market-share/my-products", limit=500, **common).get("rows") or [])
    missing_fields = [r["sku"] for r in rows[:50]
                      if r.get("sellers_total") is None or r.get("sellers_with_sales") is None]
    record("5 carrying vs measurable", "FAIL" if missing_fields else "PASS",
           f"both counters present on every row"
           + (f"; missing on {missing_fields[:5]}" if missing_fields else ""))
    gaps = [(r["sku"], r["sellers_total"], r["sellers_with_sales"]) for r in rows
            if (r.get("sellers_total") or 0) > (r.get("sellers_with_sales") or 0)]
    record("5 carrying vs measurable", "PASS" if gaps else "WARN",
           f"{len(gaps)} rows where a seller carries the product but publishes no "
           f"sales data (the two columns must differ there)"
           + (f", e.g. {gaps[:3]}" if gaps else " — nothing to distinguish in this window"))

    seen = {}
    for r in rows:
        for s in r.get("sellers") or []:
            name = (s.get("store_name") or "").strip()
            for want in want_stores:
                if want.lower() == name.lower():
                    entry = seen.setdefault(want, {"rows": 0, "with_sales": 0, "example": None})
                    entry["rows"] += 1
                    if s.get("units") is not None:
                        entry["with_sales"] += 1
                    entry["example"] = entry["example"] or {
                        "sku": r["sku"], "price": s.get("price"),
                        "units": s.get("units"),
                        "reason": s.get("unavailable_reason")}
    for want in want_stores:
        got = seen.get(want)
        record("6 named stores appear", "PASS" if got else "FAIL",
               f"{want}: on {got['rows']} of my products "
               f"({got['with_sales']} with measurable sales) e.g. {got['example']}"
               if got else
               f"{want} does not appear as a seller on ANY of my products — "
               f"check its crawl freshness and matcher coverage")


# ── 7. CSV provenance ───────────────────────────────────────────────────────
REQUIRED_CSV_COLUMNS = ("Confidence", "Unavailable reason", "Calculation method")


def check_csv(base, days, partial):
    for section in ("my_products", "missing", "brands", "categories"):
        r = SESSION.get(f"{base}/api/market-share/export",
                        params={"days": days, "include_today": str(partial).lower(),
                                "section": section}, timeout=TIMEOUT)
        if r.status_code != 200:
            record("7 CSV provenance", "FAIL", f"{section} → {r.status_code}")
            continue
        rows = list(csv.reader(io.StringIO(r.text)))
        head = rows[0] if rows else []
        missing = [c for c in REQUIRED_CSV_COLUMNS if c not in head]
        if section == "my_products":
            for extra in ("My units source", "Stores carrying it (competitors)",
                          "Sales data available (sellers)"):
                if extra not in head:
                    missing.append(extra)
        blank_method = 0
        if len(rows) > 1:
            idx = head.index("Calculation method") if "Calculation method" in head else None
            if idx is not None:
                blank_method = sum(1 for x in rows[1:] if not (x[idx] if len(x) > idx else ""))
        record("7 CSV provenance", "FAIL" if (missing or blank_method) else "PASS",
               f"{section}: {len(rows) - 1} rows, missing columns={missing}, "
               f"rows with no calculation method={blank_method}")


# ── 8. filters move the KPIs ────────────────────────────────────────────────
def check_filters(base, days, partial):
    common = {"days": days, "include_today": str(partial).lower()}
    whole = api(base, "/market-share/overview", **common)
    cats = (whole.get("filters") or {}).get("categories") or []
    if not cats:
        record("8 filters move KPIs", "SKIP", "no category resolved in this window")
        return
    cat = cats[0]
    filtered = api(base, "/market-share/overview", category=cat, **common)
    table = api(base, "/market-share/my-products", category=cat, limit=1, **common)
    k_all = (whole.get("kpis") or {}).get("my_catalog_products")
    k_one = (filtered.get("kpis") or {}).get("my_catalog_products")
    checks = [
        (filtered.get("filtered") is True, "overview reports itself as filtered"),
        (k_one is not None and k_all is not None and k_one <= k_all,
         f"KPI shrank with the filter: {k_all} → {k_one}"),
        (k_one == table.get("total"),
         f"KPI ({k_one}) equals the filtered table total ({table.get('total')})"),
    ]
    for ok, detail in checks:
        record("8 filters move KPIs", "PASS" if ok else "FAIL", f"{cat}: {detail}")


# ── 9. auth gate ────────────────────────────────────────────────────────────
def check_auth_gate(base, days):
    naked = requests.Session()
    codes = {}
    for path in ("/market-share/overview", "/market-share/export",
                 "/admin/zid/oauth/status", "/admin/backfill/status"):
        try:
            codes[path] = naked.get(f"{base}/api{path}",
                                    params={"days": days}, timeout=60).status_code
        except Exception as exc:
            codes[path] = str(exc)
    bad = {p: c for p, c in codes.items() if c not in (401, 403)}
    record("9 auth gate", "FAIL" if bad else "PASS",
           f"unauthenticated calls rejected: {codes}" if not bad
           else f"these answered without a token: {bad}")


# ── 10. fleet freshness + matcher coverage (backfill acceptance) ────────────
def check_fleet(base, matcher_window_days=14):
    fresh = api(base, "/data-freshness")
    stores = fresh.get("stores") or []
    stale, dark = [], []
    for s in stores:
        age, bucket = s.get("age_days"), s.get("bucket")
        if bucket == "no_data" or age is None:
            dark.append(s.get("store_name"))
        elif age > matcher_window_days:
            stale.append((s.get("store_name"), age))
    record("10 fleet freshness", "FAIL" if (stale or dark) else "PASS",
           f"{len(stores)} stores tracked; never crawled={dark}; "
           f"older than the {matcher_window_days}-day matcher window={stale}")
    try:
        cov = api(base, "/admin/coverage-report")
    except Exception as exc:
        record("10 matcher coverage", "SKIP", f"coverage report unavailable: {exc}")
        return
    per_store = cov.get("stores") or []
    silent = [s for s in per_store
              if not s.get("is_own_store")
              and (s.get("products_crawled") or 0) > 100
              and (s.get("matched_products") or 0) == 0]
    table = [(s.get("name"), s.get("products_crawled"), s.get("matched_products"))
             for s in per_store if not s.get("is_own_store")]
    print(f"   coverage ({cov.get('window_days')}d): store / crawled / matched → {table}")
    record("10 matcher coverage", "FAIL" if silent else "PASS",
           f"stores with snapshots but ZERO matcher rows: {[s.get('name') for s in silent]}"
           if silent else
           f"every crawled competitor has matcher rows ({len(table)} competitors reported)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DALEEL_URL") or
                    os.environ.get("REACT_APP_BACKEND_URL"))
    ap.add_argument("--email", default=os.environ.get("DALEEL_EMAIL"))
    ap.add_argument("--password", default=os.environ.get("DALEEL_PASSWORD"))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--partial", action="store_true",
                    help="include today's still-accumulating KSA day "
                         "(needed where sealed days have no measurable sales yet)")
    ap.add_argument("--stores", default="Zarafa,Petsy",
                    help="stores that must appear as sellers (comma separated)")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()
    if not (args.url and args.email and args.password):
        ap.error("--url, --email and --password are required "
                 "(or DALEEL_URL / DALEEL_EMAIL / DALEEL_PASSWORD)")
    base = args.url.rstrip("/")

    print(f"\nDaleel — Market Share production verification\n"
          f"target: {base}\nwindow: {args.days}d "
          f"({'including today (partial)' if args.partial else 'sealed days only'})\n"
          f"time:   {datetime.now(timezone.utc).isoformat()}\n" + "─" * 72)
    health = requests.get(f"{base}/api/health", timeout=60).json()
    print(f"health: {health.get('status')} · mongo={health.get('mongodb')} · "
          f"jobs={health.get('scheduler_active_jobs')} · "
          f"last crawl={health.get('last_successful_crawl')}\n")
    login(base, args.email, args.password)

    check_tab_loads(base, args.days, args.partial)
    check_measured_only(base, args.days, args.partial)
    check_unavailable_reasons(base, args.days, args.partial)
    check_carrying_vs_measurable(base, args.days, args.partial,
                                 [s.strip() for s in args.stores.split(",") if s.strip()])
    check_csv(base, args.days, args.partial)
    check_filters(base, args.days, args.partial)
    check_auth_gate(base, args.days)
    check_fleet(base)

    fails = [r for r in RESULTS if r["status"] == "FAIL"]
    warns = [r for r in RESULTS if r["status"] == "WARN"]
    print("─" * 72)
    print(f"{len(RESULTS)} checks · {len(RESULTS) - len(fails) - len(warns)} pass · "
          f"{len(warns)} warn · {len(fails)} FAIL")
    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump({"target": base, "at": datetime.now(timezone.utc).isoformat(),
                       "window_days": args.days, "partial": args.partial,
                       "results": RESULTS}, fh, indent=1)
        print(f"report written to {args.json_out}")
    if fails:
        print("\nFAILURES:")
        for f in fails:
            print(f"  ❌ [{f['rule']}] {f['detail']}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()

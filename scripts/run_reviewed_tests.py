"""Run the reviewed gates and selected regressions with explicit local isolation.

Does not run the legacy live-auth suite, boot tasks, or production operations.
All test users and test data are disposable. No real credentials are printed.
"""
import os
import secrets
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from dotenv import dotenv_values
from pymongo import MongoClient

ROOT = Path(__file__).resolve().parents[1]
url = os.environ.get("DALEEL_TEST_MONGO_URL") or dotenv_values(ROOT / "backend/.env").get("MONGO_URL")
if not url or urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
    raise SystemExit("Refusing to test against a missing or non-loopback Mongo URL")
environment = dict(os.environ)
environment.update(MONGO_URL=url, DALEEL_TEST_MONGO_URL=url,
                   DB_NAME=f"test_reviewed_runner_{uuid.uuid4().hex}",
                   JWT_SECRET=secrets.token_urlsafe(48), ENCRYPTION_KEY=Fernet.generate_key().decode(),
                   WEBHOOK_CRON_SECRET=secrets.token_urlsafe(40),
                   SUPER_ADMIN_EMAIL="fixture-admin@example.test", SUPER_ADMIN_PASSWORD=secrets.token_urlsafe(32),
                   CORS_ORIGINS="https://allowed.example.test", SEED_DEMO_DATA="false",
                   ALLOW_PUBLIC_REGISTRATION="false", APP_ENV="test",
                   # Tests exercise the live compute path; the production
                   # cache-miss policy (rebuild → 503) must not leak in from .env.
                   CACHE_MISS_POLICY="live",
                   OBSERVATIONS_V2_SINCE="2000-01-01T00:00:00+00:00",
                   SALES_SOURCE="v2",
                   PYTHONPATH=os.pathsep.join([str(ROOT / "backend"), str(ROOT / "backend/tests")]))
groups = {
    "reviewed-core": ["test_findings_v2_regression", "test_iteration37_integration_real_mongo", "test_codex_review_gates"],
    "isolated-auth": ["test_findings_auth_isolated"],
    "real-source": ["test_iteration39_real_source_evidence"],
    "related-contracts": ["test_pack_count_guard", "test_ledger_phase1", "test_ledger_phase2", "test_own_store_vat_basis"],
    "six-acceptance": ["test_acceptance_six_regressions"],
    "four-correctness": ["test_four_correctness_regressions"],
    "matcher-parent-pool": ["test_matcher_parent_pool_regression"],
    "release-safety": ["test_release_safety"],
    # Oct 2026 production recovery: read budgets, cache keys and stale serving,
    # write path without the event_id index, leases, scheduler, crawl attempts,
    # heartbeats/resume, identity flags and measured-day revenue labels.
    "recovery-oct-2026": ["test_v2_since_bound", "test_read_budgets_and_page_cache", "test_cohort_memo",
                          "test_index_builds", "test_cache_loop_fixes", "test_stale_previous_revision",
                          "test_scoped_page_cache_keys", "test_snapshot_write_by_id", "test_recover_sealed_ledger",
                          "test_market_share_reasons", "test_lease_renewal", "test_scheduler_misfire",
                          "test_process_watch_and_resume", "test_identity_check", "test_measured_days",
                          "test_crawl_attempts", "test_store_categories", "test_category_map",
                          "test_pagination_rate_limit", "test_zid_variant_supplement", "test_full_export",
                          "test_ledger_sales", "test_stale_serve_age", "test_store_active_persists"],
}
report_dir = ROOT / "test_reports/pytest"
report_dir.mkdir(parents=True, exist_ok=True)
failed = []
try:
    for label, modules in groups.items():
        print(f"\n=== {label} ===", flush=True)
        args = [sys.executable, "-m", "pytest", "-q", *[f"backend/tests/{m}.py" for m in modules],
                f"--junitxml={report_dir / (label + '-final.xml')}"]
        if subprocess.run(args, cwd=ROOT, env=environment).returncode:
            failed.append(label)
finally:
    with MongoClient(url) as client:
        client.drop_database(environment["DB_NAME"])
if failed:
    raise SystemExit("Failed test groups: " + ", ".join(failed))
print("All selected test groups passed; no production or catalogue backfill operations executed.")
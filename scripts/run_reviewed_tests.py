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
                   PYTHONPATH=os.pathsep.join([str(ROOT / "backend"), str(ROOT / "backend/tests")]))
groups = {
    "reviewed-core": ["test_findings_v2_regression", "test_iteration37_integration_real_mongo", "test_codex_review_gates"],
    "isolated-auth": ["test_findings_auth_isolated"],
    "real-source": ["test_iteration39_real_source_evidence"],
    "related-contracts": ["test_pack_count_guard", "test_ledger_phase1", "test_ledger_phase2", "test_own_store_vat_basis"],
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
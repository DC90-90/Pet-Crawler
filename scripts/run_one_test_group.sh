#!/usr/bin/env bash
# Run one pytest target with the same disposable isolation as run_reviewed_tests.py.
set -euo pipefail
cd "$(dirname "$0")/.."
MONGO_URL="$(python - <<'EOF'
from dotenv import dotenv_values
print(dotenv_values("backend/.env")["MONGO_URL"])
EOF
)"
export MONGO_URL DALEEL_TEST_MONGO_URL="$MONGO_URL"
export DB_NAME="test_one_$(python -c 'import uuid;print(uuid.uuid4().hex)')"
export JWT_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
export ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
export WEBHOOK_CRON_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(40))')"
export SUPER_ADMIN_EMAIL="fixture-admin@example.test"
export SUPER_ADMIN_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(32))')"
export CORS_ORIGINS="https://allowed.example.test" SEED_DEMO_DATA="false" ALLOW_PUBLIC_REGISTRATION="false" APP_ENV="test"
export PYTHONPATH="backend:backend/tests"
trap 'python - <<EOF
from pymongo import MongoClient
import os
MongoClient(os.environ["MONGO_URL"]).drop_database(os.environ["DB_NAME"])
EOF' EXIT
python -m pytest -q "$@"

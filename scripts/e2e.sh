#!/usr/bin/env bash
# Run the Playwright e2e suite against a DB-less backend (in-process mock DB)
# plus the Vite dev server. Intended for local + CI use without a MongoDB.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export APP_ENV=development
export USE_MOCK_DB=true
export SEED_ON_STARTUP=true
export JWT_SECRET=${JWT_SECRET:-devsecretdevsecretdevsecretdevsecret}
export CSRF_SECRET=${CSRF_SECRET:-devcsrfdevcsrfdevcsrfdevcsrf}
export ADMIN_SEED_EMAIL=${ADMIN_SEED_EMAIL:-owner@example.com}
export ADMIN_SEED_PASSWORD=${ADMIN_SEED_PASSWORD:-ChangeMe!Now123}

echo "▶ starting backend (mock DB) on :8000"
( cd backend && PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8000 ) &
BACK_PID=$!
trap 'kill $BACK_PID 2>/dev/null || true' EXIT

# wait for backend
for i in $(seq 1 30); do
  if curl -sf http://localhost:8000/api/public/content-version >/dev/null; then break; fi
  sleep 1
done

echo "▶ running Playwright"
cd frontend
npx playwright test "$@"
